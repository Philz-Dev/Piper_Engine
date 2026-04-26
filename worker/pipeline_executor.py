import ast
import re
import os
import json
from shared.unpacked_data import UnZip
from shared.tools import crawler, retrieve_file, replace_place_value, inspect_function
from shared.validators import ACTION_MAP
from shared.encryption_manager import get_encryption_key
from datetime import datetime
import copy
from shared.database_manager import ContextDB

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
            self, manifest, run_id, task_id, client_id, from_trigger=False, 
            _crypto_engine=None, is_schedule: bool=False):   
        sample_m = next((item for item in manifest if item), None)
        
        # 2. Get client info and task ID for DB lookup
        if sample_m:
            context_file = self.db.get_context(client_id, task_id) or {}
        
        for m in manifest:
            if not m or not m.get("id"): continue
            
            # Variable replacement logic remains the same (it just uses the data we fetched)
            m = self.replace_value_from_context(package=m, context_file=context_file)
            
            if "condition" in m:
                if not self.eval_condition(condition=m["condition"]):
                    continue
            
            package = await ACTION_MAP[m["service_manager"]](**m["args"], _crypto_engine=_crypto_engine)
            
            if not package or "error" in str(package).lower():
                return
            
            self.context_manager[m["id"]] = package
            
            if "steps" in m:
                await self.run_executor(manifest=m["steps"], _crypto_engine=_crypto_engine, from_trigger=from_trigger)
        
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
        