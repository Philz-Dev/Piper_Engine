import asyncio
import yaml
import json
import httpx # Async HTTP client
import aiofiles # Async file reading
from shared.unpacked_data import UnZip
from shared.interpreter import missing_field, validate_type, all_config_keys
import asyncio
import re
import os
import ast
from typing import Dict, Any, List
from shared.tools import retrieve_file, inspect_function, validate_type



def validate_pipeline(regs):
    context = {
        "seen_ids": [],
        "errors": []
    }
    def check_dependency(dependency: dict, regs_schema, content, step):
        for key, value in dependency.items():
            dep = [i for i in content.keys() if i in regs_schema[key]]
            if value["mandatory"] and not dep:
                raise KeyError(f"missed {key} in step {step}")
            if len(dep) > value["support"]:
                raise ValueError(f"more than one {key} for this step {steps}")
            
        
    for n in range(0, len(content := (regs["content"]))):
        c = content[n]
        if not type(c) is dict:
            raise TypeError("wrong command")
        
        # ---CHECK DEPENDENCY---
        check_dependency(dependency=regs["d_map"][regs["key"]], regs_schema=regs, content=c, steps=n)
        
        service = [s for s in content.keys() if s in regs["key"]]
        config_key = inspect_function(func=regs["handler"][service])

        # ---VALIDATION BLOCK---
        for k, v in c.items():
            if not k in regs["allow_key"][regs["key"]] or k not in config_key.keys():
                raise SyntaxError(f"this key {k} is not required in this block")
            expected_type = type(v)
            validate_type(key=k, expected_type=expected_type, content=v)
            regs["validator"](regs=regs)
                
        # ---ADD STEPS IF IT EXIST---
        steps = [st for st in c.keys() if st in regs["rec_map"]]
        regs["content"] = c[steps[0]]
        validate_pipeline(regs=regs)
        

def validate_id(val, context, block_id):
    """Checks for duplicates and stores the ID."""
    if val in context['seen_ids']:
        raise ValueError(f"[{block_id}] Duplicate ID found: '{val}'. IDs must be unique.")
    context['seen_ids'].append(val)


def validate_condition_syntax(condition_str: str, seen_ids: list):
    """
    Checks if the condition is logically sound before execution.
    """
    # 1. Extract all tags like {{id.key}}
    tags = re.findall(r"\{\{(?P<id>[\w\-]+)\.(?P<path>[\w\.]+)\}\}", condition_str)
    
    # 2. Check if the IDs being referenced actually exist earlier in the pipeline
    for ref_id, path in tags:
        if ref_id not in seen_ids:
            raise ValueError(f"Condition Error: Reference to '{ref_id}' found, but '{ref_id}' is not defined in previous steps.")

    # 3. "MOCK" the condition for a syntax check
    # We replace {{tag}} with a dummy value (like '1') to see if the Python syntax is valid
    # e.g., "{{total}} == 0" becomes "1 == 0"
    mock_condition = re.sub(r"\{\{.*?\}\}", "1", condition_str)
    
    try:
        # Check if it's safe and if it's valid Python
        tree = ast.parse(mock_condition, mode='eval')
        
        # Re-use your security check here!
        allowed_nodes = (ast.Expression, ast.Compare, ast.BinOp, ast.BoolOp, 
                         ast.UnaryOp, ast.Name, ast.Constant, ast.Load)
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                raise SyntaxError(f"Forbidden logic in condition: {type(node).__name__}")
                
    except SyntaxError as e:
        raise SyntaxError(f"Invalid condition syntax: '{condition_str}'. Check your operators (==, !=, >, <).")

    return True

def check_dependency(dep, package, key):
    if dep:
        missing = missing_field(required=dep, content_to_check=package)
        if missing:
            raise SyntaxError(f" {missing} was not inluded")
            












            """elif k in self.regs["service_reg"]:
                self.manifest[n][id_key] = self.id_name_list[-1]
                self.manifest[n]["args"] = {}
                self.manifest[n]["args"] = self.verify_config(regs=self.regs, content=c, key=k, manifest=manifest[n]["args"])
                self.manifest[n]["service_manager"] = k
                self.manifest[n] = await self.regs["tk_map"][k](regs=self.regs, manifest=self.manifest[n], cont=c, key=k)
            elif k in self.regs["con_map"]:
                self.manifest[n]["condition"] = v
            elif k in self.regs["rec_map"]:
                pass
                self.manifest[n]["steps"] = []
                self.regs["content"]= c[k]
                await self.run_pipeline()
            self.exe_manifest["Pipeline"] = self.manifest
            self.exe_manifest["crypto_engine"] = self.regs["crypto_engine"]
            return self.exe_manifest
        
def validate_trigger(self, key, cont):
    pass

class Validator:
    def __init__(self):
        self.progress: dict = {}
        self.unzip = UnZip()
        self.config_keys = all_config_keys(func_list=A_SERVICE_MANAGER_MAP, handler=ACTION_MAP)
    
    def run_validator(self, file: yaml, name: str):
        hooks = {dict: self.validate_types, list: self.validate_types, "primitive": self.validate_types}
        for key, value in file.items():
            if not key in SECTION_MAP:
                raise TypeError(f"CRITICAL: '{key}' is not recognized.")
            self.unzip.unpack_bulk_data(content=value, key=key, hooks=hooks)

    def validate_types(self, value, key, content=None):
        # Validates value against TYPE_MAP if a key is provided.
        if key:
            if not key in schema_reg and key not in self.config_keys and not key in key_list:
                raise SyntaxError(f"wrong key {key}, this key does not exist")
            expected_type = TYPE_MAP.get(key) or key_list.get(key) or self.config_keys.get(key)["annotation"]
            #if TYPE_MAP.get(key) else self.config_keys[key]["annotation"]
            validate_type(expected_type=expected_type, key=key, content=content)

class PiperValidator:
    def __init__(self, registry_maps: Dict[str, Any], unzip_engine: Any):
        
        registry_maps: The dictionary of maps returned by build_subregistries()
        unzip_engine: Your UnZip class instance
        
        self.maps = registry_maps
        self.unzip = unzip_engine
        
        # Identification of the "Service Key" (e.g., 'service') dynamically from registry
        self.service_key = next((k for k, v in self.maps['A_SERVICE_MANAGER_MAP'].items() if v is True), "service")
        
        # Regex for your custom schema tags
        self.tag_pattern = re.compile(
            r"\{\{DataType=(?P<type>\w+)(?:,\s*(?:Value|Alt)=(?P<default>[^}]+))?\}\}"
        )

    async def validate_dsl(self, dsl: Dict[str, Any]):
        The Master Entry Point: Validates the entire YAML/JSON DSL.
        print(f"--- Starting Pre-Flight Validation ---")

        # 1. Structural & Type Check (Top Level)
        for section, content in dsl.items():
            if section not in SECTION_MAP:
                raise TypeError(f"CRITICAL: '{section}' is not recognized.")
            
            # Check if section is the right type (e.g., pipeline must be a list)
            validate_type(key=section, expected_type=TYPE_MAP[section], content=content)
            service_manager()

        

        # 2. Deep Dive into Trigger and Pipeline
        if "trigger" in dsl:
            await self._validate_block(dsl["trigger"], "trigger")
        
        if "pipeline" in dsl:
            for index, task in enumerate(dsl["pipeline"]):
                await self._validate_block(task, f"pipeline_task_{index}")

        print(f"✅ Validation Successful: DSL is safe for execution.")
        return True

    async def _validate_block(self, block: Dict[str, Any], block_id: str):
        Validates a single functional unit (a task or a trigger).
        
        # A. Find which Registry Section we are in
        # We determine this by checking which registry entry's allowed_keys contains this block's keys
        parent_section = "trigger" if "trigger" in block_id else "pipeline"
        
        # B. Service Key Check
        service_val = block.get(self.service_key)
        if not service_val:
            raise SyntaxError(f"[{block_id}] Missing mandatory '{self.service_key}' definition.")

        # C. Key Authorization (Check against Registry + Function Inspection)
        allowed_by_reg = self.maps['ALLOW_KEY_MAP'].get(parent_section, [])
        handler_func = self.maps['ACTION_MAP'].get(parent_section)
        
        # Get dynamic args from the handler function using your inspect_function
        handler_args = inspect_function(handler_func) if handler_func else {}

        for key in block.keys():
            # If the key isn't in registry allowed_keys AND isn't a valid function argument -> Error
            if key not in allowed_by_reg and key not in handler_args and key != self.service_key:
                raise SyntaxError(f"[{block_id}] Unexpected key '{key}'. Not permitted by registry or handler.")

        # D. Third-Level Payload Validation (The API Schema check)
        if "." in service_val: # Check if it's a namespaced service like 'ext.hubspot.create'
            await self._validate_external_payload(service_val, block, block_id, parent_section)

    async def _validate_external_payload(self, service_path: str, block: dict, block_id: str, section: str):
        Uses UnZip to crawl the API schema and verify the 'input' block.
        
        # 1. Construct Path using Registry Metadata
        parts = service_path.split('.')
        # Logic: ext.hubspot.create -> apps/hubspot/create.json
        base_dir = self.maps['ADDRESS_MAP'].get(section, "apps")
        extension = self.maps['FILE_EXT_MAP'].get(section, "json")
        
        # We skip the prefix (ext/script) and build the path
        schema_file = os.path.join(base_dir, *parts[1:]) + f".{extension}"
        
        schema_data = retrieve_file(schema_file)
        if not schema_data:
            raise ImportError(f"[{block_id}] Schema not found for service: {service_path} at {schema_file}")

        # 2. Flatten the Schema with UnZip to find all leaf requirements
        self.unzip.unpack_bulk_data(schema_data)
        flat_schema = self.unzip.key_path # e.g., {'body.properties.email': '{{DataType=str}}'}
        
        user_input = block.get("input", {})

        # 3. Compare Leaf-by-Leaf
        for path, schema_val in flat_schema.items():
            if isinstance(schema_val, str):
                match = self.tag_pattern.search(schema_val)
                if match:
                    expected_type_str = match.group("type")
                    default_val = match.group("default")
                    
                    # The actual field name is the last part of the path
                    field_name = path.split('.')[-1]

                    # Validation Logic
                    if field_name not in user_input and not default_val:
                        raise ValueError(f"[{block_id}] Payload Error: Missing required field '{field_name}' required by {service_path}")
                    
                    if field_name in user_input:
                        self._verify_type(field_name, user_input[field_name], expected_type_str, block_id)

    def validate_type(self, key, expected_type, content=None):
        if not isinstance(content, expected_type):
            raise TypeError(
                f"DATA TYPE MISMATCH: {key} expects {expected_type.__name__}, "
                f"but got {type(content).__name__}."
            )

    def _verify_type2(self, key: str, value: Any, expected_str: str, block_id: str):
        Helper to map string types to Python types.
        # Bypass type checking for dynamic variables
        if not isinstance(value, expected_str):
            return

        if isinstance(value, str) and "{{" in value:
            return

        type_map = {"str": str, "int": int, "float": float, "bool": bool, "dict": dict, "list": list}
        expected_type = type_map.get(expected_str)
        
        if expected_type and not isinstance(value, expected_type):
            raise TypeError(f"[{block_id}] Type Mismatch: Field '{key}' expects {expected_str}, got {type(value).__name__}")

        hooks = {dict: self.validate_types, list: self.validate_types, "primitive": self.validate_types}
        # Start the unpacking process
        for key, value in file.items():
            # Initial validation for top-level keys
            if not key in SECTION_MAP:
                raise TypeError(f"CRITICAL: '{key}' is not recognized.")
            self.unzip.unpack_bulk_data(content=value, key=key, hooks=hooks)
            await self.task_dispatcher(key=key, value=value, name=name, crypto_engine=crypto_engine)
        return self.task_manifest["_sys_manifest"]

    def validate_types(self, value, key, content=None):
        # Validates value against TYPE_MAP if a key is provided.
        if key:
            if not key in schema_reg and key not in self.config_keys and not key in key_list:
                raise SyntaxError(f"wrong key {key}, this key does not exist")
            expected_type = TYPE_MAP.get(key) or key_list.get(key) or self.config_keys.get(key)["annotation"]
            #if TYPE_MAP.get(key) else self.config_keys[key]["annotation"]
            validate_type(expected_type=expected_type, key=key, content=content)
    
    
    async def task_dispatcher(self, key, crypto_engine, value, name, content=None):
        if tk_manager := TASK_MANAGER_MAP.get(key):
            registries = {
                "content": value, "key": key, "service_reg": A_SERVICE_MANAGER_MAP,
                "tk_map": TASK_MANAGER_MAP, "d_map": DEPENDENCY_MAP, "ad_map": ADDRESS_MAP,
                "fl_map": FILE_EXT_MAP, "handlers": ACTION_MAP, "reg": schema_reg, "id_map": ID_MAP,
                "con_map": CONDITION_MAP, "rec_map": RECURSION_MAP, "allow_key": ALLOW_KEY_MAP,
                "trig_map": TRIGGER_MAP, "client_name": name, "crypto_engine": crypto_engine
            }
            self.task_manifest["_sys_manifest"] = await tk_manager(
                regs=registries,
            )

    def check_dependency(self, package, key):
        if dep := DEPENDENCY_MAP[key]:
            missing = missing_field(required=dep, content_to_check=package)
            if missing:
                raise SyntaxError(f" {missing} was not inluded")"""