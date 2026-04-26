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
from shared.tools import inspect_function, crawler, replace_place_value, retrieve_file, open_json_file, check_key_matches, input_manager
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
            if section == "version": continue
            
            # If it's a workflow section (like 'pipeline' or 'on_start')
            if isinstance(content, list):
                self.manifest[section] = await self.registry.interpreter_map.get(section)(content, self.registry, self.crypto_engine, name)
        self.manifest["crypto_engine"] = self.crypto_engine
        self.manifest["client_name"] = name
        return self.manifest
    
async def run_pipeline(content: List, registry, crypto_engine, name):
    executable_block = []

    async def _interpret_block(content: List, registry, crypto_engine, name) -> List[Dict]:
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
                print(specialist)

                # 2. Execute the specialist
                result = await specialist(
                    step=step,
                    key=key,
                    value=value,
                    registry=registry,
                    crypto_engine=crypto_engine,
                    name=name,
                    func=_interpret_block # Pass for recursion
                )

                # 3. Determine Storage Logic (Merge vs Assign)
                # Senior Move: Let the Registry define if a role should 'merge'
                if registry.should_merge(key):
                    entry.update(result)
                else:
                    entry[key] = result
                print(entry)
            executable_block.append(entry)

        return executable_block
    return await _interpret_block(content=content, registry=registry, crypto_engine=crypto_engine, name=name)
    
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
    handler = registry.get_sub_handler(service_key, prefix)
    if not handler:
        return {}
    handler_keys = registry.hydrate_from_handler(handler)
    config_keys = {ky: vl for ky, vl in step.items() if ky in handler_keys}
    print(f"config_keys:      {config_keys}")
    return config_keys 
    
async def app_service(registry, step, key: str, value: str, crypto_engine, name, func):
    prefix = registry.service_prefix(service_key=key, service_value=value)
    list_of_value = value.split(".")
    app_name = list_of_value[0] if list_of_value[0] != prefix else list_of_value[1]
    action = list_of_value[-1]
    if (p := registry.address_book_map.get(key)):
        if (e := registry.file_ext_map.get(key)):
            path = p + "/" + app_name + "/" + action + "." + e

    config_keys = service_func_config_keys(registry=registry, step=step, service_key=key, prefix=prefix)

    service_config = registry._raw.get(key)
    dependencies = service_config.get("dependency", {}).get(prefix, {})

    for k, value in step.items():
        for r, v in registry.manager_map.items():
            if k in v and r in dependencies:
                sub_interpreter = registry.get_sub_interpreter(key, key)
                if sub_interpreter:
                    app_schema = {
                    "_args": sub_interpreter(
                        key=k, 
                        current_step=step, 
                        registry=registry,
                        service_path=path, # Pass path so it can find the app schema
                        service_value=value,
                        #content_to_modify=app_schema
                        )
                }
    final_args = config_keys      #{**config_keys, **app_schema}
        
    return {
        "service_manager": key,
        "app_name": app_name,
        "action": action,
        "args": final_args
    }
    
async def build_input(service_path, service_value, registry, current_step, key):
    print("fpath:     {service_path}")
    """key_matches = check_key_matches(service_path=path)
    app_schema = key_matches["app_schema"]
    found_items = key_matches["found_items"]
    missing = missing_field(required=found_items, content_to_check=value)
    if missing:
        for m in missing:
            missisng_value = found_items.get(m)
            if not type(missisng_value) is int and missisng_value.startswith("{{$.") and missisng_value.endswith("}}"):
                app_path = get_auth_config_file(client_name=client_name, file_type="app_service", service=service)
                w_f = retrieve_file(file_path=app_path, base_dir=True)
                if w_f:
                    w_f["client_name"] = client_name
                    w_f["app_name"] = service
                    await start_auth_flow(_cont=w_f, _crypto_engine=crypto_engine)
                    continue

        content_to_modify = replace_place_value(
            key_path=unzip_key_app, content_to_modify=content_to_modify, key=key, value=value
            )        
    return content_to_modify"""

"""async def trigger(content: List, registry, crypto_engine, name):
    services = {"webhook": webhook_func, "timer": timer_func}
    raw_cont = cont[key]
    service, action = raw_cont.split(".")
    if (p := regs["ad_map"][key]):
        if (e := regs["fl_map"][key]):
            path = p + "/" + service + "/" + action + "." + e
    if service_func := services.get(action):
        response = await service_func(cont=cont, regs=regs, key=key, path=path, service=service, action=action)
        response["app_name"] = service
    return response"""

async def webhook_func(regs, service, action, cont, path, key=None):
    pass

async def timer_func():
    pass

"""async def _interpret_block(content: List=content, registry=registry, crypto_engine=crypto_engine, name=name) -> List[Dict]:
    
    Processes a list of DSL steps into executable manifest entries.
    for n, step in enumerate(content):
        entry = {}
        id_key = [k for k in step.keys() if k in registry.id_map.get(k)]
        if id_key:
            for key in id_key:    
                specialist = registry.interpreter_map.get(key)
                if specialist:
                    entry[id_key] = specialist(
                            step=step, 
                            key=service_key, 
                            registry=registry,
                            crypto_engine=crypto_engine,
                            name=name, func=_interpret_block
                        )
                    

        condition_key = [k for k in step.keys() if k in registry.condtion_map.get(k)]
        if condition_key:
            for key in condition_key:  
                specialist = registry.interpreter_map.get(key)
                if specialist:
                    entry[condition_key] = specialist(
                            step=step, 
                            key=service_key, 
                            registry=registry,
                            crypto_engine=crypto_engine,
                            name=name, func=_interpret_block
                        )
                    

        service_key = [k for k in step.keys() if k in registry.service_map.get(k)]
        if service_key:
            for key in service_key:  
                specialist = registry.interpreter_map.get(key)
                service_data = await specialist(
                    step=step, 
                    key=service_key, 
                    registry=registry,
                    crypto_engine=crypto_engine,
                    name=name, func=_interpret_block
                )
        entry.update(service_data) # This merges without losing 'id' or 'condition'
        recursive_key = next((k for k in step.keys() if registry.is_recursive(k)), None)
        if recursive_key:
            entry[recursive_key] = await _interpret_block(step[recursive_key], registry, crypto_engine)

        executable_block.append(entry)
    return executable_block"""
