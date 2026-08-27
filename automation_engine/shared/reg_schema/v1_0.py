from enum import IntEnum
import interpreter
from universal_dispatcher_v2.core import dispatcher
import validators_V2
import executor, processor
from .schemaid import SchemaID
import system_functions

schema_reg = {
    "__main__": {
        "top_level_key": True,
        "id": SchemaID.MAIN,
        "type": None,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.PIPELINE: {"mandatory": True}, 
            SchemaID.TRIGGER: {"mandatory": True}, 
            SchemaID.VERSION: {"mandatory": True},
            SchemaID.ON_COMPLETE: {"mandatory": False},
            SchemaID.ON_ERROR: {"mandatory": False},
            SchemaID.ON_SUCCESS: {"mandatory": False},
            SchemaID.IMPORT: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.main_validator,
        "interpreter": interpreter,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "service": {
        "top_level_key": False,
        "id": SchemaID.SERVICE,
        "type": str,
        "weight": 0,
        "is_merger": True,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.validate_service_v2,
        "interpreter": interpreter.app_service,
        "executor": executor.service_executor,
        "processor": [],
        "native_namespace": "lib",
        "address_book": "apps",
        "file_ext": "json",
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "partial_mandatory": [],
        "is_service_manager": True,
        "prefix": {
            "ext": {
                "dependency": {SchemaID.INPUT: {"mandatory": True, "support": True}},
                "executor": dispatcher,
                "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER]
            },
            "script": {
                "dependency":  {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "interpreter": interpreter.script_interpreter,
                "executor": executor.execute_in_sandbox,
                "validator": "validators_V2.validate_script",
                "top_level_parent": [SchemaID.PIPELINE]
            },
            "lib": {
                "dependency": {SchemaID.INPUT: {"mandatory": True, "support": True}},
                "executor": dispatcher,
                "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER]
            },
            "webhook": {
                "dependency": {SchemaID.INPUT: {"mandatory": True, "support": True}},
                "processor": processor.start_webhook,
                "executor": dispatcher,
                "top_level_parent": [SchemaID.TRIGGER]
            },
            "timer": {
                "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "interpreter": interpreter.webhook_func,
                "processor": processor.schedule,
                "executor": executor.schedule_executor,
                "validator": "validators_V2.validate_timer",
                "top_level_parent": [SchemaID.TRIGGER]
            },
            "iter": {
                "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "executor": executor.iterator,
                "top_level_parent": [SchemaID.PIPELINE]
            },
            "aggr": {
                "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "executor": executor.aggregator_executor,
                "top_level_parent": [SchemaID.PIPELINE]
            },
            "load": {
                "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "executor": executor.bin_executor,
                "top_level_parent": [SchemaID.PIPELINE]
            },
            "sys": {
                "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "top_level_parent": [SchemaID.PIPELINE],
                "prefix": {
                    "execute": {
                        "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                        "executor": {},
                        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER]
                    }
                }
            }


        }
    },

    "id": {
        "top_level_key": False,
        "id": SchemaID.ID,
        "type": str,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.validate_id,
        "interpreter": interpreter.assign_key_value,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "pipeline": {
        "top_level_key": True,
        "id": SchemaID.PIPELINE,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": False}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False},
            SchemaID.OPERATIONS: {"mandatory": False},
            SchemaID.ON_ERROR: {"mandatory": False},
            SchemaID.ON_COMPLETE: {"mandatory": False},
            SchemaID.ON_SUCCESS: {"mandatory": False},
            SchemaID.USE: {"mandatory": False}
        },
        "dependency": {},
        "partial_mandatory": [SchemaID.SERVICE, SchemaID.USE],
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.pipeline_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {},
        "is_service_manager": False
    },
    "input": {
        "top_level_key": False,
        "id": SchemaID.INPUT,
        "type": dict,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {SchemaID.CONDITION: {"mandatory": False}},
        "dependency": {},
        "validator": validators_V2.validate_input_v2,
        "interpreter": interpreter.build_input_v2,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "steps": {
        "top_level_key": False,
        "id": SchemaID.STEPS,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys":  {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": True}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.CONDITION: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.validate_recursive,
        "interpreter": interpreter.core_interpreter,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "version": {
        "top_level_key": True,
        "id": SchemaID.VERSION,
        "type": str,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": [],
        "interpreter": interpreter.version_interpreter,
        "executor": [],
        "processor": processor.version_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "condition": {
        "top_level_key": False,
        "id": SchemaID.CONDITION,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.IF: {"mandatory": False}, 
            SchemaID.ELSE: {"mandatory": False}, 
            SchemaID.OPERATIONS: {"mandatory": False},
            SchemaID.VALUE: {"mandatory": False},
            SchemaID.ELIF: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.validate_condition,
        "interpreter": [],
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "if": {
        "top_level_key": False,
        "id": SchemaID.IF,
        "type": str,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.validate_condition_syntax,
        "interpreter": interpreter.assign_key_value,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "else": {
        "top_level_key": False,
        "id": SchemaID.ELSE,
        "type": dict,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {SchemaID.OPERATIONS: {"mandatory": True}},
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": [],
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "action": {
        "top_level_key": False,
        "id": SchemaID.ACTION,
        "type": str,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.action_validator,
        "interpreter": [],
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [
            SchemaID.PIPELINE,
            SchemaID.ON_COMPLETE, 
            SchemaID.ON_ERROR,
            SchemaID.ON_SUCCESS

        ],
        "prefix": {
            "call": {
                "dependency": {},
                "executor": system_functions.call,
                # 🛠️ FIX: CONDITION added alongside 'goto' (see that entry below for
                # why) - 'map'-style DSL files put actions directly under a
                # top-level 'condition:' section, which none of these prefixes
                # previously allowed.
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ],
                "validator": "validators_V2.call_validator"
            },
            "ignore": {
                "dependency":  {},
                "interpreter": interpreter.script_interpreter,
                "executor": system_functions.ignore,
                "validator": {},
                "top_level_parent": [
                    SchemaID.PIPELINE,
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "sleep": {
                "dependency": {},
                "executor": system_functions.sleep,
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "stop": {
                "dependency": {},
                "processor": processor.start_webhook,
                "executor": system_functions.stop,
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "exit": {
                "dependency": {},
                "interpreter": interpreter.webhook_func,
                "processor": processor.schedule,
                "executor": system_functions.exit,
                "validator": "validators_V2.validate_timer",
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "retry": {
                "dependency": {},
                "interpreter": interpreter.webhook_func,
                "processor": processor.schedule,
                "executor": system_functions.retry,
                "validator": "validators_V2.validate_timer",
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "goto": {
                "dependency": {},
                "interpreter": interpreter.webhook_func,
                "processor": processor.schedule,
                "executor": system_functions.goto,
                "validator": "validators_V2.validate_timer",
                # 🛠️ FIX: CONDITION added - 'map'-style DSL files put 'action: goto'
                # directly under a top-level 'condition:' section (a decision map),
                # not under 'pipeline'/'on_complete'/'on_error'/'on_success' like a
                # waterfall file. Without CONDITION here, action_validator rejected
                # every 'goto' in a map.yml file with "'condition' does not support
                # the action type 'goto'." even though 'condition' is a legitimate
                # place for it in this DSL type.
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "break": {
                "dependency": {},
                "interpreter": interpreter.webhook_func,
                "processor": processor.schedule,
                "executor": system_functions.to_break,
                "validator": "validators_V2.validate_timer",
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            },
            "continue": {
                "dependency": {},
                "interpreter": interpreter.webhook_func,
                "processor": processor.schedule,
                "executor": system_functions.skip,
                "validator": "validators_V2.validate_timer",
                "top_level_parent": [
                    SchemaID.PIPELINE, 
                    SchemaID.ON_COMPLETE, 
                    SchemaID.ON_ERROR,
                    SchemaID.ON_SUCCESS,
                    SchemaID.CONDITION
                ]
            }
        },
        "partial_mandatory": [],
        "is_service_manager": True
    },
    "operations": {
        "top_level_key": False,
        "id": SchemaID.OPERATIONS,
        "type": list,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ACTION: {"mandatory": True}
        },
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": [],
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [
            SchemaID.PIPELINE, 
            SchemaID.TRIGGER, 
            SchemaID.ON_COMPLETE,
            SchemaID.ON_ERROR,
            SchemaID.ON_SUCCESS
        ],
        "parent": [SchemaID.CONDITION],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "trigger": {
        "top_level_key": True,
        "id": SchemaID.TRIGGER,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": False}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.CONDITION: {"mandatory": False},
            SchemaID.OPERATIONS: {"mandatory": False},
            SchemaID.ON_ERROR: {"mandatory": False},
            SchemaID.ON_COMPLETE: {"mandatory": False},
            SchemaID.ON_SUCCESS: {"mandatory": False},
            SchemaID.USE: {"mandatory": False}
        },
        "partial_mandatory": [SchemaID.SERVICE, SchemaID.USE],
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": [],
        "processor": processor.trigger_processor,
        "address_book": "apps",
        "file_ext": "json",
        "top_level_parent": [],
        "parent": [],
        "prefix": {},
        "is_service_manager": False
    },
    "value": {
        "top_level_key": False,
        "id": SchemaID.VALUE,
        "type": str,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": [],
        "interpreter": [],
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "elif": {
        "top_level_key": False,
        "id": SchemaID.ELIF,
        "type": str,
        "weight": 0,
        "is_merger": False,
        "allowed_keys": {SchemaID.VALUE: {"mandatory": False}},
        "dependency": {},
        "validator": validators_V2.validate_condition_syntax,
        "interpreter": [],
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "on_complete": {
        "top_level_key": True,
        "id": SchemaID.ON_COMPLETE,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": False}, 
            SchemaID.SERVICE: {"mandatory": False}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False},
            SchemaID.OPERATIONS: {"mandatory": False},
            SchemaID.ON_ERROR: {"mandatory": False},
            SchemaID.ON_COMPLETE: {"mandatory": False},
            SchemaID.ON_SUCCESS: {"mandatory": False},
            SchemaID.ACTION: {"mandatory": False},
            SchemaID.IF: {"mandatory": False},
            SchemaID.ELSE: {"mandatory": False},
            SchemaID.ELIF: {"mandatory": False},
            SchemaID.USE: {"mandatory": False}

        },
        "dependency": {},
        "validator": validators_V2.on_group_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.on_complete_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [
            SchemaID.PIPELINE, 
            SchemaID.TRIGGER, 
            SchemaID.ON_COMPLETE, 
            SchemaID.ON_ERROR,
            SchemaID.ON_SUCCESS 
        ],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "on_success": {
        "top_level_key": True,
        "id": SchemaID.ON_SUCCESS,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": False}, 
            SchemaID.SERVICE: {"mandatory": False}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False},
            SchemaID.OPERATIONS: {"mandatory": False},
            SchemaID.ON_ERROR: {"mandatory": False},
            SchemaID.ON_COMPLETE: {"mandatory": False},
            SchemaID.ON_SUCCESS: {"mandatory": False},
            SchemaID.ACTION: {"mandatory": False},
            SchemaID.IF: {"mandatory": False},
            SchemaID.ELSE: {"mandatory": False},
            SchemaID.ELIF: {"mandatory": False},
            SchemaID.USE: {"mandatory": False}

        },
        "dependency": {},
        "validator": validators_V2.on_group_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.on_success_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [
            SchemaID.PIPELINE, 
            SchemaID.TRIGGER, 
            SchemaID.ON_COMPLETE, 
            SchemaID.ON_ERROR,
            SchemaID.ON_SUCCESS
        ],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "on_error": {
        "top_level_key": True,
        "id": SchemaID.ON_ERROR,
        "type": [list, dict],
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": False}, 
            SchemaID.SERVICE: {"mandatory": False}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False},
            SchemaID.OPERATIONS: {"mandatory": False},
            SchemaID.ON_ERROR: {"mandatory": False},
            SchemaID.ON_COMPLETE: {"mandatory": False},
            SchemaID.ON_SUCCESS: {"mandatory": False},
            SchemaID.ACTION: {"mandatory": False},
            SchemaID.IF: {"mandatory": False},
            SchemaID.ELSE: {"mandatory": False},
            SchemaID.ELIF: {"mandatory": False},
            SchemaID.USE: {"mandatory": False}

        },
        "dependency": {},
        "validator": validators_V2.on_group_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.on_error_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [
            SchemaID.PIPELINE, 
            SchemaID.TRIGGER,
            SchemaID.ON_COMPLETE, 
            SchemaID.ON_ERROR,
            SchemaID.ON_SUCCESS
        ],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False   
    },
    "on_call": {
        "top_level_key": False,
        "id": SchemaID.ON_CALL,
        "type": bool,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": {},
        "interpreter": {},
        "executor": {},
        "processor": {},
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "import": {
        "top_level_key": True,
        "id": SchemaID.IMPORT,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.FROM: {"mandatory": True}, 
            SchemaID.AS: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.import_validator,
        "interpreter": interpreter.import_interpreter,
        "executor": {},
        "processor": processor.import_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },

    "from": {
        "top_level_key": True,
        "id": SchemaID.FROM,
        "type": str,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.from_validator,
        "interpreter": {},
        "executor": {},
        "processor": {},
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.IMPORT],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "as": {
        "top_level_key": True,
        "id": SchemaID.AS,
        "type": str,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.validate_id,
        "interpreter": {},
        "executor": {},
        "processor": {},
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.IMPORT],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": False
    },
    "use": {
        "top_level_key": True,
        "id": SchemaID.USE,
        "type": str,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {},
        "dependency": {},
        "validator": validators_V2.use_validator,
        "interpreter": interpreter.use_interpreter,
        "executor": {},
        "processor": {},
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [
            SchemaID.PIPELINE, 
            SchemaID.TRIGGER, 
            SchemaID.ON_COMPLETE,
            SchemaID.ON_ERROR,
            SchemaID.ON_SUCCESS
        ],
        "prefix": {},
        "partial_mandatory": [],
        "is_service_manager": True
    }
}