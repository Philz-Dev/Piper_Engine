import asyncio
import yaml
import json
import httpx # Async HTTP client
import aiofiles # Async file reading
from dev_utils.registry import TYPE_MAP, WEIGHT_MAP, ACTION_MAP, SECTION_MAP, ALLOW_KEY_MAP, schema_reg, DEPENDENCY_MAP, TASK_MANAGER_MAP, A_SERVICE_MANAGER_MAP, ADDRESS_MAP, FILE_EXT_MAP, CONDITION_MAP, RECURSION_MAP, ID_MAP, TRIGGER_MAP
import yaml
from dev_utils.unpacked_data import UnZip
from dev_utils.task_managers import missing_field, validate_type, all_config_keys
from dev_utils.apps.list_of_app_keywords import key_list

class Interpreter:
    def __init__(self):
        self.progress: dict = {}
        self.task_manifest = {}
        self.unpacked_data = []
        self.unzip = UnZip()
        self.config_keys = all_config_keys(func_list=A_SERVICE_MANAGER_MAP, handler=ACTION_MAP)
    
    async def run_interpreter(self, crypto_engine, file: yaml, name: str):
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
        """Validates value against TYPE_MAP if a key is provided."""
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
                raise SyntaxError(f" {missing} was not inluded")