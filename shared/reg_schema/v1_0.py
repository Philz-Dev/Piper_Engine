from shared import interpreter
from shared.universal_dispatcher_v2.core import dispatcher
from shared.execute_in_sandbox import execute_in_sandbox
# from shared.interpreter import external_script, external_schema
from shared import validators_V2
from shared import executor, processor

schema_reg = {
    "service": {
        "type": str, "executor": executor.service_executor, "weight": 0, "is_section": False,
        "allowed_keys": ["ext", "script", "lib", "webhook", "timer"], "a_pipeline_manager": False, "sub_interpreters": {},
        "dependency": {
            "ext": {
                "an_input_manager": {
                    "mandatory": True, "support": 1
                },
                "supported_manager": {
                    "managers": ["a_pipeline_manager"]
                }
            },
            "script": {
                "an_input_manager": {
                    "mandatory": False, "support": 0
                },
                "supported_manager": {
                    "managers": ["a_pipeline_manager"]
                }
            },
            "lib": {
                "an_input_manager": {
                    "mandatory": True, "support": 1
                },
                "supported_manager": {
                    "managers": ["a_pipeline_manager"]
                }
            },
            "webhook": {
                "an_input_manager": {
                    "mandatory": True, "support": 1
                },
                "supported_manager": {
                    "managers": ["a_trigger_manager"]
                }
            },
            "timer": {
                "an_input_manager": {
                    "mandatory": False, "support": 0
                },
                "supported_manager": {
                    "managers": ["a_trigger_manager"]
                }
            }

        }, 
        "a_service_manager": True, "native_namespace": "lib", "is_merger": True, "processor": [],
        "address_book": "apps", "file_ext": "json", "a_trigger_manager": False, "validator": validators_V2.validate_service_v2, "interpreter": interpreter.app_service,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "an_input_manager": False,

        "sub_validators": {
            "timer": validators_V2.validate_timer,
            "script": validators_V2.validate_script
        },
        "sub_executors": {
            "ext": dispatcher,
            "script": executor.execute_in_sandbox,
            "lib": dispatcher,
            "webhook": dispatcher,
            "timer": executor.schedule_executor
        },
        "sub_processors": {
            "webhook": processor.start_webhook,
            "timer": processor.schedule
        },
        "sub_interpreters": {
            "script": interpreter.script_interpreter,
            "webhook": interpreter.webhook_func
        }
    },
    "id": { 
        "type": str, "weight": 10, "allowed_keys": [], "a_service_manager": False, "a_pipeline_ma nager": False,
        "is_section": False, "dependency": [], "address_book": None, "file_ext": None, "sub_interpreters": {},
        "an_id_manager": True, "a_condition_manager": False, "a_recursive_manager": False, "a_trigger_manager": False,
        "validator": validators_V2.validate_id, "interpreter": interpreter.assign_key_value, "executor": [], "sub_validators": {},
        "an_input_manager": False, "is_merger": False, "processor": [], "sub_processors": {}, "sub_executors": {}
    },
    "pipeline": {
        "type": list, "weight": 10, "executor": executor.PipelineExecutor, "a_service_manager": False, "sub_validators": {}, "sub_executors": {},
        "allowed_keys": ["id", "service", "input", "steps", "condition"], "is_section": True,
        "dependency": {
            "service_map": {"mandatory": True, "support": 1},
            "id_map": {"mandatory": True, "support": 1},
            "condition_map": {"mandatory": False, "support": 1},
            "recursion_map": {"mandatory": False, "support": 1}
        },
        "processor": processor.pipeline_processor, "sub_processors": {},
        "address_book": None, "file_ext": None, "an_id_manager": False, "a_condition_manager": False, "an_input_manager": False, "is_merger": False,
        "a_recursive_manager": False, "a_trigger_manager": False, "validator": validators_V2.validate_pipeline, "interpreter": interpreter.run_pipeline,
        "a_pipeline_manager": True, "sub_interpreters": {}
    },
    "input": {
        "type": dict, "weight": 10, "validator": [], "executor": [], "a_pipeline_ma nager": False,
        "allowed_keys": [], "sub_interpreters": {"input": interpreter.build_input_v2},
        "is_section": False, "dependency": {"pattern": r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}"},
        "a_service_manager": False, "address_book": None, "file_ext": None, "sub_executors": {},
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "processor": [],
        "a_trigger_manager": False, "sub_validators": {"input": validators_V2.validate_input_v2},
        "interpreter": [], "an_input_manager": True, "is_merger": False, "executor": [], "sub_processors": {}
    },
    "steps": {
        "type": list, "weight": 10, "allowed_keys": [], "is_merger": False, "sub_executors": {},
        "is_section": False, "dependency": [], "sub_validators": {}, "processor": [], "a_pipeline_manager": False,
        "a_service_manager": False, "address_book": None, "file_ext": None, "an_input_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": True, "sub_interpreters": {},
        "a_trigger_manager": False, "validator": validators_V2.validate_recursive, "interpreter": interpreter.recursive_step_manager, "executor": [], "sub_processors": {}
    },
    "version": {
        "type": str, "allowed_keys": [], "weight": 0, "validator": [], "interpreter": interpreter.version_interpreter, "executor": [],
        "is_section": True, "dependency": [], "an_input_manager": False, "sub_executors": {}, "sub_interpreters": {},
        "a_service_manager": False, "address_book": None, "file_ext": None, "a_trigger_manager": False,
        "an_id_manager": False, "a_condition_manager": False, "a_recursive_manager": False, "a_pipeline_ma nager": False,
        "sub_validators": {}, "is_merger": False, "executor": [], "processor": processor.version_processor, "sub_processors": {}
    },
    "condition": { 
        "type": str, "weight": 10, "allowed_keys": [], "a_service_manager": False, "sub_executors": {},
        "is_section": False, "dependency": {}, "address_book": None, "file_ext": None, "a_pipeline_ma nager": False,
        "an_id_manager": False, "a_condition_manager": True, "a_recursive_manager": False, "a_trigger_manager": False,
        "validator": validators_V2.validate_condition_syntax, "interpreter": interpreter.assign_key_value, "sub_validators": {},
        "an_input_manager": False, "is_merger": False, "executor": [], "sub_processors": {}, "processor": [], "sub_interpreters": {}
    },
    "trigger": { 
        "type": list, "weight": 10, "processor": processor.trigger_processor, "allowed_keys": ["id", "service", "input"], 
        "is_section": True,
        "dependency": {
            "service_map": {"mandatory": True, "support": 1},
            "id_map": {"mandatory": True, "support": 1},
            "condition_map": {"mandatory": False, "support": 0},
            "recursion_map": {"mandatory": False, "support": 0}
        },
        "sub_processors": {}, "sub_validators": {},
        "a_service_manager": False, "a_pipeline_manager": False,
        "address_book": "apps", "file_ext": "json", "an_id_manager": False, "a_condition_manager": False, 
        "a_recursive_manager": False, "a_trigger_manager": True, "validator": validators_V2.validate_pipeline, "interpreter": interpreter.run_pipeline,
        "executor": [], "an_input_manager": False, "is_merger": False, "sub_executors": {}, "sub_interpreters": {}
    },
}