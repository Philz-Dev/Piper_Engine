import subprocess
import asyncio # Changed from time for better async handling
import os
os.environ["COMPOSE_CONVERT_WINDOWS_PATHS"] = "1"
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
from shared.tools import crawler, retrieve_file, replace_place_value, inspect_function, get_registry_package, generate_random_token
# from shared.validators import ACTION_MAP
from shared.encryption_manager import get_encryption_key
from datetime import datetime
import copy
from shared.database_manager import ContextDB
import re
import shared.helpers as helpers
from typing import Dict
import time
from shared.pipeline_executor import PipelineExecutor
from shared.iterator_executor import IteratorManager
import docker
import json
import os
import time
from typing import Dict
import redis
from shared.aggregator_executor import AggregatorManager
from shared.bin_executor import BinManager

r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)


DB = ContextDB()
       
async def service_executor(_registry, _cont: Dict, _crypto_engine, _context_data, _client_name, _task_id, **_kwargs):
    prefix = _cont.get("prefix")
    
    if args := _cont.get("execution"):
        args["_context_data"] = _context_data
        
    engine_internal = _cont.get("engine_internal")
    exe = _registry.sub_executor_map.get(prefix) if prefix else None
    
    if exe:
        # Check if the target executor is an async function
        if asyncio.iscoroutinefunction(exe):
            return await exe(
                **_cont["execution"], 
                _crypto_engine=_crypto_engine, 
                _registry=_registry, 
                _client_name=_client_name, 
                _task_id=_task_id, 
                _engine_internal=engine_internal, 
                _prefix=prefix,
                _steps=_cont.get("steps")
            )
        else:
            return exe(
                **_cont["execution"], 
                _crypto_engine=_crypto_engine, 
                _registry=_registry, 
                _client_name=_client_name, 
                _task_id=_task_id, 
                _engine_internal=engine_internal, 
                _prefix=prefix,
                _steps=_cont.get("steps")
            )
    
    # Safely returns a plain dictionary back to an awaiting pipeline caller
    return {}


def schedule_executor(interval: str, **_kwargs):
    """
        A function placeholder for schedule sub executor
    """
    pass


import asyncio
import json
import os
import time
from typing import Dict
import redis
from shared.tools import generate_random_token

# Assume 'r' is your initialized redis client
# r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)




async def execute_in_sandbox(
    _prefix: str,
    _engine_internal: Dict,
    _context_data: Dict,
    runtime: str,
    timeout: int = 30,
    **_kwargs,
):
    client_name = os.getenv("CLIENT_NAME", "unknown")
    dsl_name = os.getenv("DSL_NAME", "default")
    uid = generate_random_token()

    system_items = _engine_internal.get(_prefix, {})
    file_path = system_items.get("_file_path")

    # Map runtime to language-specific Redis streams for the 24/7 warm daemons
    STREAM_MAPPING = {
        "python": "piper_python_stream",
        "py": "piper_python_stream",
        "nodejs": "piper_node_stream",
        "node": "piper_node_stream",
        "javascript": "piper_node_stream",
    }
    
    normalized_runtime = runtime.lower()
    target_stream = STREAM_MAPPING.get(normalized_runtime)
    if not target_stream:
        return {"error": f"Unsupported runtime specified: {runtime}"}

    channel_name = f"sandbox:channel:{uid}"
    task_payload = {
        "run_id": f"sandbox_{uid}",
        "file_path": file_path,
        "runtime": normalized_runtime,
        "context": _context_data,
        "client_name": client_name,
        "dsl_name": dsl_name,
        "timeout": timeout,
        "response_channel": channel_name,
    }

    # Subscribe to the unique return channel BEFORE pushing the job to the stream
    pubsub = r.pubsub()
    pubsub.subscribe(channel_name)

    try:
        # Push execution request to the dedicated language stream consumed by the warm daemon
        r.xadd(target_stream, {"payload": json.dumps(task_payload)})

        start_time = time.time()
        while time.time() - start_time < timeout:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if message and message.get("data"):
                raw_res = message["data"]
                try:
                    return json.loads(raw_res)
                except json.JSONDecodeError:
                    return {"error": "Failed to parse sandbox result JSON", "raw": raw_res}

            await asyncio.sleep(0.01)

        return {
            "error": f"Sandbox execution timed out after {timeout}s via Redis Pub/Sub"
        }

    finally:
        # Clean up channel listeners safely
        pubsub.unsubscribe(channel_name)
        pubsub.close()

async def iterator(_prefix: str, mode: str, filename: str, _steps: list, _client_id: str, _crypto_engine,  _task_id: str, _engine_internal: Dict, _context_data: Dict, runtime: str, timeout: int=30, **_kwargs):
    iterator = IteratorManager()
    exe = PipelineExecutor() # Use your existing class
    
    for row in iterator.iterate(_client_id, _task_id, filename):
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        run_id = f"run_{uuid.uuid4().hex[:8]}"

        DB.save_context(
            client_id=_client_id, 
            task_id=_task_id, 
            context_data={"row": row, "_received_at": datetime.now().isoformat()}, 
            event_id=event_id
        )
        
        if mode == "async":
            # --- REDIS PATH (Your Controller picks this up) ---
            task_payload = {
                "run_id": f"run_{uuid.uuid4().hex[:8]}",
                "task_id": _task_id,
                "client_id": _client_id,
                "pipeline": _steps,
                "event_id": event_id,
                "from_trigger": True
            }
            r.rpush("task_queue", json.dumps(task_payload))
            
        else:
            # --- SYNC PATH (Direct Execution) ---
            # Call your run_executor exactly as the worker does
            await exe.run_executor(
                manifest=_steps,
                event_id=event_id,
                run_id=f"run_{uuid.uuid4().hex[:8]}",
                task_id=_task_id,
                client_id=_client_id,
                from_trigger=True,
                _crypto_engine=_crypto_engine
            )
            
    return {"status": "success"}


async def bin_executor(_prefix: str, url: str, filename: str, _steps: list, _client_id: str, _crypto_engine,  _task_id: str, _engine_internal: Dict, _context_data: Dict, runtime: str, timeout: int=30, **_kwargs):
    
    manager = BinManager()
    try:
        path = await manager.download_stream(url, _client_id, _task_id, filename)
        return {"status": "success", "file_path": path}
    except Exception as e:
        #logger.error(f"❌ Bin Download Failed: {str(e)}")
        return {"status": "error", "message": str(e)}


async def aggregator_executor(_prefix: str, mode: str, filename: str, _steps: list, _client_id: str, _crypto_engine,  _task_id: str, _engine_internal: Dict, _context_data: Dict, runtime: str, timeout: int=30, **_kwargs):

    """
    Collects results from individual workers and merges them.
    """
    # The input is usually a single result from a child task
    
    new_data = _steps.get("data")
    
    manager = AggregatorManager()
    path = manager.append_data(_client_id, _task_id, new_data)
    
    #logger.info(f"💾 Aggregated result to {path}")
    return {"status": "success", "file_path": path}


        

        