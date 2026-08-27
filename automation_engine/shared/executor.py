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

    service_info = _cont.get("service", {})
    prefix = service_info.get("type")
    
    if args := _cont.get("execution"):
        args["_context_data"] = _context_data
        args["_app_name"] = service_info.get("app")
        
    engine_internal = service_info.get("engine_internal")
    exe = _registry.prefix_executor(key="service", prefix_name=prefix) if prefix else None

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




DOCKER_CLIENT = docker.from_env()

# Canonical runtime name -> aliases accepted from pipeline manifests
RUNTIME_ALIASES = {
    "python": "python",
    "py": "python",
    "javascript": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
}

# Canonical runtime -> warm runner container name (must match the
# `piper-runner-<language>` naming convention in watcher.py's sync_language_runners)
# and the in-container entrypoint used to invoke the single-shot runner script.
RUNTIME_CONFIG = {
    "python": {
        "container": "piper-runner-python",
        "entrypoint": ["python3", "/app/runner-python/runner.py"],
    },
    "javascript": {
        "container": "piper-runner-javascript",
        "entrypoint": ["node", "/app/runner-node/runner.js"],
    },
}

RESULT_PATTERN = re.compile(r"PIPER_RESULT_START\n(.*?)\nPIPER_RESULT_END", re.DOTALL)


async def execute_in_sandbox(
    _prefix: str,
    _engine_internal: Dict,
    _context_data: Dict,
    runtime: str,
    timeout: int = 30,
    **_kwargs,
):
    system_items = _engine_internal.get(_prefix, {})
    file_path = system_items.get("_file_path")
    if not file_path:
        return {"error": "No script file_path found in engine_internal"}

    canonical_runtime = RUNTIME_ALIASES.get(runtime.lower())
    if not canonical_runtime:
        return {"error": f"Unsupported runtime specified: {runtime}"}

    config = RUNTIME_CONFIG[canonical_runtime]

    # Runner containers are kept warm by watcher.py's sync_language_runners();
    # if one isn't up yet (still starting, or capacity-limited), fail clearly
    # rather than hanging on a container that doesn't exist.
    try:
        container = await asyncio.to_thread(DOCKER_CLIENT.containers.get, config["container"])
    except docker.errors.NotFound:
        return {
            "error": f"No warm runner container found for runtime '{runtime}' "
                     f"({config['container']}). It may still be starting up."
        }

    env = {
        "PIPER_CONTEXT": json.dumps(_context_data),
        "PYTHONUNBUFFERED": "1",
    }

    # 'timeout' is the coreutils binary run *inside* the container - this kills a
    # hung/looping user script at the OS level, since we no longer have the
    # subprocess.run(timeout=...) guard that worker_daemon.py used to provide.
    cmd = ["timeout", str(timeout), *config["entrypoint"], file_path]

    try:
        exit_code, output = await asyncio.to_thread(
            container.exec_run, cmd, environment=env, demux=False
        )
    except Exception as e:
        return {"error": f"docker exec failed: {str(e)}"}

    raw_output = output.decode("utf-8", errors="replace") if output else ""

    if exit_code == 124:
        return {"error": f"Sandbox execution timed out after {timeout}s"}

    match = RESULT_PATTERN.search(raw_output)
    if not match:
        return {
            "error": "No result markers found in sandbox output",
            "raw": raw_output,
            "exit_code": exit_code,
        }

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"error": "Failed to parse sandbox result JSON", "raw": match.group(1)}

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