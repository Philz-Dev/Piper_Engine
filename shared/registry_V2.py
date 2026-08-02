from dataclasses import dataclass, field
from typing import Dict, List, Any, Callable, Optional
from shared.build_subregistry import build_subregistries
from shared.tools import datatype_hook, resolve_service_instruction, extract_types_from_handler, inspect_function, retrieve_file
from shared.unpacked_data import UnZip
import os
import json
import inspect
import re
from difflib import get_close_matches
from datetime import datetime
from enum import IntEnum
from shared import system_functions, helpers

@dataclass
class DependencyRule:
    mandatory: bool = False
    support: bool = False
    managers: List[str] = field(default_factory=list)

@dataclass
class LogEntry:
    timestamp: str
    level: str            # 'info', 'warn', 'error'
    category: str         # 'technical' (Terminal) or 'user' (Activity)
    message: str
    ui_hint: Optional[Dict[str, Any]] = None  # For buttons/actions in UI

@dataclass
class ValidationState:
    seen_ids: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list) # Tip: Consider renaming to 'warnings'
    logs: List[LogEntry] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    depth: int = 0

    def add_log(self, message: str, level: str = "info", category: str = "technical", ui_hint: dict = None):
        indent = "  " * self.depth
        self.logs.append(LogEntry(
            timestamp=datetime.now().isoformat(),
            level=level,
            category=category,
            message=f"{indent}{message}",
            ui_hint=ui_hint
        ))

    # --- UPDATED CONVENIENCE WRAPPERS ---
    def add_error(self, msg: str, category: str = "technical", ui_hint: dict = None):
        self.add_log(msg, level="error", category=category, ui_hint=ui_hint)
        self.errors.append(msg) # <--- THIS WAS MISSING

    def add_warning(self, msg: str, category: str = "technical"):
        self.add_log(msg, level="warn", category=category)
        self.Warning.append(msg) # <--- ADDED THIS

    def add_info(self, msg: str, category: str = "user"):
        self.add_log(msg, level="info", category=category)
        self.info.append(msg) # <--- ADDED THIS

class PiperRegistry:
    def __init__(self, definitions: Dict[str, Any]):
        self._raw = definitions
        # Initialize the factory once at startup
        maps = build_subregistries(definitions=definitions)
        self.registry_lookup = {d["id"]: d for d in definitions.values()}
        self.class_map = {}
        
        # 2. Core Maps (11 total)
        # We use .get(..., {}) to ensure the engine doesn't crash if a map is empty
        self.type_map         = maps.get("type_map", {})
        self.weight_map       = maps.get("weight_map", {})
        self.handler_map      = maps.get("handler_map", {})
        self.allowed_keys_map = maps.get("allowed_keys_map", [])
        self.dependency_map   = maps.get("dependency_map", {})
        self.task_manager_map = maps.get("task_manager_map", {})
        self.address_book_map = maps.get("address_book_map", {})
        self.file_ext_map     = maps.get("file_ext_map", {})
        self.validator_map    = maps.get("validator_map", {})
        self.interpreter_map  = maps.get("interpreter_map", {})
        self.executor_map     = maps.get("executor_map", {})
        self.processor_map    = maps.get("processor_map", {})
        self.id_map           = maps.get("id_map", {})
        self.prefix_map       = maps.get("prefix_map", {})
        self.top_level_key    = maps.get("top_level_key_map", {})
        #print(f"id:   {self.id_map["service"]}")

        # 3. Specialized Manager Maps (6 total)
        self.merger_map       = maps.get("merger_map", {})
        self.action_handlers    = {}
        self.register_all_actions()

        # list of all runtime field keys
        self.list_of_runtime_keys = set()
        self.populate_list_of_keys()
        self.handler_config_keys = []

    def get_action_handler(self, action_name: str):
        """Retrieves the function reference for a given action name."""
        return self.action_handlers.get(action_name)

    def register_action(self, name: str, func: Callable):
        """Registers a function to be accessible by action name."""
        self.action_handlers[name] = func
    
    def register_all_actions(self):
        """
        Dynamically imports actions from system_functions and helpers.
        No need to return anything; this modifies self.action_handlers in place.
        """
        # Ensure system_functions and helpers are imported at the top of this file
        for module in [system_functions, helpers]:
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if not name.startswith('_'):
                    self.register_action(name, func)

    def get_allowed_keys_definition(self, section_key: str) -> Dict[str, Any]:
        """
        Retrieves the 'allowed_keys' dictionary for a section.
        Returns a dict: {SchemaID.KEY: {"mandatory": True/False}}
        """
        definition = self._raw.get(section_key, {})
        # Return the dictionary if it exists, otherwise an empty dict
        raw_keys = definition.get("allowed_keys", {})
        allow_keys = {self.get_key_from_id(target_id=k): v for k, v in raw_keys.items()}
        return allow_keys

    def get_key_from_id(self, target_id: str) -> Optional[str]:
        """
        Retrieves the DSL key associated with a specific ID.
        
        Args:
            target_id: The ID string to search for (e.g., 'service_runner').
            
        Returns:
            The corresponding key name if found, otherwise None.
        """
        # Search the id_map for the matching value
        for key, id_value in self.id_map.items():
            if id_value == target_id:
                return key
        return None

    def get_allowed_ids(self, block_name: str):
        """
        Retrieves a set of SchemaIDs allowed within a specific block.
        """
        schema = self._raw.get(block_name)
        if not schema or "allowed_keys" not in schema:
            return set()
        
        # Extract the 'id' from each dictionary in the allowed_keys list
        return {key for key in schema["allowed_keys"].keys()}
    
    def populate_list_of_keys(self):
        self.list_of_keys = [k for k in self.type_map.keys()]

    
    def get_validator(self, key: str) -> Optional[Callable]:
        definition = self._raw.get(key)
        if isinstance(definition, dict):
            return definition.get("validator")
        return None

    def is_recursive(self, key: str) -> bool:
        return self.recursion_map.get(key, False)

    def get_core_syntax_keys(self):
        inbuild_keys = self._raw
        return [k for k in inbuild_keys.keys()] if inbuild_keys else []
    
    def get_handler(self, service_id: str):
        return self.handler_map.get(service_id)
    
    def identify_manager_role(self, key):
        # Returns 'a_service_manager', 'an_id_manager', etc.
        for role, keys in self.manager_map.items():
            if key in keys:
                return role
        return None
    
    def should_merge(self, key):
        """Returns True if this key's specialist output should be merged."""
        return self.merger_map.get(key, False)
    
    def service_prefix(self, service_key: str, service_value, sub_type: str="sub_validators"):
        """The 'Full Registry' Hydrator."""
        # 1. Resolve the metadata (Mode and Literal Path)
        service_cfg = self._raw.get(service_key, {})
        service_data = service_cfg.get("prefix")
        native_prefix = service_cfg.get("native_namespace", "lib")

        # Determine mode prefix
        prefix = next((p.rstrip(".") for p in service_data if service_value.startswith(p)), None)
        if prefix is None:
            prefix = native_prefix
        return prefix

    def get_all_sub_validators(self) -> Dict[str, Callable]:
        """
        Returns a flattened dictionary of all sub-validators defined in the registry.
        Output example: {"ext": <func>, "lib": <func>, "input": <func>}
        """
        all_subs = {}
        for definition in self._raw.values():
            if isinstance(definition, dict):
                subs = definition.get("sub_validators", {})
                all_subs.update({k: v for k, v in subs.items() if callable(v)})
        return all_subs
    
    def find_dependency_func(self, sub_type: str, registry, step: Dict, dependencies, prefix: str | List=None):
        type = {
            "interpreter": self.sub_interpreter_map, 
            "executor": self.sub_executor_map,
            "validator": self.sub_validator_map
            }
        sub_func_list = {}
        if not type.get(sub_type):
            return
        
        if isinstance(prefix, str):
            prefix = [prefix]
        
        for k, value in step.items():
            for r, v in registry.manager_map.items():
                if k in v and r in dependencies:
                    sub_key = type.get(sub_type)
                    if sub_key:
                        if prefix:
                            prefix = prefix
                        else:
                            prefix = [k]
                        for p in prefix:
                            sub_func = sub_key.get(p)
                            if sub_func:
                                sub_func_list[p] = sub_func
        return sub_func_list
    
    def identify_specific_role(self, key, prefix, role_to_find):
        """
        Determines if the current prefix (e.g., 'webhook') 
        is acting as a specific role (e.g., 'a_cleanup_manager').
        """
        # 1. Get the service configuration (e.g., the 'service' block)
        service_config = self._raw.get(key, {})
        
        # 2. Look up the specific prefix (e.g., 'webhook') in the dependency map
        prefix_config = service_config.get("dependency", {}).get(prefix, {})
        
        # 3. Check if the role is in the supported managers list
        supported = prefix_config.get("supported_manager", {}).get("managers", [])
        
        return role_to_find in supported
    
    def get_all_sub_interpreters(self) -> Dict[str, Callable]:
        """
        Returns a flattened dictionary of all sub-validators defined in the registry.
        Output example: {"ext": <func>, "lib": <func>, "input": <func>}
        """
        all_subs = {}
        for definition in self._raw.values():
            if isinstance(definition, dict):
                subs = definition.get("sub_interpreters", {})
                all_subs.update({k: v for k, v in subs.items() if callable(v)})
        return all_subs
    
    def get_all_sub_executors(self) -> Dict[str, Callable]:
        """
        Returns a flattened dictionary of all sub-validators defined in the registry.
        Output example: {"ext": <func>, "lib": <func>, "input": <func>}
        """
        all_subs = {}
        for definition in self._raw.values():
            if isinstance(definition, dict):
                subs = definition.get("sub_executors", {})
                all_subs.update({k: v for k, v in subs.items() if callable(v)})
        return all_subs
    
    def get_all_sub_processors(self) -> Dict[str, Callable]:
        """
        Returns a flattened dictionary of all sub-validators defined in the registry.
        Output example: {"ext": <func>, "lib": <func>, "input": <func>}
        """
        all_subs = {}
        for definition in self._raw.values():
            if isinstance(definition, dict):
                subs = definition.get("sub_processors", {})
                all_subs.update({k: v for k, v in subs.items() if callable(v)})
        return all_subs
    
    def prefix_executor(self, key: str, prefix_name: str) -> Any:
        """
        Extracts the executor associated with a specific prefix (e.g., 'webhook') 
        under a top-level key (e.g., 'service').
        
        Usage: 
            executor = registry.prefix_executor("service", "webhook")
        """
        # 1. Get the definition for the key (e.g., 'service')
        definition = self._raw.get(key, {})
        
        # 2. Get the prefix dictionary (e.g., the map of webhook, timer, etc.)
        prefixes = definition.get("prefix", {})
        
        # 3. Get the specific prefix config (e.g., the 'webhook' dictionary)
        target_config = prefixes.get(prefix_name, {})
        
        # 4. Return the 'executor' if it exists, otherwise return None/empty list
        return target_config.get("executor")
    
    def prefix_interpreter(self, key: str, prefix_name: str) -> Any:
        """
        Extracts the executor associated with a specific prefix (e.g., 'webhook') 
        under a top-level key (e.g., 'service').
        
        Usage: 
            executor = registry.prefix_executor("service", "webhook")
        """
        # 1. Get the definition for the key (e.g., 'service')
        definition = self._raw.get(key, {})
        
        # 2. Get the prefix dictionary (e.g., the map of webhook, timer, etc.)
        prefixes = definition.get("prefix", {})
        
        # 3. Get the specific prefix config (e.g., the 'webhook' dictionary)
        target_config = prefixes.get(prefix_name, {})
        
        # 4. Return the 'executor' if it exists, otherwise return None/empty list
        return target_config.get("interpreter")
    
    def get_prefix_validator(self, key: str, prefix_name: str) -> Any:
        """
        Extracts the validator associated with a specific prefix (e.g., 'webhook') 
        under a top-level key (e.g., 'service').
        
        Usage: 
            validator = registry.get_prefix_validator("service", "webhook")
        """
         # 1. Get the definition for the key (e.g., 'service')
        definition = self._raw.get(key, {})
        
        # 2. Get the prefix dictionary (e.g., the map of webhook, timer, etc.)
        prefixes = definition.get("prefix", {})
        
        # 3. Get the specific prefix config (e.g., the 'webhook' dictionary)
        target_config = prefixes.get(prefix_name, {})
        
        # 4. Return the 'executor' if it exists, otherwise return None/empty list
        return target_config.get("validator")

    def prefix_processor(self, prefix_name: str, key: str="service") -> Any:
            """
            Extracts the executor associated with a specific prefix (e.g., 'webhook') 
            under a top-level key (e.g., 'service').
            
            Usage: 
                executor = registry.prefix_executor("service", "webhook")
            """
            # 1. Get the definition for the key (e.g., 'service')
            definition = self._raw.get(key, {})
            print(f"definition:    {definition}")
            
            # 2. Get the prefix dictionary (e.g., the map of webhook, timer, etc.)
            prefixes = definition.get("prefix", {})
            print(f"prefixes:    {prefixes}")
            
            # 3. Get the specific prefix config (e.g., the 'webhook' dictionary)
            target_config = prefixes.get(prefix_name, {})
            print(f"target_config:    {target_config}")
            
            # 4. Return the 'executor' if it exists, otherwise return None/empty list
            return target_config.get("processor")

    def gather_all_keys(self, service_key: str, service_value, state: ValidationState):
        """The 'Full Registry' Hydrator."""
        # 1. Resolve the metadata (Mode and Literal Path)
        info = resolve_service_instruction(service_value)
        new_types = {}
        prefix = self.service_prefix(service_key=service_key, service_value=service_value)

        # 1. GATHER FROM JSON (API/External Schema)
        if info and info["validate_input"]:
            # Logic: internal_api uses a specific base_dir logic in retrieve_file
            is_internal = (info["mode"] == "internal_api")
            file_path = info.get("full_path")
            schema_data = retrieve_file(file_path=file_path, base_dir=is_internal)
            
            if schema_data:
                # We get the flattened type map from the JSON
                schema_keys = self.hydrate_from_json(schema_data, state)
                new_types.update(schema_keys)
        handler =  self.prefix_executor(key=service_key, prefix_name=prefix)
        if handler:
            handler_keys = self.hydrate_from_handler(handler)
            # These are usually top-level config keys (not inside 'input')
            new_types.update(handler_keys)
        self.type_map.update(new_types)
        # In gather_all_keys
        runtime_keys = {k.split(".")[-1] for k in self.type_map.keys()} # Use set comprehension
        self.list_of_runtime_keys.update(runtime_keys)
        self.list_of_keys = list(set(self.list_of_keys) | self.list_of_runtime_keys)
   
    def hydrate_from_json(self, json_data: dict, state: ValidationState) -> Dict:
        unzipper = UnZip()
        discovered_schema = {}
        seen_keys_in_this_file = set()
        service_name = json_data.get("name", "UNKNOWN")
        ALLOWED_TYPES = ["str", "int", "bool", "float", "list", "dict"]
        
        # 1. PRE-SCAN: Build the Local Class Registry
        local_class_keys = set()
        if "class" in json_data and isinstance(json_data["class"], dict):
            local_class_keys = set(json_data["class"].keys())
            for k, v in json_data["class"].items():
                self.class_map[f"class.{k}"] = v

        def collection_hook(content, key, value, path, **kwargs):
            actual_val = value[key] if isinstance(value, dict) and key in value else value
            if isinstance(actual_val, str):

                # --- STREAM A: Variable Injection {var} ---
                injections = re.findall(r"(?<!\{)\{([^{}\s]+)\}(?!\})", actual_val)
                
                for var in injections:
                    if path.startswith("class"):
                        state.add_error(f"❌  [Syntax Error] {service_name}: Variable '{{{var}}}' used at {path} 'class' does not permit variable mapping.")
                    if var not in local_class_keys and not path.startswith("class"):
                        matches = get_close_matches(var, list(local_class_keys), n=1, cutoff=0.6)
                        suggestion = f" Did you mean '{matches[0]}'?" if matches else ""
                        state.add_warning(f"⚠️  [Injection Warning] {service_name}: Variable '{{{var}}}' used at {path} is undefined in 'class' block.{suggestion}")

                # --- STREAM B: Dynamic Inputs {{input}} ---
                inputs = re.findall(r"\{\{(.*?)\}\}", actual_val)
                for var_content in inputs:
                    # 1. Mandatory Metadata Check (DataType)
                    if "DataType=" not in var_content:
                        state.add_error(f"❌ [Missing required key value] {service_name}: Input '{{{{{var_content}}}}}' at {path} is missing mandatory 'DataType' definition.")
                    else:
                        # 2. Type Validity Check
                        # Extracts 'str' from 'DataType=str, Value=...'
                        type_match = re.search(r"DataType=([^,\s}]+)", var_content)
                        if type_match:
                            declared_type = type_match.group(1)
                            if declared_type not in ALLOWED_TYPES:
                                state.add_error(f"❌ [Type Error] {service_name}: Invalid DataType '{declared_type}' at {path}. (Allowed: {', '.join(ALLOWED_TYPES)})")

                    # 3. Architectural Violation: Duplicate Key Check
                    var_name = var_content.split('=')[-1] if '=' in var_content else var_content
                    if key in seen_keys_in_this_file:
                        if var_name not in local_class_keys:
                            error_msg = (
                                f"[{service_name}] Architectural Violation: Duplicate key '{key}' found with input '{{{{{var_name}}}}}'. "
                                f"Piper requires shared keys to be managed via the 'class' block to ensure type safety."
                            )
                            state.add_error(error_msg)
                    
                    seen_keys_in_this_file.add(key)

            # 4. Data Type Hydration
            found_type = datatype_hook(content, key, value)
            if found_type:
                discovered_schema[path] = found_type

        unzipper.unpack_bulk_data(
            content=json_data, 
            hooks={"primitive": collection_hook}
        )
        return discovered_schema
    
    def hydrate_from_json_V2(self, json_data: dict) -> Dict:
        unzipper = UnZip()
        discovered_schema = {}
        seen_keys_in_this_file = set()
        service_name = json_data.get("name", "UNKNOWN")

        # Updated hook to accept 'path'
        def collection_hook(content, key, value, path, **kwargs):
            if path.startswith("class"): 
                return
            
            actual_data = value[key] if isinstance(value, dict) and key in value else value
            
            is_input = isinstance(actual_data, str) and actual_data.startswith("{{") and actual_data.endswith("}}")

            if is_input:
                if key in seen_keys_in_this_file:
                    # Using your exact architectural violation string
                    error_msg = (
                        f"[{service_name}] Architectural Violation: Duplicate key '{key}' found. "
                        f"Piper Engine requires shared keys to be managed via the 'class' block "
                        f"to ensure type safety and prevent collisions."
                    )
                    raise ValueError(error_msg)
            
                seen_keys_in_this_file.add(key)

            found_type = datatype_hook(content, key, value)
            if found_type:
                # UNIQUE ADDRESS: Use the path, not just the key
                discovered_schema[path] = found_type

        unzipper.unpack_bulk_data(
            content=json_data, 
            hooks={"primitive": collection_hook}
        )
        
        return discovered_schema

    def hydrate_from_handler(self, func) -> Dict:
        """
        Calls inspect_function and maps annotations to the Registry.
        """
        details = inspect_function(func)
        handler_types = {}
        
        for name, info in details.items():
            # If the function has a type hint (annotation), we use it
            if info["annotation"] is not inspect.Parameter.empty:
                handler_types[name] = info["annotation"]
            else:
                # Fallback to str or a generic type if no hint is provided
                handler_types[name] = Any 
            self.handler_config_keys.append(name)

        # Update the global registry map""
        return handler_types
    
    def get_sub_validator(self, section: str, section_id: str) -> Optional[Callable]:
        """Retrieves a validator nested inside a parent section."""
        section_def = self._raw.get(section, {})
        if isinstance(section_def, dict):
            return section_def.get("sub_validators", {}).get(section_id)
        return None
    
    def get_sub_interpreter(self, section: str, section_id) -> Optional[Callable]:
        """Retrieves a validator nested inside a parent section."""
        section_def = self._raw.get(section, {})
        if isinstance(section_def, dict):
            return section_def.get("sub_interpreter", {}).get(section_id)
        return None


    def get_keys_by_feature(self, feature_name: str) -> list:
        """Returns all top-level keys that have a specific feature flag set to True."""
        return [k for k, v in self._raw.items() if v.get(feature_name) is True]

    def get_dependency_rules(self, section_key: str) -> Dict[str, DependencyRule]:
        raw_deps = self.dependency_map.get(section_key, {})
        
        # If the dependency is a list (v1 style), we convert it to the new Rule format
        if isinstance(raw_deps, list):
            return {item: DependencyRule(mandatory=True) for item in raw_deps}
            
        # If it's a dict (v2 style), we unpack it into our Dataclass
        if isinstance(raw_deps, dict):
            return {k: DependencyRule(**v) for k, v in raw_deps.items()}
            
        return {}
    
    def get_service_dependency_rules(self, section_key: str, mode: str) -> Dict[str, DependencyRule]:
        """
        Retrieves dependency rules for 'service' based on its mode (prefix).
        """
        # 1. Get the raw dependency map for 'service'
        raw_deps = self._raw.get(section_key, {})
        if not isinstance(raw_deps, dict):
            return {}

        # 3. Retrieve the rules for that specific mode
        prefix_cont = raw_deps.get("prefix", {})
        prefix_selected_cont = prefix_cont.get(mode, {}) # Added default empty dict
        mode_rules = prefix_selected_cont.get("dependency", {})
        
        # FIX: Convert raw dicts to DependencyRule dataclasses so getattr() works
        return {k: DependencyRule(**v) for k, v in mode_rules.items()}

    def get_sub_validator(self, section_key: str, section_id: str) -> Dict[str, Any]:
        if h := self.validator_map.get(section_key, {}):
            if h and isinstance(h, dict):
                return h.get(section_id, {})
        return h
    
    def get_sub_executor(self, section_key: str, section_id: str) -> Dict[str, Any]:
        if h := self.executor_map.get(section_key, {}):
            if h and isinstance(h, dict):
                return h.get(section_id, {})
        return h
    
    def is_section_manager(self, section_key: str) -> bool:
        """Check if the given key represents a top-level section manager."""
        return section_key in self.section_map
    
    def has_prefix(self, key):
        if self.prefix_map.get(key):
            return True
        return False
    
    def _build_role_to_keys_map(self) -> Dict[str, List[str]]:
        """
        Creates a map where keys are the Manager Roles and values are lists of DSL keys.
        Output: {"an_id_manager": ["id"], "an_input_manager": ["input", "payload"]}
        """
        role_map = {}
        
        for dsl_key, definition in self._raw.items():
            if isinstance(definition, dict):
                # Find the manager flag (e.g., 'an_id_manager')
                for field, value in definition.items():
                    if field.endswith("_manager") and value is True:
                        # If this manager role isn't in our map yet, initialize the list
                        if field not in role_map:
                            role_map[field] = []
                        
                        # Add the DSL key to the list for this manager role
                        role_map[field].append(dsl_key)
                        
        return role_map
    
