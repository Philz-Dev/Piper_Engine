from typing import Dict, Any

# Define the Source of Truth based on your schema_reg
CORE_KEYS = [
    "type", "weight", "handler", "allowed_keys", "dependency", 
    "task_manager", "address_book", "file_ext", "validator", 
    "interpreter", "executor", "sub_handlers", "sub_validators"
]

# Mapping the boolean flags to their internal map names
MANAGER_MAP_CONFIG = {
    "is_section": "section_map",
    "a_service_manager": "service_map",
    "a_trigger_manager": "trigger_map",
    "an_id_manager": "id_map",
    "a_condition_manager": "condition_map",
    "a_recursive_manager": "recursion_map",
    "is_merger": "merger_map"
}

def build_subregistries(definitions: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The Factory: Generates optimized lookup maps for the Piper Engine."""
    
    # Initialize all potential maps
    registry_maps = {f"{k}_map": {} for k in CORE_KEYS}
    for map_name in MANAGER_MAP_CONFIG.values():
        registry_maps[map_name] = {}

    for key, cfg in definitions.items():
        # 1. Validation: Ensure the definition is complete
        all_keys = CORE_KEYS + list(MANAGER_MAP_CONFIG.keys())
        missing = [k for k in all_keys if k not in cfg]
        if missing:
            raise ValueError(f"CRITICAL: '{key}' is missing: {missing}")

        # 2. Populate Core Value Maps
        for core_k in CORE_KEYS:
            registry_maps[f"{core_k}_map"][key] = cfg[core_k]

        # 3. Populate Manager Maps (Only if the flag is True)
        for flag, map_name in MANAGER_MAP_CONFIG.items():
            if cfg.get(flag) is True:
                registry_maps[map_name][key] = True

    return registry_maps