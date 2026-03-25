from dev_utils.universal_dispatcher.core import dispatcher
from dev_utils.trigger_service_manager import trigger_exe
from dev_utils import task_managers
from dev_utils.pipeline_executor import Executor

pipe_run = Executor()
schema_reg = {
    "owner": { 
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], 
        "is_section": False, "dependency": [], "task_manager": None, "a_service_manager": False,
        "address_book": None, "file_ext": None, "an_id_manager": False, "a_condition_manager": False,
        "a_recursive_manager": False, "a_trigger_manager": False
    },
    "name": { 
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], 
        "is_section": False, "dependency": [], "task_manager": None, "a_service_manager": False,
        "address_book": None, "file_ext": None, "an_id_manager": False, "a_condition_manager": False, 
        "a_recursive_manager": False, "a_trigger_manager": False
    },
    "app_service": {
        "type": str, "handler": dispatcher, "weight": 0, "is_section": False,
        "allowed_keys": [], "dependency": ["with"], "task_manager": task_managers.app_service, "a_service_manager": True,
        "address_book": "apps", "file_ext": "json", "a_trigger_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False
    },
    "on_responds": {
        "type": dict, "handler": None, "weight": 3, "a_service_manager": False,
        "allowed_keys": [], "is_section": False, "dependency": [], "task_manager": None,
        "address_book": None, "file_ext": None, "an_id_manager": False, "a_condition_manager": False,
        "a_recursive_manager": False, "a_trigger_manager": False
    },
    "interval": {
        "type": dict, "weight": 10, "handler": None, "is_section": False, "a_service_manager": False,
        "allowed_keys": [], "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False
    },
    "id": { 
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": task_managers.naming, "address_book": None, "file_ext": None,
        "an_id_manager": True, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False
    },
    "Pipeline": {
        "type": list, "weight": 10, "handler": pipe_run.call_run_executor, "a_service_manager": False,
        "allowed_keys": ["id", "app_service", "with", "maps", "timeout", "steps", "condition", "trigger"], "is_section": True,
        "dependency": ["id"], "task_manager": task_managers.run_pipeline,
        "address_book": None, "file_ext": None, "an_id_manager": False, "a_condition_manager": False, 
        "a_recursive_manager": False, "a_trigger_manager": False
    },
    "with": {
        "type": dict, "handler": None, "weight": 10, 
        "allowed_keys": ["content", "keys", "channel", "message", "query", "location", "form_id"],
        "is_section": False, "dependency": [r"\{\{\$\.\s*(\w+)\s*\}\}", r"\{\{\w+\}\}"], "task_manager": task_managers.build_with,
        "a_service_manager": False, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False,
        "a_trigger_manager": False
    },
    "steps": {
        "type": list, "weight": 10, "handler": None, "allowed_keys": [], 
        "is_section": False, "dependency": [], "task_manager": None,
        "a_service_manager": False, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": True,
        "a_trigger_manager": False
    },
    "content": {
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], 
        "is_section": False, "dependency": [], "task_manager": None,
        "a_service_manager": False, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False,
        "a_trigger_manager": False
    },
    "sentinel": {
        "type": dict, "handler": None,  "weight": 1, "is_section": True,
        "allowed_keys": ["on_responds", "interval", "fail_fast"],
        "dependency": [], "task_manager": task_managers.sentinel_tk, "a_trigger_manager": False,
        "a_service_manager": False, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False
    },
    "version": {
        "type": float, "handler": None,"allowed_keys": [], "weight": 0, 
        "is_section": True, "dependency": [], "task_manager": task_managers.add_version,
        "a_service_manager": False, "address_book": None, "file_ext": None, "a_trigger_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False,
    },
    "import": {
        "type": list, "handler": None,"allowed_keys": [], "weight": 0, 
        "is_section": True, "dependency": [], "task_manager": task_managers.import_tk,
        "a_service_manager": False, "address_book": None, "file_ext": None, "a_trigger_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False
    },
    "metadata": {
        "type": dict, "weight": 10, "handler": None, "allowed_keys": [], 
        "is_section": True, "dependency": [], "task_manager": task_managers.metadata_tk,
        "a_service_manager": False, "address_book": None, "file_ext": None, "a_trigger_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False
    },
    "fail_fast": {
        "type": bool, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False
    },
    "message": {
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False
    },
    "condition": { 
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": True, "a_recursive_manager": False, "a_trigger_manager": False
    },
    "location": {
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False
    },
    "trigger": { 
        "type": str, "weight": 10, "handler": trigger_exe, "allowed_keys": ["webhook"], 
        "is_section": False, "dependency": ["with"], "task_manager": task_managers.trigger, "a_service_manager": False,
        "address_book": "apps", "file_ext": "json", "an_id_manager": False, "a_condition_manager": False, 
        "a_recursive_manager": False, "a_trigger_manager": True
    }
}

# The Master Definition (Your only source of truth)

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

# Execute once at startup
TYPE_MAP, WEIGHT_MAP, ACTION_MAP, ALLOW_KEY_MAP, DEPENDENCY_MAP, TASK_MANAGER_MAP, A_SERVICE_MANAGER_MAP, ADDRESS_MAP, FILE_EXT_MAP, CONDITION_MAP, ID_MAP, RECURSION_MAP, SECTION_MAP, TRIGGER_MAP = build_subregistries(schema_reg)

