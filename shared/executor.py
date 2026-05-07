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
from shared.tools import crawler, retrieve_file, replace_place_value, inspect_function, get_registry_package
# from shared.validators import ACTION_MAP
from shared.encryption_manager import get_encryption_key
from datetime import datetime
import copy
from shared.database_manager import ContextDB
import re
import shared.helpers as helpers
from typing import Dict

DB = ContextDB()

class Executor:
    def __init__(self):
        self.context_manager = {}
        self.db = ContextDB()

class PipelineExecutor:
    def __init__(self):
        self.context_manager = {}
        # 1. Initialize the Database connection
        self.db = ContextDB()
        

    async def run_executor(
            _registry, self, manifest, run_id, task_id, client_id, from_trigger=False, 
            _crypto_engine=None, is_schedule: bool=False):   
        sample_m = next((item for item in manifest if item), None)
        
        # 2. Get client info and task ID for DB lookup
        if sample_m:
            context_file = self.db.get_context(client_id, task_id) or {}
        
        for m in manifest:
            if not m or not m.get("id"): continue
            
            # Variable replacement logic remains the same (it just uses the data we fetched)
            m = self.replace_value_from_context(package=m, context_file=context_file)
            m  = self.resolve_helpers_v2(dsl_string=m)
            
            if "condition" in m:
                if not self.eval_condition(condition=m["condition"]):
                    continue

            package = await _registry.executor_map.get(m["service_manager"])(_registry=_registry, _cont=m, _crypto_engine=_crypto_engine, _context_data=context_file)
            if not package or "error" in str(package).lower():
                return
            
            self.context_manager[m["id"]] = package
            
            if "steps" in m:
                await self.run_executor(_registry=_registry, manifest=m["steps"], _crypto_engine=_crypto_engine, from_trigger=from_trigger)
        
        # 3. REPLACED: write_to_context_manager logic
        # Instead of writing to a file path, we send it to the DB
        #if sample_m:
        self.sync_to_db(
            client_id=client_id, 
            task_id=task_id, 
            package=self.context_manager, 
            from_trigger=from_trigger
        )
        if is_schedule:
            self.db.reschedule_after_completion(client_id, task_id)

    def resolve_helpers_v2(self, package):
        # 1. Use your existing crawler to find all strings in the step
        # (Re-using the same pattern logic but looking for function calls)
        func_pattern = r"(\w+)\(([^()]*)\)"
        
        # We use the same crawler logic you used for variables
        found_items = crawler(content_to_crawl=package, patterns=func_pattern)
        
        if not found_items:
            return package

        for key, original_value in found_items["matched_items"].items():
            if isinstance(original_value, str):
                resolved_val = original_value
                # Perform the recursive replacement loop on the specific string
                while True:
                    match = re.search(func_pattern, resolved_val)
                    if not match: break
                    
                    func_name = match.group(1)
                    args = [arg.strip() for arg in match.group(2).split(',') if arg.strip()]
                    
                    if hasattr(helpers, func_name):
                        func = getattr(helpers, func_name)
                        result = func(*args)
                        start, end = match.span()
                        dsl_string = dsl_string[:start] + str(result) + dsl_string[end:]
                    else:
                        resolved_val = f"ERROR: {func_name} not found"
                        break
                
                # Put the resolved string back into the manifest
                package = replace_place_value(
                    key_path=found_items["key_path"], 
                    key=key,
                    content_to_modify=package, 
                    value=resolved_val
                )
        return package
        
    def sync_to_db(self, client_id, task_id, package, from_trigger):
        """Replaces write_to_context_manager with Database Logic"""
        # Fetch current state from DB
        current_data = self.db.get_context(client_id, task_id) or {}
        
        if not from_trigger:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_data[now] = package
        else:
            # Update the last execution entry
            if current_data:
                last_key = list(current_data.keys())[-1]
                current_data[last_key].update(package)
            else:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_data[now] = package

        # 4. Atomic Save to Postgres
        self.db.save_context(client_id, task_id, current_data)
        print(f"📊 DB Sync Complete for {client_id}")

    def write_to_context_manager(self, package, path, from_trigger):
        context_file = {}
        
        # Load existing data safely
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                with open(path, "r") as f:
                    context_file = json.load(f)
            except json.JSONDecodeError:
                context_file = {}
        if not from_trigger:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            context_file[now] = package
        else:
            last_execution_key = list(context_file.keys())[-1]
            context_file[last_execution_key].update(package)

        # Overwrite with "w" to keep JSON structure valid
        with open(path, "w") as f:
            json.dump(context_file, f, indent=4)

    def resolve_helpers(self, dsl_string):
        """
        Example input: "upper(lower({{user_name}}))"
        Context: {"user_name": "John"}
        """

        # 2. Recursive Function Evaluation (Inside-Out)
        # This regex finds a word followed by parentheses that DON'T contain other parentheses
        # Match group 1: function name, group 2: arguments
        innermost_regex = r"(\w+)\(([^()]*)\)"

        while True:
            match = re.search(innermost_regex, dsl_string)
            if not match:
                break  # No more functions to resolve

            func_name = match.group(1)
            # Split arguments by comma and strip whitespace
            args = [arg.strip() for arg in match.group(2).split(',') if arg.strip()]

            # 3. Dynamic Execution
            if hasattr(helpers, func_name):
                func = getattr(helpers, func_name)
                try:
                    # Execute and get result
                    result = func(*args)
                    # Replace the entire "func(args)" block with the result
                    # We use a safe replacement to avoid regex special character issues
                    start, end = match.span()
                    resolved_string = resolved_string[:start] + str(result) + resolved_string[end:]
                except Exception as e:
                    return f"Execution Error in {func_name}: {str(e)}"
            else:
                return f"Error: Function '{func_name}' not found."

        return resolved_string

    def replace_value_from_context(self, package, context_file):
        # NEW PATTERN: Non-greedy, supports $, dots, and hyphens
        pattern = r"\{\{(?P<variable>[\w\.\-\$]+)\}\}"
        
        # 1. Establish Historical Record (Latest from file)
        history_record = {}
        if context_file:
            try:
                # Optimized way to get the last entry
                last_key = next(reversed(context_file))
                history_record = context_file[last_key]
            except (StopIteration, KeyError):
                pass

        # 2. Merge Truth Sources: Memory overrides History
        # We merge them so we can do a single lookup pass
        active_data = {**history_record, **self.context_manager}

        # 3. Define the Callback Replacer
        def replacer(match):
            path = match.group("variable")
            parts = path.split(".")
            
            # Use your existing get_nested_value helper
            val = self.get_nested_value(active_data, parts)
            
            # Return the value as a string, or keep the tag if not found for debugging
            return str(val) if val is not None else match.group(0)

        # 4. Crawl the manifest
        found_items = crawler(content_to_crawl=package, patterns=pattern)
        
        if found_items:
            for key, original_value in found_items["matched_items"].items():
                # We only perform regex substitution on strings
                if isinstance(original_value, str):
                    # This handles: "Lead {{name}} from {{source}}" in one go
                    final_value = re.sub(pattern, replacer, original_value)

                    package = replace_place_value(
                        key_path=found_items["key_path"], 
                        key=key,
                        content_to_modify=package, 
                        value=final_value
                    )
        return package

    def get_nested_value(self, data, parts):
        """Helper to navigate dicts/lists and return None if path fails"""
        temp = data
        try:
            for k in parts:
                if isinstance(temp, list):
                    # Handle list indexing
                    k = int(k) if k.isdigit() else 0
                    temp = temp[k] if k < len(temp) else None
                elif isinstance(temp, dict):
                    temp = temp.get(k)
                else:
                    return None
                
                if temp is None: 
                    return None
            return temp
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    
    async def call_run_executor(self, _cont, password, run_id, task_id, client_id, from_trigger: bool=False):
        # Reset live memory for each unique trigger run
        version = DB.get_version(client_id)
        current_registry = get_registry_package(version)
        registry = current_registry[0]

        self.context_manager = {}
        _crypto_engine = get_encryption_key(password=password)
        
        # CRITICAL: Deep copy ensures Run 1 doesn't mutate Global RAM for Run 2
        fresh_manifest_container = copy.deepcopy(_cont)
        
        # Extract the list of steps
        if isinstance(fresh_manifest_container, dict) and "Pipeline" in fresh_manifest_container:
            manifest = fresh_manifest_container["Pipeline"]
        else:
            manifest = fresh_manifest_container

        await self.run_executor(
            _registry=registry,
            manifest=manifest, 
            _crypto_engine=_crypto_engine, 
            from_trigger=from_trigger,
            run_id=run_id, client_id=client_id, task_id=task_id
        )
    
    """async def call_run_executor(self, _cont, password, action=None, from_trigger: bool=False):
        self.context_manager = {}
        _crypto_engine = get_encryption_key(password=password)
        fresh_manifest = copy.deepcopy(_cont)
        manifest = fresh_manifest["Pipeline"] if type(fresh_manifest) is dict and fresh_manifest.get("Pipeline") else fresh_manifest
        await self.run_executor(manifest=manifest, action=action, _crypto_engine=_crypto_engine, from_trigger=from_trigger)"""
    
    def eval_condition(self, condition: str):
        if not self.is_safe_condition(condition_string=condition):
           raise SyntaxError(f"{condition}")
        #condition_str = "ops_count < 100" # From DSL
        #context = {"ops_count": 45}       # From your internal metadata
        if "MISSING_KEY_" in str(condition) or "PATH_NOT_FOUND_" in str(condition):
            print(f"⚠️ Data Dependency Missing: {condition}. Skipping step.")
            print(f"⚠️ Skipping condition evaluation due to missing data: {condition}")
            return False
        print(f"condition: {condition}")
        # Pass the context so 'ops_count' is recognized
        result =  eval(condition)
        print(f"result: {result}")
        return result
    
    def is_safe_condition(self, condition_string):
        try:
            tree = ast.parse(condition_string, mode='eval')
            
            # Walk through every part of the user's code
            for node in ast.walk(tree):
                # Block anything that isn't a simple name, constant, or operator
                allowed_nodes = (
                    ast.Expression, ast.Compare, ast.BinOp, 
                    ast.BoolOp, ast.UnaryOp, ast.Name, 
                    ast.Constant, ast.Load
                )
                if not isinstance(node, allowed_nodes):
                    print(f"Security Violation: {type(node).__name__} is not allowed.")
                    return False
                return True
        except SyntaxError:
            return False
        
    def eval_user_string(self, text):
        # This looks for anything between {{ and }}
        # and captures the part after the dot
        match = re.search(r"\{\{(\w+)\.(\w+)\}\}", text)
        if match:
            return match.group(1), match.group(2)
        
def service_executor(_registry, _cont: Dict, _crypto_engine, _context_data):
    prefix = _cont.get("prefix")
    if args :=_cont.get("args"):
        args["context_data"] = _context_data
    engine_internal = _cont.get("engine_internal")
    exe = _registry.sub_executor_map.get(prefix) if prefix else None
    if exe:
        return exe(**_cont["args"], _crypto_engine=_crypto_engine, _registry=_registry, _engine_internal=engine_internal, _prefix=prefix)
    return {}


def schedule_executor(interval: str, **_kwargs):
    """
        A function placeholder for schedule sub executor
    """
    pass

async def execute_in_sandbox(_prefix: str, _engine_internal: Dict, _context_data: Dict, runtime: str, timeout: int=30, **_kwargs):
    
    system_items = _engine_internal.get(_prefix)
    file_path = system_items.get("_file_path" ) if system_items else None

    P_LANGUAGE_IMAGES = {
        "python": "piper-runner-python:v1",
        "nodejs": "piper-runner-node:v1",
    }

    P_EXTENSIONS = {
        "python": "py",
        "nodejs": "js"
    }
    selected_image = P_LANGUAGE_IMAGES.get(runtime)
    extension = P_EXTENSIONS.get(runtime, "py")

    # 1. Dynamic Volume Mounting
    # We map the HOST path (from the interpreter) to a standard CONTAINER path
    # Example: C:/Users/Dev/my_script.js -> /app/user_code.js
    container_script_path = f"/app/user_code.{extension}"
    if not file_path:
        return {}
    
    # Senior Move: Use // for MINGW64/Git Bash path compatibility on Windows
    volume_mapping = f"{file_path}:{container_script_path}"

    cmd = [
        "docker", "run", "--rm", "-i",
        "--network", "bridge", 
        "-v", volume_mapping,
        selected_image
    ]
    
    try:
        # 2. Process Execution with Timeout
        process = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, # Capture errors too!
            text=True
        )

        # 3. Inject Context & Wait
        stdout, stderr = process.communicate(
            input=json.dumps(_context_data), 
            timeout=timeout
        )

        # 4. Result Extraction
        if "PIPER_RESULT_START" in stdout:
            result_json = stdout.split("PIPER_RESULT_START")[1].split("PIPER_RESULT_END")[0]
            return json.loads(result_json.strip())
        
        # If execution fails, return stderr for debugging
        return {
            "error": "Script executed but returned no Piper Result",
            "stdout": stdout,
            "stderr": stderr
        }

    except subprocess.TimeoutExpired:
        process.kill()
        return {"error": f"Execution timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}

        

        