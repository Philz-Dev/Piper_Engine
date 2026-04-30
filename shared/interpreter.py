import json
import os
from shared.unpacked_data import UnZip
from functools import partial
import re
import inspect
import os
from dotenv import load_dotenv
import importlib
import yaml
from shared.auth_manger import start_auth_flow
from shared.tools import get_auth_config_file
from shared.tools import inspect_function, crawler, replace_place_value_v3, replace_place_value, retrieve_file, open_json_file, check_key_matches, input_manager
from typing import Dict, Any, List
from shared.tools import retrieve_file, replace_place_value, crawler, missing_field, load_schema_registry
from shared.registry_V2 import PiperRegistry

class PiperInterpreter:
    def __init__(self, registry, crypto_engine=None):
        self.registry = registry
        self.crypto_engine = crypto_engine
        self.manifest = {}

    @classmethod
    async def create(cls, registry, dsl_file, name, crypto_engine=None):
        # Now this matches the __init__ above
        instance = cls(registry, crypto_engine) 
        
        # This performs the actual manifest generation
        await instance.build_manifest(dsl_file, name)
        return instance
    
    async def build_manifest(self, dsl_file: Dict[str, Any], name: str) -> Dict[str, Any]:
        """
        The entry point. Converts DSL into the final execution dictionary.
        """
        # Process top-level sections
        for section, content in dsl_file.items():
            # If it's a workflow section (like 'pipeline' or 'on_start')
            if isinstance(content, list):
                self.manifest[section] = await self.registry.interpreter_map.get(section)(content, self.registry, self.crypto_engine, name)
        return self.manifest
    
async def run_pipeline(content: List, registry, crypto_engine, name, **kwargs):

    executable_block = []
    for n, step in enumerate(content):
        entry = {}
        
        # 1. Identify which managers are present in THIS step
        # We look at every key in the step and ask the Registry: "Who manages this?"
        for key, value in step.items():
            # Get the 'role' (e.g., 'an_id_manager', 'a_service_manager')
            role = registry.identify_manager_role(key) 
            
            if not role:
                continue # Skip keys that aren't managed (like 'version')

            specialist = registry.interpreter_map.get(key)
            if not specialist:
                continue

            # 2. Execute the specialist
            result = await specialist(
                step=step,
                key=key,
                value=value,
                registry=registry,
                crypto_engine=crypto_engine,
                name=name,
                func=run_pipeline # Pass for recursion
            )

            # 3. Determine Storage Logic (Merge vs Assign)
            # Senior Move: Let the Registry define if a role should 'merge'
            if registry.should_merge(key):
                entry.update(result)
            else:
                entry[key] = result
        executable_block.append(entry)

    return executable_block
    
async def recursive_step_manager(registry, step, key: str, value: str, crypto_engine, name, func):
    # Ensure we get the list from the correct key (e.g., 'steps' or 'on_error')
    target_content = step.get(key)
    
    if not isinstance(target_content, list):
        target_content = [target_content] 
        
    # Must pass 'name' back to the recursive function
    return await func(content=target_content, registry=registry, crypto_engine=crypto_engine, name=name)

async def assign_key_value(registry, step, key: str, value: str, crypto_engine, name, func):
    return step.get(key)

def service_func_config_keys(registry, step, service_key, prefix):
    handler = registry.sub_executor_map.get(prefix)
    if not handler:
        return {}
    handler_keys = registry.hydrate_from_handler(handler)
    config_keys = {ky: vl for ky, vl in step.items() if ky in handler_keys}
    return config_keys 

    
async def app_service(registry, step, key: str, value: str, crypto_engine, name, func):
    prefix = registry.service_prefix(service_key=key, service_value=value)
    list_of_value = value.split(".")
    if "." in value:
        app_name = list_of_value[0] if list_of_value[0] != prefix else list_of_value[1]
    else:
        app_name = value
    action = list_of_value[-1]
    if (p := registry.address_book_map.get(key)):
        if (e := registry.file_ext_map.get(key)):
            path = p + "/" + app_name + "/" + action + "." + e
    
    if not os.path.isabs(path):
        # Anchor to the directory of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_dir, path)
    config_keys = service_func_config_keys(registry=registry, step=step, service_key=key, prefix=prefix)

    service_config = registry._raw.get(key)
    dependencies = service_config.get("dependency", {}).get(prefix, {})
    prefix_list = []
    for k, v in step.items():
        role = registry.identify_manager_role(k)
        if role in dependencies:
            prefix_list.append(k)
    dependency_func = registry.find_dependency_func(sub_type="interpreter", registry=registry, step=step, dependencies=dependencies, prefix=prefix_list)
    sub_interpreter = {prefix: registry.sub_interpreter_map.get(prefix)}
    sub_interpreter_list = {**dependency_func, **sub_interpreter}
    app_schema = {}
    if sub_interpreter_list:
        for k, d in sub_interpreter_list.items():
            if d: # Safety check
                app_schema = await d(
                    key=k,
                    path=path,
                    value=value,
                    service=app_name,
                    client_name=name,
                    crypto_engine=crypto_engine,
                    current_step=step,
                    content_to_modify=app_schema
                )
    
    final_args = {**config_keys, **app_schema}
        
    return {
        "service_manager": key,
        "app_name": app_name,
        "action": action,
        "service_type": prefix,
        "args": final_args
    }

async def build_input_v2(path, current_step, crypto_engine, client_name, value, key, service, content_to_modify):
    key_matches = check_key_matches(service_path=path)
    app_schema = key_matches["app_schema"]
    found_items = key_matches["found_items"]["matched_items"]
    key_path = key_matches["found_items"]["key_path"]
    missing = missing_field(required=found_items, content_to_check=value)
    
    # Ensure input_data is a dict
    raw_input = current_step.get(key, {})
    input_data = raw_input if isinstance(raw_input, dict) else {}

    default_regex = r"Default\s*=\s*([\$\.\w\d_\-\s]+)" 

    if missing:
        for m in missing:
            missing_value = str(found_items.get(m))
            match = re.search(default_regex, missing_value)
            
            if match and m not in input_data:
                # EXTRACT ONLY THE VALUE: "$.Hubspot"
                extracted_val = match.group(1).strip()
                
                # Replace surgically using the V2 logic
                app_schema = replace_place_value_v3(
                    key_path=key_path, 
                    content_to_modify=app_schema, 
                    key=m, 
                    value=extracted_val,
                    is_metadata_replacement=True # CRITICAL
                )
                
                # Auth Logic
                if extracted_val.startswith("$."):
                    target_service = extracted_val.replace("$.", "")
                    app_path = get_auth_config_file(client_name=client_name, file_type="app_service", service=target_service)
                    w_f = retrieve_file(file_path=app_path, base_dir=True)
                    if w_f:
                        w_f.update({"client_name": client_name, "app_name": target_service})
                        await start_auth_flow(_cont=w_f, _crypto_engine=crypto_engine)
                continue

    # Handle explicit overrides
    for ke in found_items.keys():
        if ke in input_data:
            val = input_data.get(ke)
            app_schema["_args"] = replace_place_value_v3(
                key_path=key_path, content_to_modify=app_schema, key=ke, value=val, is_metadata_replacement=False
            )        
    return app_schema

async def build_input(path, current_step, crypto_engine, client_name, value, key, service, content_to_modify):

    key_matches = check_key_matches(service_path=path)
    app_schema = key_matches["app_schema"]
    found_items = key_matches["found_items"]["matched_items"]
    key_path =  key_matches["found_items"]["key_path"]
    missing = missing_field(required=found_items, content_to_check=value)
    input_data = current_step.get(key)
    default_regex = r"Default\s*=\s*([\$\.\w\d_\-\s]+)"
    if missing:
        for m in missing:
            missing_value = found_items.get(m)
            #match = re.search(r"Default\s*=\s*\$\.([\w\d_\-\s]+)", str(missing_value))
            match = re.search(default_regex, missing_value)
            
            input_data = current_step.get(key)
            if match and m not in input_data:
                transformed_value = f"{{{{{match.group(1).strip()}}}}}"
                # Update our schema tracking so replace_place_value uses the simplified string
                app_schema = replace_place_value(
                    key_path=key_path, 
                    content_to_modify=app_schema, 
                    key=m, 
                    value=transformed_value
                )
                app_path = get_auth_config_file(client_name=client_name, file_type="app_service", service=service)
                w_f = retrieve_file(file_path=app_path, base_dir=True)
                if w_f:
                    w_f["client_name"] = client_name
                    w_f["app_name"] = service
                    await start_auth_flow(_cont=w_f, _crypto_engine=crypto_engine)
                    continue
        for ke in found_items.keys():
            if not ke in input_data:
                continue
            val = input_data.get(ke)
            content_to_modify["_args"] = replace_place_value_v3(
                key_path=key_path, content_to_modify=app_schema, key=ke, value=val, is_metadata_replacement=True
            )        
    return content_to_modify

async def script_interpreter(current_step, value, content_to_modify, **_kwargs):
    """
    VALIDATOR: Resolves paths and ensures the script exists.
    Returns a manifest entry, but DOES NOT execute.
    """
    # 1. Resolve Extension
    RUNTIME_EXT_MAP = {
        "python": "py",
        "nodejs": "js",
        "node": "js"
    }
    runtime = current_step.get("runtime", "python").lower()
    ext = RUNTIME_EXT_MAP.get(runtime, "py")

    # 2. Resolve Paths
    path_parts = value.split('.')
    if path_parts[0] == "script":
        path_parts.pop(0) 
    
    relative_path = os.path.join(*path_parts) + f".{ext}"
    project_root = os.getcwd()
    absolute_script_path = os.path.abspath(os.path.join(project_root, relative_path))

    # 4. Return Metadata (The Manifest Entry)
    content_to_modify["_file_path"] = absolute_script_path
    return  content_to_modify

async def trigger(content: List, registry, crypto_engine, name):

    run_pipeline(content=content, registry=registry, crypto_engine=crypto_engine, name=name)

async def webhook_func(regs, service, action, cont, path, key=None):
    pass

async def timer_func():
    pass

async def version_interpreter(content: str, registry, crypto_engine, name):
    return content

