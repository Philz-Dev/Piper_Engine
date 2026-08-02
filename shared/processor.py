import subprocess
import asyncio # Changed from time for better async handling
import os
import json
from shared.universal_dispatcher_v2.core import dispatcher
from shared.encryption_manager import get_encryption_key
from shared.database_manager import ContextDB
import uuid
from dateutil.relativedelta import relativedelta
import ast
import re
from shared.unpacked_data import UnZip
from shared.tools import crawler, retrieve_file, replace_place_value, inspect_function, generate_random_token
# from shared.validators import ACTION_MAP
from shared.encryption_manager import get_encryption_key
from datetime import datetime
import copy
from shared.database_manager import ContextDB
import re
import shared.helpers as helpers
from typing import Dict
from shared.redis_queuer import reddis_now

DB = ContextDB()

async def processor(_cont, _password, _client_name, _registry, _dsl_file_name):
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
            _key=top_level_key,
            _dsl_file_name=_dsl_file_name
        )

async def on_complete_processor(_cont, _task_id, _client_name, _key, _dsl_file_name, **kwargs):
    """Handles persistence for the 'on_complete' lifecycle block."""
    print("💾 Saving 'on_complete' block to pipeline storage...")
    if _cont:
        DB.upsert_on_complete(_client_name, _task_id, _cont, dsl_name=_dsl_file_name)
        print(f"✨ 'on_complete' state synchronized for {_client_name} (Task: {_task_id})")

async def on_error_processor(_cont, _task_id, _client_name, _key, _dsl_file_name, **kwargs):
    """Handles persistence for the 'on_error' lifecycle block."""
    print("💾 Saving 'on_error' block to pipeline storage...")
    if _cont:
        DB.upsert_on_error(_client_name, _task_id, _cont, dsl_name=_dsl_file_name)
        print(f"🚨 'on_error' state synchronized for {_client_name} (Task: {_task_id})")

async def on_success_processor(_cont, _task_id, _client_name, _key, _dsl_file_name, **kwargs):
    """Handles persistence for the 'on_success' lifecycle block."""
    print("💾 Saving 'on_success' block to pipeline storage...")
    if _cont:
        DB.upsert_on_success(_client_name, _task_id, _cont, dsl_name=_dsl_file_name)
        print(f"🌟 'on_success' state synchronized for {_client_name} (Task: {_task_id})")

async def pipeline_processor(_cont, _task_id, _client_name, _key, _dsl_file_name, **kwargs):
    """
    Specifically handles the 'Pipeline' top-level key.
    The executor passed the stable task_id, so we just upsert.
    """

    print("saving the task to db")
    if _cont:
        # upsert_pipeline handles the DB logic (Insert new or Update existing)
        DB.upsert_pipeline(_client_name, _task_id, _cont, dsl_name=_dsl_file_name)
        print(f"💾 Pipeline State Synchronized for {_client_name} (Task: {_task_id})")
    
async def trigger_processor(_cont, _task_id, _client_name, _key, _crypto_engine, _registry, **_kwargs):
    """data = {
        "_cont": _cont, 
        "crypto_engine":_crypto_engine,
        "task_id": _task_id,
        "client_name": _client_name
    }"""

    _cont = _cont.get("instructions") or _cont

    for n, step in enumerate(_cont):
        service = step.get("service")
        service_type =  service.get("type")
        exe_func = _registry.prefix_processor(service_type)
        if exe_func:
            # 2. Extract the dynamic arguments dictionary
            dynamic_args = step.get("execution", {})
            
            # 3. Call with ** unpacking
            # This turns {"interval": "30 sec", "retry": True} into (interval="30 sec", retry=True)
            await exe_func(
                **dynamic_args,        # Dynamic DSL arguments
                _client_id=_client_name, # System arguments
                _task_id=_task_id,
                _registry=_registry,
                _cont=step,
                _step=step,
                _crypto_engine=_crypto_engine
            )

async def start_webhook(_cont, _crypto_engine, _client_id, _task_id, _step, **kwargs):

    # PHASE 2: Registration
    print("--- PHASE 2: Registering URL with Provider ---")
    webhook_token = generate_random_token()
    args = _cont.get("args")
    app_name = _cont.get("app_name")
    id = _cont.get("id")
    await dispatcher(
        **args, 
        _crypto_engine=_crypto_engine, 
        _client_name=_client_id, 
        _task_id=_task_id, 
        _app_name=app_name, 
        _webhook_token=webhook_token
        )
    
    DB.save_webhook_registration(
        token=webhook_token,
        client_id=_client_id,
        task_id=_task_id,
        app_name=app_name,
        webhook_id=id
    )
    print(f"🔑 Webhook token registered and saved for {app_name}")
    
    prefix = _step.get("service_type")
    if exe := _cont.get("engine_internal"):
        if cleanup_schema := exe.get(prefix):
            DB.save_cleanup_schema(
                        client_id=_client_id, 
                        task_id=_task_id, 
                        schema=cleanup_schema
                    )
            print(f"🛡️ Cleanup schema persisted for task: {_task_id}")
    print("\n--- System Fully Operational ---")

async def schedule(interval: str, _client_id: str, _task_id: str, _step: Dict, **_kwargs):
    # 1. Mapping for local calculation

    service_map = {
        "sec": "seconds",
        "min": "minutes",
        "h": "hours",
        "d": "days",
        "m": "months",
        "y": "years"
    }
    
    try:
        if _step.get("action") == "now":
            print(f"⚡ Immediate execution requested for Task {_task_id}")
            # Logic: Either run the task logic here, or set run_at to now()
            run_at = datetime.now()
            reddis_now(_client_id=_client_id, _task_id=_task_id)
            
        else:
            # e.g., "2 m" or "30 sec"
            value_str, interval_str = interval.split(" ")
            value = int(value_str)
            id = _step.get("id")
            
            # Ensure the unit exists in our map
            if interval_str not in service_map:
                print(f"❌ Error: Unknown interval unit '{interval_str}'")
                return

            # 2. Calculate the VERY FIRST run date
            delta_kwargs = {service_map[interval_str]: value}
            run_at = datetime.now() + relativedelta(**delta_kwargs)

        # 3. Save to DB
        # IMPORTANT: We save the 'interval_str' (e.g., "m") so check_schedules 
        # can look it up in its own service_map later.
        DB.schedule_task(
            client_id=_client_id, 
            task_id=_task_id, 
            run_at=run_at, 
            value=value,
            step_id=id, 
            intervals=service_map[interval_str]  # This goes into the 'intervals' column
        )
        
        print(f"⏰ Task {_task_id} scheduled for {run_at} (Every {value} {interval_str})")
        
    except ValueError:
        print(f"❌ Error: Invalid interval format '{interval}'. Expected 'value unit' (e.g., '10 min')")
    except Exception as e:
        print(f"❌ Schedule Processor Crash: {e}")

async def schedule_v2(interval: str, _client_id: str, _task_id: str, **_kwargs):
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
    # If _cont is {'version': '1.0'}, extract the value correctly
    # Use next(iter(...)) to safely get the first value if it's a dict
    version = next(iter(_cont.values())) if isinstance(_cont, dict) else str(_cont)
    
    DB.save_version(_client_name, version)
    print(f"📦 Version '{version}' locked in version_registry for {_client_name}")