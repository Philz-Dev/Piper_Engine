import subprocess
import asyncio # Changed from time for better async handling
import os
import json
from shared.universal_dispatcher.core import dispatcher
from shared.encryption_manager import get_encryption_key
from shared.database_manager import ContextDB
import uuid
from datetime import datetime
from dateutil.relativedelta import relativedelta
import ast
import re
from shared.unpacked_data import UnZip
from shared.tools import crawler, retrieve_file, replace_place_value, inspect_function
# from shared.validators import ACTION_MAP
from shared.encryption_manager import get_encryption_key
from datetime import datetime
import copy
from shared.database_manager import ContextDB
import re
import shared.helpers as helpers

DB = ContextDB()

async def processor(_cont, _password, _client_name, _registry):
    # --- Setting the Floor ---
    # 1. Resolve Task ID (Blind to pipeline content)
    existing_record = DB.get_pipeline_by_client(_client_name)
    if existing_record:
        task_id = existing_record["task_id"]
    else:
        task_id = str(uuid.uuid4())
    
    # 2. Setup Crypto
    _crypto_engine = get_encryption_key(_password)

    # --- Agnostic Orchestration ---
    
    for top_level_key, value in _cont.items():
        #print(top_level_key)
        # Ask registry who handles this key
        exe_func = _registry.processor_map.get(top_level_key)
        if not exe_func:
            continue
            
        # Call blindly - passing the "floor" variables
        await exe_func(
            _cont=value, 
            _client_name=_client_name, 
            _crypto_engine=_crypto_engine, 
            _task_id=task_id,
            _registry=_registry,
            _key=top_level_key
        )

async def pipeline_processor(_cont, _task_id, _client_name, _key, **kwargs):
    """
    Specifically handles the 'Pipeline' top-level key.
    The executor passed the stable task_id, so we just upsert.
    """
    print("saving the task to db")
    if _cont:
        # upsert_pipeline handles the DB logic (Insert new or Update existing)
        DB.upsert_pipeline(_client_name, _task_id, _cont)
        print(f"💾 Pipeline State Synchronized for {_client_name} (Task: {_task_id})")
    
async def trigger_processor(_cont, _task_id, _client_name, _key, _crypto_engine, _registry, **_kwargs):
    data = {
        "_cont": _cont, 
        "crypto_engine":_crypto_engine,
        "task_id": _task_id,
        "client_name": _client_name
    }
    for n, step in enumerate(_cont):
        service_type =  step.get("service_type")
        exe_func = _registry.sub_processor_map.get(service_type)
        if exe_func:
            # 2. Extract the dynamic arguments dictionary
            dynamic_args = step.get("args", {})
            
            # 3. Call with ** unpacking
            # This turns {"interval": "30 sec", "retry": True} into (interval="30 sec", retry=True)
            await exe_func(
                **dynamic_args,        # Dynamic DSL arguments
                _client_id=_client_name, # System arguments
                _task_id=_task_id,
                _registry=_registry
            )
        print(f"_cont:    {_cont[n]}")

async def start_webhook(_cont, _crypto_engine, _client_name, _task_id, **kwargs):

    # PHASE 2: Registration
    print("--- PHASE 2: Registering URL with Provider ---")
    await dispatcher(_args=_cont, _crypto_engine=_crypto_engine, _client_name=_client_name, _task_id=_task_id)

    print("\n--- System Fully Operational ---")

async def schedule(interval: str, _client_id: str, _task_id: str, **_kwargs):
    # Mapping your input strings to dateutil keywords
    # Note: relative delta uses plural (seconds, minutes, etc.)
    service_map = {
        "sec": "seconds",
        "min": "minutes",
        "h": "hours",
        "d": "days",
        "m": "months",
        "y": "years"
    }
    
     # e.g., "2 month"
    value_str, interval_str = interval.split(" ")
    value = int(value_str)

    # Calculate precise future date
    # relativedelta handles the 'calendar math' (e.g., Feb 28 + 1 month = March 28)
    delta_kwargs = {service_map[interval_str]: value}
    run_at = datetime.now() + relativedelta(**delta_kwargs)

    # Save to your DB (Assuming your DB.schedule_task takes these params)
    # We pass the calculated 'run_at' datetime object
    DB.schedule_task(_client_id, _task_id, run_at, value, interval)
    
    print(f"⏰ Task {_task_id} scheduled for {run_at} (In {value} {interval_str})")


async def version_processor(_cont, _task_id, _client_name, **_kwargs):
    # Get the version from the manifest
    version = _cont.values()
    
    # Save it to its OWN table
    DB.save_version(_client_name, version)
    
    print(f"📦 Version '{version}' locked in version_registry for {_client_name}")