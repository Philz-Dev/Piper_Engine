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

if TYPE_CHECKING:
    from shared.registry_V2 import PiperRegistry, ValidationState

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

def resolve_service_instruction(service_key: str, base_dir: str = "apps/"):
    # 1. Initialize variables FIRST
    mode = "internal_api"
    validate_input = True
    extension = ".json"
    raw_lookup = service_key

    # 2. Process logic overrides
    if service_key.startswith("script."):
        mode = "external_script"
        validate_input = False
        extension = ".py"
        raw_lookup = service_key.split("script.", 1)[1]
    elif service_key.startswith("ext."):
        base_dir = "."
        mode = "external_api"
        validate_input = True
        extension = ".json"
        raw_lookup = service_key.split("ext.", 1)[1]

    # 3. Path construction (Now raw_lookup is guaranteed to exist)
    literal_path = raw_lookup.replace(".", "/")
    full_path = os.path.normpath(os.path.join(base_dir, f"{literal_path}{extension}"))

    return {
        "mode": mode,
        "full_path": full_path,
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
        details[name] = {"default": param.default if not type(param.default) is type else None,
                         "annotation": param.annotation
                         }
    return details

# Anchors the pathing to the directory where THIS script is saved
# Example: /app/dev_utils/ on Docker or C:\Automation\src\dev_utils on Windows
# Anchors the pathing to the directory where THIS script is saved
BASE_DIR = Path(__file__).resolve().parent

def get_registry_package(dsl_file):
    from shared.registry_V2 import PiperRegistry, ValidationState
    version = dsl_file.get("version", "1.0")
    schema_dict = load_schema_registry(version)
    registry = PiperRegistry(schema_dict)
    state = ValidationState()
    return registry, state

def get_suggestion(misspelled_key: str, valid_keys: list) -> str:
    # n=1 gives us the single best match
    # cutoff=0.6 ensures we don't suggest things that are too different
    matches = difflib.get_close_matches(misspelled_key, valid_keys, n=1, cutoff=0.6)
    return matches[0] if matches else None

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
                registry.gather_all_keys(manager_key, service_id, state)

def input_manager(registry, step):
    input_manager_definitions = registry.get_keys_by_feature("an_input_manager") 
    # Return the actual list of found keys so len() works correctly
    return [k for k in step.keys() if k in input_manager_definitions]

def check_key_matches(service_path, pattern = r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}" ):     
    app_schema = retrieve_file(file_path=service_path, base_dir=True)
    if app_schema:
        found_items = crawler(content_to_crawl=app_schema, patterns=pattern)
    return {"found_items": found_items if found_items else {}, "app_schema": app_schema if app_schema else {}}

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

def crawler(content_to_crawl: dict, patterns: list | str, is_regex: bool = True):
    matched_field = {}
    unzip_app_schema = UnZip()
    unzip_app_schema.unpack_bulk_data(content_to_crawl)
    if isinstance(patterns, str):
        patterns = [patterns]
    for p in patterns:
        # If we want a literal search, escape special characters
        # e.g., "price?" becomes "price\?" so regex treats it as text
        search_pattern = p if is_regex else re.escape(p)
        for key, value in unzip_app_schema.unpacked_key_value.items():
            if re.fullmatch(search_pattern, str(value)):
                matched_field[key] = value
    package = {
        "matched_items": matched_field,
        "key_path": unzip_app_schema.key_path
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
        print(f"⚠️ [System] File not found: {file_path}")
        return None
    except Exception as e:
        print(f"❌ [System] Error reading {file_path}: {e}")
        return None
    
def replace_place_value(key_path, key, value, content_to_modify=None):
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
    t_map, w_map, a_map, k_map, d_map, tk_map, ser_map, ad_map, fl_map, co_map, id_map, rec_map, s_map, tr_map = {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}
    
    for key, cfg in definitions.items():
        # Security Check: Ensure no missing data
        if not all(k in cfg for k in (
            "type", "weight", "handler", "is_section", "dependency", "allowed_keys", 
            "task_manager", "a_service_manager", "address_book", "file_ext", "a_condition_manager",
            "an_id_manager", "a_recursive_manager", "a_trigger_manager"
        )):
            raise ValueError(f"CRITICAL: Definition for '{key}' is incomplete.")
            
        t_map[key] = cfg["type"]
        w_map[key] = cfg["weight"]
        a_map[key] = cfg["handler"]
        k_map[key] = cfg["allowed_keys"]
        d_map[key] = cfg["dependency"]
        tk_map[key] = cfg["task_manager"]
        if service := cfg["a_service_manager"]:
            ser_map[key] = service
        ad_map[key] = cfg["address_book"]
        fl_map[key] = cfg["file_ext"]
        if condition := cfg["a_condition_manager"]:
            co_map[key] = condition
        if id := cfg["an_id_manager"]:
            id_map[key] = id
        if recursion := cfg["a_recursive_manager"]:
            rec_map[key] = recursion
        if section := cfg["is_section"]:
            s_map[key] = section
        if trigger := cfg["a_trigger_manager"]:
            tr_map[key] = trigger
        
    return t_map, w_map, a_map, k_map, d_map, tk_map, ser_map, ad_map, fl_map, co_map, id_map, rec_map, s_map, tr_map

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
