from shared import interpreter
from shared.executor import trigger_exe
from shared.universal_dispatcher.core import dispatcher
from shared.execute_in_sandbox import execute_in_sandbox
# from shared.interpreter import external_script, external_schema
from shared import validators_V2


schema_reg = {
    "service": {
        "type": str, "handler": dispatcher, "weight": 0, "is_section": False,
        "allowed_keys": [], 
        "dependency": {
            "ext": {
                "an_input_manager": {
                    "mandatory": True, "support": 1
                }
            },
            "script": {
                "an_input_manager": {
                    "mandatory": False, "support": 0
                }
            },
            "lib": {
                "an_input_manager": {
                    "mandatory": True, "support": 1
                }
            }
        }, 
        "task_manager": [], "a_service_manager": True, "native_namespace": "lib", "is_merger": True,
        "address_book": "apps", "file_ext": "json", "a_trigger_manager": False, "validator": validators_V2.validate_service, "interpreter": interpreter.app_service, "executor": [],
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "an_input_manager": False,
        "sub_validators": {
            "ext": validators_V2.validate_native_service,
            "script": validators_V2.validate_sandbox_service,
            "lib": validators_V2.validate_native_service,
        },
        "sub_handlers": {
            "ext": dispatcher,
            "script": execute_in_sandbox,
            "lib": dispatcher
        }
    },
    "interval": {
        "type": dict, "weight": 10, "handler": None, "is_section": False, "a_service_manager": False,
        "allowed_keys": [], "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False,
        "validator": [], "interpreter": [], "executor": [], "sub_validators": {}, "sub_handlers": {},
        "an_input_manager": False, "is_merger": False
    },
    "id": { 
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": [], "address_book": None, "file_ext": None,
        "an_id_manager": True, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False,
        "validator": validators_V2.validate_id, "interpreter": interpreter.assign_key_value, "executor": [], "sub_validators": {}, "sub_handlers": {},
        "an_input_manager": False, "is_merger": False
    },
    "pipeline": {
        "type": list, "weight": 10, "handler": [], "a_service_manager": False, "sub_validators": {}, "sub_handlers": {},
        "allowed_keys": ["id", "service", "input", "steps", "condition"], "is_section": True,
        "dependency": {
            "service_map": {"mandatory": True, "support": 1},
            "id_map": {"mandatory": True, "support": 1},
            "condition_map": {"mandatory": False, "support": 1},
            "recursion_map": {"mandatory": False, "support": 1}
        },
        "task_manager": [],
        "address_book": None, "file_ext": None, "an_id_manager": False, "a_condition_manager": False, "an_input_manager": False, "is_merger": False,
        "a_recursive_manager": False, "a_trigger_manager": False, "validator": validators_V2.validate_pipeline, "interpreter": interpreter.run_pipeline, "executor": []
    },
    "input": {
        "type": dict, "handler": None, "weight": 10, "validator": [], "interpreter": [], "executor": [],
        "allowed_keys": [], "sub_interpreter": {"input": interpreter.build_input},
        "is_section": False, "dependency": {"pattern": r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}"}, "task_manager": [],
        "a_service_manager": False, "address_book": None, "file_ext": None, "address_book": None, 
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False,
        "a_trigger_manager": False, "sub_validators": {"input": validators_V2.validate_input_v2},
        "interpreter": [], "an_input_manager": True, "is_merger": False, "sub_handlers": {}
    },
    "steps": {
        "type": list, "weight": 10, "handler": None, "allowed_keys": [], "is_merger": False,
        "is_section": False, "dependency": [], "task_manager": None, "sub_validators": {}, "sub_handlers": {},
        "a_service_manager": False, "address_book": None, "file_ext": None, "an_input_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": True,
        "a_trigger_manager": False, "validator": [], "interpreter": [], "executor": [],
    },
    "version": {
        "type": str, "handler": None,"allowed_keys": [], "weight": 0, "validator": [], "interpreter": [], "executor": [],
        "is_section": True, "dependency": [], "task_manager": [], "an_input_manager": False,
        "a_service_manager": False, "address_book": None, "file_ext": None, "a_trigger_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False,
        "sub_validators": {}, "sub_handlers": {}, "is_merger": False
    },
    "condition": { 
        "type": str, "weight": 10, "handler": None, "allowed_keys": [], "a_service_manager": False,
        "is_section": False, "dependency": [], "task_manager": None, "address_book": None, "file_ext": None,
        "an_id_manager": False, "a_condition_manager": True, "a_recursive_manager": False, "a_trigger_manager": False,
        "validator": validators_V2.validate_condition_syntax, "interpreter": interpreter.assign_key_value, "executor": [], "sub_validators": {}, "sub_handlers": {},
        "an_input_manager": False, "is_merger": False
    },
    "trigger": { 
        "type": str, "weight": 10, "handler": trigger_exe, "allowed_keys": ["id", "service", "input", "timeout", "steps", "condition"], 
        "is_section": False, 
        "dependency": {
            "service_map": {"mandatory": True, "support": 1},
            "id_map": {"mandatory": True, "support": 1},
        },
        "task_manager": [], "a_service_manager": False,
        "address_book": "apps", "file_ext": "json", "an_id_manager": False, "a_condition_manager": False, 
        "a_recursive_manager": False, "a_trigger_manager": True, "validator": validators_V2.validator_trigger, "interpreter": [], "executor": [],
        "sub_validators": {}, "sub_handlers": {}, "an_input_manager": False, "is_merger": False
    },
}