import json
import yaml
import os
from pathlib import Path
import inspect
from shared.unpacked_data import UnZip
import re
import importlib
from typing import List, Dict, Any, Optional
import difflib
from typing import TYPE_CHECKING, Any
import secrets
from shared.reg_schema.schemaid import SchemaID
from ruamel.yaml import YAML

if TYPE_CHECKING:
    from shared.registry_V2 import PiperRegistry, ValidationState

def load_yaml_with_metadata(file_path):
    if not file_path.endswith((".yml", ".yaml")):
        file_path = f"{file_path}.yml"
    yaml = YAML(typ='rt')
    try:
        with open(file_path, 'r') as f:
            return yaml.load(f)
    except FileNotFoundError:
        return None

def missing_field(required: list|dict, content_to_check: list|dict):
    content = required.keys() if type(required) is dict else required
    cont_to_check = content_to_check.keys() if type(content_to_check) is dict else content_to_check
    return set(content) - set(cont_to_check)

def datatype_hook(content, key, value):
    """
    Hook for the UnZip class. 
    If content is a string with {{DataType=...}}, it stores the type.
    """
    if not isinstance(content, str):
        return None

    # Pattern: {{DataType=str}} or {{DataType=int, Value=...}}
    pattern = r"\{\{DataType=(\w+)"
    match = re.search(pattern, content)
    
    if match:
        type_str = match.group(1)
        type_map = {
            "str": str, 
            "int": int, 
            "list": list, 
            "dict": dict,
            "bool": bool
        }
        # We return the actual Python type
        return type_map.get(type_str.lower(), str)
    
    return None

def extract_types_from_handler(handler_func) -> Dict[str, Any]:
    """Uses reflection to see what a handler function expects."""
    if not handler_func:
        return {}
        
    signature = inspect.signature(handler_func)
    # We exclude common engine args like 'payload' or 'state'
    internal_args = ['state', 'registry', 'context_ref']
    
    return {
        name: param.annotation if param.annotation != inspect.Parameter.empty else Any
        for name, param in signature.parameters.items()
        if name not in internal_args
    }

def find_dependency_func(sub_type: str, registry, step: Dict, dependencies, prefix):
    type = {
        "interpreter": registry.sub_interpreter_map, 
        "executor": registry.get_sub_executor_map,
        "validator": registry.get_sub_validator_map
        }
    sub_func_list = {}
    if type.get(sub_type):
        return
    for k, value in step.items():
        for r, v in registry.manager_map.items():
            if k in v and r in dependencies:
                
                sub_func = type["sub_type"](prefix)
                if sub_func:
                    sub_func_list[k] = sub_func
    return sub_func_list

def resolve_service_instruction(service_key: str, base_dir: str = "apps/", runtime: str = None):
    # 1. Initialize variables FIRST
    script_extension = {"python": ".py", "javascript": ".js"}
    if service_key is None:
        return {"mode": "error", "full_path": None, "validate_input": False}
    # --------------------------------
    mode = "internal_api"
    validate_input = True
    extension = ".json"
    raw_lookup = service_key

    # 2. Process logic overrides
    if service_key.startswith("script."):
        base_dir = ""
        mode = "external_script"
        validate_input = False
        extension = script_extension.get(runtime)
        raw_lookup = service_key.split("script.", 1)[1]
    elif service_key.startswith("ext."):
        base_dir = ""
        mode = "external_api"
        validate_input = True
        extension = ".json"
        raw_lookup = service_key.split("ext.", 1)[1]

    elif service_key.startswith("webhook."):
        mode = "webhook"
        validate_input = True
        extension = ".json"
        raw_lookup = service_key.split("webhook.")[1]
    elif service_key.startswith("iter."):
        base_dir = ""
        mode = "iteration"
        validate_input = False
        extension = script_extension.get(runtime)
        raw_lookup = service_key.split("script.", 1)[1]
    elif service_key.startswith("aggr."):
        base_dir = ""
        mode = "aggregator"
        validate_input = False
        extension = script_extension.get(runtime)
        raw_lookup = service_key.split("script.", 1)[1]
    if service_key.startswith("load."):
        base_dir = ""
        mode = "download"
        validate_input = False
        extension = script_extension.get(runtime)
        raw_lookup = service_key.split("script.", 1)[1]
    elif service_key.startswith("timer"):
        return {}

    # 3. Path construction (Now raw_lookup is guaranteed to exist)
    literal_path = raw_lookup.replace(".", "/")
    full_path = os.path.normpath(os.path.join(base_dir, f"{literal_path}{extension}"))
    if not os.path.isabs(full_path):
        # Anchor to the directory of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, full_path)
    
    file_path = os.path.normpath(file_path)
    

    return {
        "mode": mode,
        "full_path": file_path,
        "validate_input": validate_input,
        "literal_path": raw_lookup
    }

def add_to_config(cont, service, client_name):
    auth_file_path = get_auth_config_file(client_name=client_name, file_type="auth")
    auth_file = retrieve_file(file_path=auth_file_path)
    if not auth_file.get("app_service"):
        auth_file["app_services"]  = []
    auth_file["app_services"].append(service) if service else None
    unzip = UnZip()
    unzip.unpack_bulk_data(cont)
    unzip.unpacked_key_value
    for key, v in unzip.unpacked_key_value.items():
        if type(v) is int or not v.startswith("{{$.") or not v.endswith("}}") or auth_file.get(service):
            continue
        auth_file[service] = v
        open_json_file(file_path=auth_file_path, cont=auth_file)

def get_line_number(container, key=None):
    """
    Retrieves the precise line number for a specific key.
    Falls back to the container's start line if the key isn't found.
    """
    # 1. Try to find the EXACT line for the specific key
    is_list_index = str(key).startswith("index ")
    lookup_key = key if not is_list_index else None
    if lookup_key is not None and hasattr(container, 'lc'):
        try:
            # ruamel.yaml stores key-specific line info here
            return container.lc.item(lookup_key)[0] + 1
        except (KeyError, IndexError, AttributeError):
            pass

    # 2. Fallback: If it's a list or we can't find the key, get the container's line
    if hasattr(container, 'lc'):
        return container.lc.line
            
    return "??"


def open_json_file(file_path, cont):
    with open(file_path, "w") as f:
        json.dump(cont, f, indent=4)

def inspect_function(func):
    details = {}
    sig = inspect.signature(func)
    for name, param in sig.parameters.items():
        if name.startswith("_"):
            continue
        # 🛠️ Was converting param.default to None whenever it was a class
        # object (via 'type(param.default) is type') - which is true for
        # EVERY genuinely-mandatory parameter, since inspect.Parameter.empty
        # (the sentinel Python uses for "no default") is itself a class, so
        # type(inspect.Parameter.empty) is type. Every downstream caller in
        # validators_V2.py checks 'info.get("default") is inspect.Parameter.empty'
        # to detect a mandatory arg - but that sentinel could never survive
        # this conversion to reach them, so every "Missing mandatory
        # argument" check in the file was silently dead. Preserving the
        # real param.default (including the empty sentinel) here is what
        # those checks actually need.
        details[name] = {"default": param.default,
                         "annotation": param.annotation
                         }
    return details

# Anchors the pathing to the directory where THIS script is saved
# Example: /app/dev_utils/ on Docker or C:\Automation\src\dev_utils on Windows
# Anchors the pathing to the directory where THIS script is saved
BASE_DIR = Path(__file__).resolve().parent

def get_registry_package(dsl_file: Dict) -> tuple:
    from registry_V2 import ValidationState
    version = dsl_file.get("version", "1.0")
    registry = get_registry_by_version(version=version)
    state = ValidationState()
    return registry, state

def generate_random_token(length=32):
    """Generates a secure hex token for webhook URLs."""
    return secrets.token_hex(length // 2)

def get_registry_by_version(version: str):
    from shared.registry_V2 import PiperRegistry
    schema_dict = load_schema_registry(version)
    registry = PiperRegistry(schema_dict)
    return registry

def get_suggestion(misspelled_key: str, valid_keys: list) -> str:
    # n=1 gives us the single best match
    # cutoff=0.6 ensures we don't suggest things that are too different
    matches = difflib.get_close_matches(misspelled_key, valid_keys, n=1, cutoff=0.6)
    return matches[0] if matches else None

def get_all_dsl_keys_v2(dsl_file, registry, state: "ValidationState"):
    """
    Enhanced Hydrator: Recursively finds all services to ensure 
    nested schemas (like Telegram inside HubSpot) are loaded.
    """
    for section, content in dsl_file.items():
        # Normalize everything to a list
        steps = content if isinstance(content, list) else [content]
        
        # Helper to dive into nested dictionaries/lists
        def find_services_recursive(data):
            if isinstance(data, list):
                for item in data:
                    find_services_recursive(item)
            elif isinstance(data, dict):
                # 1. Check if this dictionary is a service step
                service_triggers = [k for k in data.keys() if registry.id_map.get(k) == SchemaID.SERVICE]
                if service_triggers:
                    manager_key = service_triggers[0]
                    service_id = data[manager_key]
                    # Hydrate the registry for this specific service
                    registry.gather_all_keys(service_key=manager_key, service_value=service_id, state=state)
                
                # 2. Check for Action Steps (NEW LOGIC)
                action_triggers = [k for k in data.keys() if registry.id_map.get(k) == SchemaID.ACTION]
                for action_key in action_triggers:
                    action_name = data[action_key]
                    handler = registry.get_action_handler(action_name)

                    if handler:
                        # Inspect the handler to get arg names/types
                        handler_args = registry.hydrate_from_handler(handler)
                        
                        # Merge these new argument types into the global map
                        registry.type_map.update(handler_args)
                        
                        
                        # Ensure runtime keys are updated so the validator recognizes them
                        runtime_keys = {k.split(".")[-1] for k in handler_args.keys()}
                        registry.list_of_runtime_keys.update(runtime_keys)
                        registry.list_of_keys = list(set(registry.list_of_keys) | registry.list_of_runtime_keys)
                    else:
                        state.add_error(f"Action '{action_name}' not found in registry handlers.")

                # 2. Recursively look for 'steps' or 'on_error' to find nested services
                for value in data.values():
                    if isinstance(value, (dict, list)):
                        find_services_recursive(value)

        find_services_recursive(steps)

def get_all_dsl_keys(dsl_file, registry, state: "ValidationState"):
    for section, content in dsl_file.items():
        # Normalize everything to a list so we can use one loop
        steps = content if isinstance(content, list) else [content]
        
        for step in steps:
            if not isinstance(step, dict):
                continue
                
            # Find which key triggers a service (e.g., "service", "action")
            service_triggers = [k for k in step.keys() if k in registry.service_map]
            
            if service_triggers:
                manager_key = service_triggers[0]
                service_id = step[manager_key] # e.g., "Hubspot.search"
                
                # This fills registry.type_map with "input.email", "input.id", etc.
                registry.gather_all_keys(service_key=manager_key, service_value=service_id, state=state)

def _cast_value(val: str) -> Any:
        """Helper to cast string inputs to appropriate Python types."""
        val = val.strip()
        
        # Handle None
        if val.lower() == "none":
            return None
            
        # Handle Booleans
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
            
        # Handle Integers
        try:
            return int(val)
        except ValueError:
            pass
            
        # Handle Floats
        try:
            return float(val)
        except ValueError:
            pass
            
        # Return as string if no other type matches
        return val

def unescape_dsl_content(text: str) -> str:
    """
    Converts literal backslashes to their actual characters.
    e.g., '\$' -> '$', '\)' -> ')', '\{' -> '{', '\|' -> '|'
    """
    return re.sub(r'\\([\{\}\(\)\$\|])', r'\1', text)

def split_args_smart(args_str):
    """Splits arguments by comma, but ignores commas inside nested parens."""
    args = []
    current_arg = []
    parens_depth = 0
    in_quotes = False
    
    for char in args_str:
        if char == '"': in_quotes = not in_quotes
        if not in_quotes:
            if char == '(': parens_depth += 1
            elif char == ')': parens_depth -= 1
            elif char == ',' and parens_depth == 0:
                args.append("".join(current_arg).strip())
                current_arg = []
                continue
        current_arg.append(char)
    
    args.append("".join(current_arg).strip())
    return args

def parse_pipe_args(arg_list):
    """Parses and casts pipe arguments into positional args and kwargs."""
    args = []
    kwargs = {}
    for arg in arg_list:
        if "=" in arg:
            key, val = arg.split("=", 1)
            kwargs[key] = _cast_value(val)
        else:
            args.append(_cast_value(arg))
    return args, kwargs

def input_manager(registry, step):
    input_manager_definitions = registry.get_keys_by_feature("an_input_manager") 
    # Return the actual list of found keys so len() works correctly
    return [k for k in step.keys() if k in input_manager_definitions]

def check_key_matches(service_path, pattern = r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}" ):     
    app_schema = retrieve_file(file_path=service_path, base_dir=True)
    found_items = {}
    if app_schema:
        found_items = crawler(content_to_crawl=app_schema, patterns=pattern)
    return {
        "found_items": found_items if found_items else {}, 
        "app_schema": app_schema if app_schema else {}
        }

def get_auth_config_file(client_name=None, file_type: str = "auth", service: str = None):
    """
    Unified path manager for Client configs, App Service configs, and System configs.
    Supports Docker (Flat/Root) and Windows (Nested Templates) structures.
    """
    is_docker = os.environ.get('CLIENT_NAME') is not None
    
    # 1. Handle App Service Specific Configs (e.g., Hubspot, Telegram)
    if file_type == "app_service" and service:
        # Returns relative path for retrieve_file(base_dir=True) to handle
        return os.path.join("apps", service, "_auth_config.json")

    # 2. Handle System Configs (e.g., universal_webhook)
    if file_type == "config_service" and service:
        # service here would be "universal_webhook"
        return os.path.join(".piper_config", f".{service}")

    # 3. Handle Client-Specific Configs
    """base_path = os.path.join("templates", client_name) if client_name else ""
    if is_docker:
        # DOCKER PATHS: Files are mounted directly in /app/
        services = {
            "auth": "auth_config.json",
            "env": ".env",
            "piper_vault": ".piper_vault",
            "config": ".config",
            "custom_app": "custom_app.json",
            "waterfall": "waterfall.yml"
        }
    else:"""
        # WINDOWS PATHS: Files are in templates/{client_name}/

    base_path = os.path.join("templates", client_name) if client_name else ""
    services = {
        "auth": os.path.join(base_path, "auth_config.json"),
        "env": os.path.join(base_path, ".env"),
        "piper_vault": os.path.join(base_path, ".piper_vault"),
        "config": os.path.join(base_path, ".config"),
        "custom_app": os.path.join(base_path, "custom_app.json"),
        "waterfall": os.path.join(base_path, "waterfall.yml")
    }
    return services.get(file_type)

def open_json_file(file_path, cont):
        with open(file_path, "w") as f:
            json.dump(cont, f, indent=4)

def validate_type(key, expected_type: "Any", content=None):
        if not isinstance(content, expected_type):
            raise TypeError(
                f"DATA TYPE MISMATCH: {key} expects {expected_type.__name__}, "
                f"but got {type(content).__name__}."
            )
        
def missing_field_v2(required_paths: dict, content_to_check: dict):
    """
    Compares the full path strings from the schema 
    against what is actually present in the user input.
    """
    # required_paths is 'key_path' from UnZip (e.g., {'body.url': '{{...}}'})
    # content_to_check is the user DSL input
    
    # We need to 'unzip' the user input to see which full paths THEY provided
    user_unzip = UnZip()
    user_unzip.unpack_bulk_data(content_to_check)
    user_paths = user_unzip.key_path.keys()

    # The difference is now a set of FULL PATHS that are missing
    missing = set(required_paths.keys()) - set(user_paths)
    key_path = user_unzip.key_path
    return {"missing": missing,
            "content_to_check_key_path": key_path
            }

def crawler_old(content_to_crawl: dict, patterns: list | str, is_regex: bool = True):
    matched_field = {}
    matched_key_value = {}
    unzip_app_schema = UnZip()
    unzip_app_schema.unpack_bulk_data(content_to_crawl)
    if isinstance(patterns, str):
        patterns = [patterns]
    for p in patterns:
        # If we want a literal search, escape special characters
        # e.g., "price?" becomes "price\?" so regex treats it as text
        search_pattern = p if is_regex else re.escape(p)
        for key, value in unzip_app_schema.unpacked_key_value.items():
            if value is None: 
                continue
            if re.fullmatch(search_pattern, str(value)):
                matched_key_value[key] = value

        for path, value in unzip_app_schema.key_path.items():
            if value is None: 
                continue
                
            # Check if the value at this path matches our {{Mustache}} pattern
            if re.fullmatch(search_pattern, str(value)):
                # We save the path as the key to prevent "url" vs "url" collisions
                matched_field[path] = value
    package = {
        "matched_items": matched_key_value,
        "key_path": unzip_app_schema.key_path,
        "key_value": matched_field
    }
    
    return package if matched_field else None

def crawler(content_to_crawl: dict, patterns: list | str, is_regex: bool = True):
    matched_field = {}
    matched_key_value = {}
    unzip_app_schema = UnZip()
    unzip_app_schema.unpack_bulk_data(content_to_crawl)
    
    if isinstance(patterns, str):
        patterns = [patterns]
        
    for p in patterns:
        search_pattern = p if is_regex else re.escape(p)
        
        # 1. Update: Use re.search instead of re.fullmatch
        # This allows matching inside a larger string (e.g., "Bearer {{ !.token }}")
        
        for key, value in unzip_app_schema.unpacked_key_value.items():
            if value is None: continue
            if re.search(search_pattern, str(value)): # <--- CHANGED
                matched_key_value[key] = value

        for path, value in unzip_app_schema.key_path.items():
            if value is None: continue
            
            # 2. Update: Use re.search here as well
            if re.search(search_pattern, str(value)): # <--- CHANGED
                matched_field[path] = value
                
    package = {
        "matched_items": matched_key_value,
        "key_path": unzip_app_schema.key_path,
        "key_value": matched_field
    }
    
    return package if matched_field else None

def retrieve_file(file_path, file_type: str=None, base_dir=False):
    # ✅ GUARD 1: If path is None, don't try to split it
    if not file_path:
        return None

    # ✅ GUARD 2: Safe extension extraction
    try:
        # If it's a Path object, convert to string; then split
        path_str = str(file_path)
        detected_type = path_str.split(".")[-1].lower()
    except (AttributeError, IndexError):
        return None

    # Add all your supported types here
    services = {
        "yml": yaml.safe_load, 
        "yaml": yaml.safe_load, 
        "json": json.load, 
        "piper_vault": json.load, 
        "ngrok_token": json.load,
        "auth": json.load,
        "context_manager": json.load,
        "universal_webhook": json.load
    }

    if base_dir and not os.path.isabs(path_str):
        # Anchor to the directory of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, file_path)
    
    file_path = os.path.normpath(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            # Use detected type if services supports it, else read raw
            if detected_type in services:
                return services[detected_type](f)
            return f.read()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"❌ [System] Error reading {file_path}: {e}")
        return None
    
def replace_place_value_v2(key_path, key, value, content_to_modify=None, is_metadata_replacement=False):
    for k, v in key_path.items():
        split_key = k.split(".")
        
        if split_key[-1] == key:
            temp = content_to_modify
            for ky in split_key[:-1]:
                if ky.isdigit(): ky = int(ky)
                temp = temp[ky]
            
            final_key = split_key[-1]
            current_val = temp[final_key]

            if is_metadata_replacement and isinstance(current_val, str) and "{{" in current_val:
                # 1. Strip braces from incoming value
                clean_val = str(value).replace("{{", "").replace("}}", "").strip()
                
                # 2. IMPROVED REGEX: 
                # re.DOTALL ensures it matches even if there are newlines in the metadata
                # the '?' makes it non-greedy so it doesn't eat the whole string
                pattern = r"\{\{.*?\}\}"
                replacement = f"{{{{{clean_val}}}}}"
                
                new_string = re.sub(pattern, replacement, current_val, flags=re.DOTALL)
                
                # DEBUG PRINT - Check your terminal for this!
                # print(f"DEBUG: Swapping '{current_val}' with '{new_string}'")
                
                temp[final_key] = new_string
            else:
                temp[final_key] = value
                
    return content_to_modify

def replace_place_value_v3(key_path, value, key, content_to_modify=None, is_metadata_replacement=False):
    for k, v in key_path.items():
        split_key = k.split(".")

        if split_key[-1] == key:
            temp = content_to_modify
            for ky in split_key[:-1]:
                if ky.isdigit(): ky = int(ky)
                temp = temp[ky]
            
            final_key = split_key[-1]
            current_val = temp[final_key]

            # ONLY apply the bracing logic if it's a metadata replacement (e.g., from a 'Default' string)
            # AND the incoming value itself contains braces (indicating it's a dynamic reference).
            if is_metadata_replacement and isinstance(current_val, str) and "{{" in current_val:
                # If the incoming value is already braced (like {{$.Hubspot}}), 
                # we preserve the structure of the schema's placeholder.
                if isinstance(value, str) and "{{" in value:
                    clean_val = str(value).replace("{{", "").replace("}}", "").strip()
                    pattern = r"\{\{.*?\}\}"
                    replacement = f"{{{{{clean_val}}}}}"
                    temp[final_key] = re.sub(pattern, replacement, current_val, flags=re.DOTALL)
                else:
                    # If it's a raw value being injected into a metadata placeholder, 
                    # replace the WHOLE thing with the raw value.
                    temp[final_key] = value
            else:
                # Standard DSL override: Replace the whole placeholder with the DSL value
                # This fixes "FFeRlEmp" becoming "{{FFeRlEmp}}"
                temp[final_key] = value
                
    return content_to_modify

def replace_place_value(key_path, key, value, content_to_modify=None):
    for k, v in key_path.items():
        split_key = k.split(".")
        
        if split_key[-1] == key:
            temp = content_to_modify
            for ky in split_key[:-1]:
                if ky.isdigit():
                    ky = int(ky)
                
                # Check if we can actually traverse this level
                if temp is None or (not isinstance(temp, (dict, list))):
                    return content_to_modify 
                    
                temp = temp[ky]
            
            # Final check before assignment
            if temp is not None and isinstance(temp, (dict, list)):
                temp[split_key[-1]] = value
                
    return content_to_modify
    
def replace_place_value_v10(key_path, key, value, content_to_modify=None):
    for k, v in key_path.items():
        split_key = k.split(".")
        
        if split_key[-1] == key:
            temp = content_to_modify
            for ky in split_key[:-1]:
                if ky.isdigit():
                    ky = int(ky)
                temp = temp[ky]
            
            # Update the final key
            temp[split_key[-1]] = value
    return content_to_modify

def build_subregistries(definitions):
    """The Factory: Turns the master definition into optimized lookup maps."""
    t_map, w_map, a_map, k_map, d_map, tk_map, ser_map, ad_map, fl_map, pr_map, tp_map = {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}
    
    for key, cfg in definitions.items():
        # Security Check: Ensure no missing data
        if not all(k in cfg for k in (
            "type", "weight", "handler", "is_section", "dependency", "allowed_keys", 
            "task_manager", "address_book", "file_ext", "prefix", "top_level_parent"
        )):
            raise ValueError(f"CRITICAL: Definition for '{key}' is incomplete.")
            
        t_map[key] = cfg["type"]
        w_map[key] = cfg["weight"]
        a_map[key] = cfg["handler"]
        k_map[key] = cfg["allowed_keys"]
        d_map[key] = cfg["dependency"]
        tk_map[key] = cfg["task_manager"]
       
        ad_map[key] = cfg["address_book"]
        fl_map[key] = cfg["file_ext"]
        pr_map[key] = cfg["prefix"]
        tp_map[key] = cfg["top_level_parent"]
        
    return t_map, w_map, a_map, k_map, d_map, tk_map, ser_map, ad_map, fl_map, pr_map, tp_map

def load_schema_registry(version: str):
    # Transforms "1.0" -> "v1_0"
    safe_version = f"v{version.replace('.', '_')}"
    module_name = f"shared.reg_schema.{safe_version}"
    
    try:
        module = importlib.import_module(module_name)
        return getattr(module, "schema_reg")
    except (ModuleNotFoundError, AttributeError):
        # Professional Fallback
        print(f"(!) Version {version} not found. Rolling back to v1_0")
        module = importlib.import_module("shared.reg_schema.v1_0")
        return getattr(module, "schema_reg")