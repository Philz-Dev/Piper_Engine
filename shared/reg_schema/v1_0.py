from enum import IntEnum
import interpreter
from universal_dispatcher_v2.core import dispatcher
import validators_V2
import executor, processor
from .schemaid import SchemaID

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
            SchemaID.VERSION: {"mandatory": True}
        },
        "dependency": {},
        "validator": validators_V2.main_validator,
        "interpreter": interpreter,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {}
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
                "top_level_parent": [SchemaID.PIPELINE]
            },
            "workflow": {
                "dependency": {SchemaID.INPUT: {"mandatory": False, "support": False}},
                "top_level_parent": [SchemaID.PIPELINE]
            },

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
        "prefix": {}
    },
    "pipeline": {
        "top_level_key": True,
        "id": SchemaID.PIPELINE,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": True}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.pipeline_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {}
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
        "prefix": {}
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
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": [],
        "processor": [],
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [SchemaID.PIPELINE],
        "prefix": {}
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
        "prefix": {}
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
        "prefix": {}
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
        "prefix": {}
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
        "prefix": {}
    },
    "action": {
        "top_level_key": False,
        "id": SchemaID.ACTION,
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
        "prefix": {}
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
        "top_level_parent": [SchemaID.PIPELINE, SchemaID.TRIGGER],
        "parent": [SchemaID.CONDITION],
        "prefix": {}
    },
    "trigger": {
        "top_level_key": True,
        "id": SchemaID.TRIGGER,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": True}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.CONDITION: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": [],
        "processor": processor.trigger_processor,
        "address_book": "apps",
        "file_ext": "json",
        "top_level_parent": [],
        "parent": [],
        "prefix": {}
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
        "prefix": {}
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
        "prefix": {}
    },
    "on_complete": {
        "top_level_key": True,
        "id": SchemaID. ON_COMPLETE,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": True}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.on_complete_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {}
    },
    "on_success": {
        "top_level_key": True,
        "id": SchemaID.ON_SUCCESS,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": True}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.on_success_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {}
    },
    "on_error": {
        "top_level_key": True,
        "id": SchemaID.ON_ERROR,
        "type": list,
        "weight": 10,
        "is_merger": False,
        "allowed_keys": {
            SchemaID.ID: {"mandatory": True}, 
            SchemaID.SERVICE: {"mandatory": True}, 
            SchemaID.INPUT: {"mandatory": False},
            SchemaID.STEPS: {"mandatory": False}, 
            SchemaID.CONDITION: {"mandatory": False}
        },
        "dependency": {},
        "validator": validators_V2.core_validator,
        "interpreter": interpreter.core_interpreter,
        "executor": {},
        "processor": processor.on_error_processor,
        "address_book": None,
        "file_ext": None,
        "top_level_parent": [],
        "prefix": {}
    }
}