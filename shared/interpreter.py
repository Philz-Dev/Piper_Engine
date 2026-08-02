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
from shared.auth_manager import start_auth_flow
from shared.tools import get_auth_config_file
from shared.tools import inspect_function, crawler, replace_place_value_v3, replace_place_value, retrieve_file, open_json_file, check_key_matches, input_manager
from typing import Dict, Any, List
from shared.tools import retrieve_file, replace_place_value, crawler, missing_field, load_schema_registry, missing_field_v2
from shared.registry_V2 import PiperRegistry
from shared.database_manager import ContextDB
from shared.tools import resolve_service_instruction
from shared.reg_schema.schemaid import SchemaID
from shared.compiler import WorkflowCompiler

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
            self.manifest[section] = await self.registry.interpreter_map.get(section)(key=section, content=content, registry=self.registry, crypto_engine=self.crypto_engine, name=name)
        return self.manifest
    
async def condition_interpreter(content, *args, **kwargs):
    return content
    
async def core_interpreter(key: str, content: List, registry, crypto_engine, name, **kwargs):
    
    if not isinstance(content, list):
        content = [target_content] 
    executable_block = []
    service_prefix = None
    for n, step in enumerate(content):
        entry = {}
        service_prefix = None
        service_config_keys = {}
        path = None

        # 1. First Pass: Resolve Service and Config
        for k, v in step.items():
            if registry.id_map.get(k) == SchemaID.SERVICE:
                service_prefix = registry.service_prefix(service_key=k, service_value=v)
                info = resolve_service_instruction(v)
                path = info.get("full_path")
                service_config_keys = service_func_config_keys(registry, step, k, service_prefix)
                entry["execution"] = {**service_config_keys}
                entry["execution_type"] = k

        for key, value in step.items():

            specialist = registry.interpreter_map.get(key)
            if not specialist:
                if key in registry._raw:
                    entry[key] = value
                continue

            # 2. Execute the specialist
            result = await specialist(
                content=value,
                key=key,
                registry=registry,
                crypto_engine=crypto_engine,
                name=name,
                service_prefix=service_prefix,
                service_path=path,
                service_config_keys=service_config_keys,
                step=step
            )

            if registry.id_map.get(key) == SchemaID.INPUT:
                entry["execution"].update(result)
            else:
                entry[key] = result


        executable_block.append(entry)

    return executable_block

async def assign_key_value(content, **kwargs):
    return content

def service_func_config_keys(registry, step, service_key, prefix):
    handler = registry.prefix_executor(service_key, prefix)
    print(f"handler:   {handler}")
    print(f"service_key       {service_key}")
    if not handler:
        return {}
    handler_keys = registry.hydrate_from_handler(handler)
    config_keys = {ky: vl for ky, vl in step.items() if ky in handler_keys}
    return config_keys 

async def app_service(registry, content, key: str, crypto_engine, name, service_config_keys, step, service_path, service_prefix, **kwargs):

    list_of_value = content.split(".")

    if len(list_of_value) > 1:
        app_name = list_of_value[0] if list_of_value[0] != service_prefix else list_of_value[1]
        action = list_of_value[-1]
    else:
        app_name = list_of_value[0]
        action = ""
    
    sub_interpreter = registry.prefix_interpreter(key, service_prefix)
    
    system_schema = {}
    if sub_interpreter:
        system_schema[service_prefix] = await sub_interpreter(
            key=service_prefix,
            path=service_path,
            value=content,
            service=app_name,
            client_name=name,
            crypto_engine=crypto_engine,
            current_step=step,
            registry=registry,
            prefix=service_prefix, 
            config_keys=service_config_keys
            
        )
    # Return only the description of the service
    return {
        "app": app_name,
        "action": action,
        "type": service_prefix,
        "engine_internal": system_schema
    }

async def build_input_v2(service_path, crypto_engine, name, content, **kwargs):
    
    key_matches = check_key_matches(service_path=service_path)
    app_schema = key_matches["app_schema"]
    found_items = key_matches["found_items"]["matched_items"]
    required_key_path = key_matches["found_items"]["key_value"]
    missing = missing_field(required=found_items, content_to_check=content)
    
    default_regex = r"Default\s*=\s*([\$!\.\w\d_\-\s]+)"

    if missing:   
        for m in missing:
            missing_value = str(found_items.get(m))
            match = re.search(default_regex, missing_value)
            
            if match and m not in content:
                raw_val = match.group(1).strip()
                
                # Logic: Check for escape and strip the slash
                is_escaped = raw_val.startswith("/")
                re_val = raw_val[1:] if is_escaped else raw_val
                
                # EXTRACT ONLY THE VALUE (Cleaned of the slash if it was there)
                extracted_val = f"{{{{{re_val}}}}}"
                
                # Replace surgically using the V2 logic
                app_schema = replace_place_value_v3(
                    key_path=required_key_path, 
                    content_to_modify=app_schema, 
                    key=m,
                    value=extracted_val,
                    is_metadata_replacement=True # CRITICAL
                )
                
                # Auth Logic: Skip if it was escaped
                if is_escaped:
                    continue
                
                # Standard Auth Logic
                if re_val.startswith("$env."):
                    target_service = re_val.replace("$env.", "")
                    app_path = get_auth_config_file(client_name=name, file_type="app_service", service=target_service)
                    w_f = retrieve_file(file_path=app_path, base_dir=True)
                    if w_f:
                        w_f.update({"client_name": name, "app_name": target_service})
                        await start_auth_flow(_cont=w_f, _crypto_engine=crypto_engine)
                continue

    # Handle explicit overrides
    for ke in found_items.keys():
        if ke in content:
            val = content.get(ke)
            app_schema = replace_place_value_v3(
                key_path=required_key_path, content_to_modify=app_schema, key=ke, value=val, is_metadata_replacement=False
            )        
    return {
        "_args": app_schema
    }

async def script_interpreter(current_step, value, **_kwargs):
    """
    VALIDATOR: Resolves paths and ensures the script exists.
    Returns a manifest entry, but DOES NOT execute.
    """
    content_to_modify = {}
    # 1. Resolve Extension
    RUNTIME_EXT_MAP = {
        "python": "py",
        "nodejs": "js",
        "node": "js",
        "javascript": "js"
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

async def webhook_func(current_step, config_keys, prefix, service, registry, value, key, client_name, crypto_engine, **_kwargs):
    # 1. Dynamically find the key used for inputs
    input_key = None
    for k in current_step.keys():
        if registry.id_map.get(k) == SchemaID.ID:
            input_key = k
            break
    
    target_key = input_key or key

    # 2. Resolve the delete schema path
    internal_value = f"{prefix}.{service}._delete"
    info = resolve_service_instruction(internal_value)
    path = info.get("full_path")
    
    if path:
        # build_input_v2 returns a dict that usually contains {"_args": {...}}
        # We want to extract just that inner schema to avoid double-nesting
        raw_schema_result = await build_input_v2(
            path=path, 
            current_step=current_step, 
            crypto_engine=crypto_engine, 
            client_name=client_name, 
            value=internal_value, 
            key=target_key, 
            service=service, 
            content_to_modify={} 
        )
        final_keys = {**config_keys, **raw_schema_result}
        
        return {
            "args": final_keys,
            "app_name": service
        }
        
    return {}

async def timer_func():
    pass

async def version_interpreter(content, *args, **kwargs):
    # Ensure we return the value (like "1.0") so the manifest builder 
    # can pass it to the processor
    return str(content)

