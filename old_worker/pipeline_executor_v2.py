import ast
import re
import os
import json
from shared.unpacked_data import UnZip
from shared.tools import crawler, retrieve_file, replace_place_value, inspect_function, get_registry_by_version
from shared.encryption_manager import get_encryption_key
from datetime import datetime
import copy
from shared.database_manager import ContextDB
import ast
import inspect
import sys
from typing import Any, Dict, Callable
import uuid
import shared.helpers

class Executor:
    def __init__(self):
        self.context_manager = {}
        self.db = ContextDB()

class PipelineExecutor:
    def __init__(self):
        self.context_manager = {}
        self.db = ContextDB()
        self.registry = None

    async def run_executor(
            self, manifest, event_id, run_id, task_id, client_id, 
            from_trigger=False, _crypto_engine=None, is_schedule: bool = False):   
        
        sample_m = next((item for item in manifest if item), None)
        steps_completed = []
        current_version = self.db.get_version(client_id)
        print(f"Current core execution engine version: {current_version}")
        self.registry = get_registry_by_version(version=current_version)
        
        context_file = {}
        if sample_m:
            context_file = self.db.get_context(client_id, task_id, event_id=event_id) or {}
        
        for m in manifest:
            if not m or not m.get("id"):
                print("⚠️ Step execution skipped: Manifest item is completely empty.")
                continue
                
            id = m.get("id")
            app_name = m.get("app_name")
            step_log = {"step_id": id, "service": m.get("service_manager"), "status": "running", "app_name": app_name}
            
            try:
                combined_context = {**context_file, **self.context_manager}
                m = self.replace_value_from_context(package=m, context_file=combined_context)
                print(f"Hydrated manifest step chunk: {m}")
                
                if "condition" in m:
                    if not self.eval_condition(condition=m["condition"]):
                        continue
                        
                ACTION_MAP = self.registry.executor_map.get(m["service_manager"])
                if ACTION_MAP:
                    package = await ACTION_MAP(
                        _cont=m, 
                        _registry=self.registry, 
                        _crypto_engine=_crypto_engine, 
                        _context_data=combined_context,
                        _client_name=client_id,
                        _task_id=task_id
                    )

                step_log.update({"status": "success", "output_preview": str(package)[:100]})
                steps_completed.append(step_log)
                
                self.db.update_live_logs(run_id, steps_completed)
                print(f"Step block execution output: {package}")
                
                if not package or "error" in str(package).lower():
                    self.db.finalize_log(run_id, "failed", steps_completed, f"Execution generated a soft runtime error: {package}")
                    return
                
                self.context_manager[id] = package
                
            except Exception as e:
                step_log.update({"status": "failed", "error": str(e)})
                steps_completed.append(step_log)
                self.db.finalize_log(run_id, "failed", steps_completed, str(e))
                print(f"Pipeline processing error exception caught: {e}")
                return 
            
            if "steps" in m:
                await self.run_executor(
                    manifest=m["steps"], 
                    event_id=event_id,
                    run_id=run_id,
                    task_id=task_id,
                    client_id=client_id,
                    from_trigger=from_trigger,
                    _crypto_engine=_crypto_engine,
                    is_schedule=is_schedule
                )
        
        self.sync_to_db(client_id=client_id, task_id=task_id, event_id=event_id)
        
        if is_schedule:
            self.db.reschedule_after_completion(client_id, task_id)
            print("Task scheduled successfully for next context polling interval cycle.")

    def get_dynamic_function_registry(self) -> Dict[str, Callable]:
        target_module = shared.helpers
        
        # Get the absolute real path of the helpers file
        target_file_path = os.path.realpath(inspect.getfile(target_module))
        
        return {
            name: func 
            for name, func in inspect.getmembers(target_module, inspect.isfunction)
            if os.path.realpath(inspect.getfile(func)) == target_file_path
        }

    def execute_expression_functions(self, package: Any) -> Any:
        """
        Recursively scans and updates dictionaries, lists, or expression strings.
        Catches all expression parsing errors softly to prevent pipeline execution crashes.
        """
        if isinstance(package, dict):
            return {k: self.execute_expression_functions(v) for k, v in package.items()}

        if isinstance(package, list):
            return [self.execute_expression_functions(item) for item in package]

        if isinstance(package, str):
            clean_expr = package.strip()
            if clean_expr.startswith("{{") and clean_expr.endswith("}}"):
                clean_expr = clean_expr[2:-2].strip()
            else:
                return package

            function_registry = self.get_dynamic_function_registry()

            try:
                tree = ast.parse(clean_expr, mode='eval')
                for node in ast.walk(tree):
                    allowed_nodes = (
                        ast.Expression, ast.Call, ast.Name, ast.Constant, 
                        ast.Load, ast.List, ast.Tuple, ast.Keyword, 
                        ast.BinOp, ast.UnaryOp, ast.Compare, ast.operator
                    )
                    if not isinstance(node, allowed_nodes):
                        print(f"⚠️ Prohibited syntax token detected: {type(node).__name__}")
                        return package
                        
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        if node.func.id not in function_registry:
                            print(f"⚠️ Function '{node.func.id}' is not registered in the pipeline context.")
                            return package
                            
                context_env = {"__builtins__": None, **function_registry}
                return eval(clean_expr, context_env, {})

            except SyntaxError as e:
                print(f"❌ Syntax error parsing token structure: {e}")
                return package
            except Exception as e:
                print(f"❌ Runtime evaluation engine failure: {e}")
                return package

        return package
    
    def sync_to_db(self, client_id, task_id, event_id=None):
        if not event_id:
            event_id = f"evt_{uuid.uuid4().hex[:8]}"

        current_data = self.db.get_context(client_id=client_id, task_id=task_id, event_id=event_id) or {}
        combined_context = {**current_data, **self.context_manager}

        self.db.save_context(client_id, task_id, combined_context, event_id=event_id)
        print(f"📊 Targeted Sync Complete for {client_id} | Event: {event_id}")

    def replace_value_from_context(self, package, context_file):
        pattern = r"\{\{\s*(.*?)\s*\}\}"

        found_items = crawler(content_to_crawl=package, patterns=[pattern])
        if not found_items:
            return package

        crawler_path_map = found_items.get("key_value") if "key_value" in found_items else found_items.get("key_path", {})

        for key, original_value in found_items["matched_items"].items():
            if not isinstance(original_value, str):
                continue

            if "(" in original_value and ")" in original_value:
                function_calls = set(re.findall(r"([\w\-]+)\s*\(", original_value))
                all_tokens = re.findall(r"[\w\-]+(?:\.[\w\-]+)*", original_value)
                all_tokens = sorted(list(set(all_tokens)), key=len, reverse=True)
                
                def token_match_handler(match):
                    found_token = match.group(0)
                    if found_token in function_calls:
                        return found_token
                    
                    parts = [p.strip() for p in found_token.split(".") if p.strip()]
                    hydrated_value = self.get_nested_value(context_file, parts)
                    
                    if hydrated_value is not None:
                        if isinstance(hydrated_value, str) and not hydrated_value.isdigit():
                            return f"'{hydrated_value}'"
                        return str(hydrated_value)
                    return found_token

                if all_tokens:
                    escaped_tokens = [re.escape(t) for t in all_tokens]
                    # Safer boundary lookup covering hyphens/dashes in variable names
                    combined_token_pattern = rf"(?<![\w\.])({'|'.join(escaped_tokens)})(?![\w\.])(?!\s*\()"
                    final_value = re.sub(combined_token_pattern, token_match_handler, original_value)
                else:
                    final_value = original_value

                package = replace_place_value(
                    key_path=crawler_path_map, 
                    key=key,
                    content_to_modify=package, 
                    value=final_value
                )
            else:
                single_match = re.fullmatch(pattern, original_value.strip())
                if single_match:
                    path = single_match.group(1).strip()
                    parts = [p.strip() for p in path.split(".") if p.strip()]
                    hydrated_value = self.get_nested_value(context_file, parts)

                    if hydrated_value is None:
                        hydrated_value = original_value

                    package = replace_place_value(
                        key_path=crawler_path_map, 
                        key=key,
                        content_to_modify=package, 
                        value=hydrated_value
                    )
                else:
                    def string_replacer(match):
                        path = match.group(1).strip()
                        parts = [p.strip() for p in path.split(".") if p.strip()]
                        val = self.get_nested_value(context_file, parts)
                        return str(val) if val is not None else match.group(0)

                    final_string_value = re.sub(pattern, string_replacer, original_value)
                    package = replace_place_value(
                        key_path=crawler_path_map, 
                        key=key,
                        content_to_modify=package, 
                        value=final_string_value
                    )
        package = self.execute_expression_functions(package=package)
        return package

    def get_nested_value(self, data, parts):
        temp = data
        try:
            for k in parts:
                if isinstance(temp, list):
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
    
    async def call_run_executor(self, event_id, _cont, password, run_id, task_id, client_id, from_trigger: bool=False, is_schedule: bool=False):
        self.context_manager = {}
        _crypto_engine = get_encryption_key(password=password)
        fresh_manifest_container = copy.deepcopy(_cont)
        
        if isinstance(fresh_manifest_container, dict) and "Pipeline" in fresh_manifest_container:
            manifest = fresh_manifest_container["Pipeline"]
        else:
            manifest = fresh_manifest_container

        await self.run_executor(
            manifest=manifest, 
            event_id=event_id,
            run_id=run_id, 
            task_id=task_id,
            client_id=client_id, 
            from_trigger=from_trigger,
            _crypto_engine=_crypto_engine, 
            is_schedule=is_schedule
        )
    
    def eval_condition(self, condition: str):
        if not self.is_safe_condition(condition_string=condition):
           raise SyntaxError(f"Security restriction violation: Invalid runtime expression framework detected: {condition}")
           
        if "MISSING_KEY_" in str(condition) or "PATH_NOT_FOUND_" in str(condition):
            print(f"⚠️ Data Dependency Missing skipping condition step logic processing context: {condition}")
            return False
            
        print(f"Evaluating verified expression token tree: {condition}")
        result = eval(condition, {"__builtins__": None}, {})
        print(f"Expression evaluation matching result sequence: {result}")
        return result
    
    def is_safe_condition(self, condition_string):
        try:
            tree = ast.parse(condition_string, mode='eval')
            for node in ast.walk(tree):
                allowed_nodes = (
                    ast.Expression, ast.Compare, ast.BinOp, 
                    ast.BoolOp, ast.UnaryOp, ast.Name, 
                    ast.Constant, ast.Load
                )
                if not isinstance(node, allowed_nodes):
                    print(f"Security Violation: {type(node).__name__} element block structure usage is not permitted.")
                    return False
            return True
        except SyntaxError:
            return False

class PipelineExecutorV2:
    def __init__(self):
        self.context_manager = {}
        # 1. Initialize the Database connection
        self.db = ContextDB()
        self.registry = None  # We will set this dynamically per run

    async def run_executor(
            self, manifest, event_id, run_id, task_id, client_id, from_trigger=False, 
            _crypto_engine=None, is_schedule: bool=False):   
        sample_m = next((item for item in manifest if item), None)
        steps_completed = []
        current_version = self.db.get_version(client_id)
        print(f"current version:      {current_version}")
        self.registry = get_registry_by_version(version=current_version)
        
        # 2. Get client info and task ID for DB lookup
        if sample_m:
            context_file = self.db.get_context(client_id, task_id, event_id=event_id) or {}
        
        for m in manifest:
            if not m or not m.get("id"):
                print("⚠️ Step execution skipped: Manifest item is completely empty (None or empty dict).")
                continue
            id = m.get("id")
            app_name = m.get("app_name")
            step_log = {"step_id": id, "service": m.get("service_manager"), "status": "running", "app_name": app_name}
            try:
                # Variable replacement logic remains the same (it just uses the data we fetched)
                combined_context = {**context_file, **self.context_manager}
                # 🚫 TEMPORARILY DISABLED CONTEXT REPLACEMENT FOR TESTING
                m = self.replace_value_from_context(package=m, context_file=combined_context)
                print(f"m:    {m}")
                if "condition" in m:
                    if not self.eval_condition(condition=m["condition"]):
                        continue
                ACTION_MAP = self.registry.executor_map.get(m["service_manager"])
                if ACTION_MAP:
                    package = await ACTION_MAP(
                        _cont=m, 
                        _registry=self.registry, 
                        _crypto_engine=_crypto_engine, 
                        _context_data=combined_context, # <--- Merged context passed here
                        _client_name=client_id,
                        _task_id=task_id
                    )

                # 2. CAPTURE STEP SUCCESS
                step_log.update({"status": "success", "output_preview": str(package)[:100]})
                steps_completed.append(step_log)
                
                # Sync partial logs to DB so the dashboard updates while the worker is still running
                self.db.update_live_logs(run_id, steps_completed)
                print(f"pachage:     {package}")
                
                if not package or "error" in str(package).lower():
                    return
                
                self.context_manager[id] = package
            except Exception as e:
                # 3. CAPTURE STEP FAILURE
                step_log.update({"status": "failed", "error": str(e)})
                steps_completed.append(step_log)
                self.db.finalize_log(run_id, "failed", steps_completed, str(e))
                print(f"error: {e}")
                print(f"combine context:       {combined_context}")
                return # Stop pipeline on error
            
            if "steps" in m:
                await self.run_executor(
                    manifest=m["steps"], 
                    event_id=event_id, 
                    run_id=run_id, 
                    task_id=task_id, 
                    client_id=client_id, 
                    from_trigger=from_trigger, 
                    _crypto_engine=_crypto_engine, 
                    is_schedule=is_schedule
                )
        
        # 3. REPLACED: write_to_context_manager logic
        # Instead of writing to a file path, we send it to the DB
        #if sample_m:
        self.sync_to_db(
            client_id=client_id, 
            task_id=task_id,
            event_id=event_id
        )
        if is_schedule:
            self.db.reschedule_after_completion(client_id, task_id)
            print(f"task rescheduled for the next run")

    # In your PipelineExecutor class
    def sync_to_db(self, client_id, task_id, event_id=None):
        """
        Saves worker results back to the specific event context 
        instead of just 'the last entry'.
        """
        # 1. Fetch current state

        if not event_id:
            event_id = f"evt_{uuid.uuid4().hex[:8]}"

        current_data = self.db.get_context(client_id=client_id, task_id=task_id, event_id=event_id) or {}
        combined_context = {**current_data, **self.context_manager}

        # 2. Atomic Save
        self.db.save_context(client_id, task_id, combined_context, event_id=event_id)
        print(f"📊 Targeted Sync Complete for {client_id} | Event: {event_id}")
        
    def sync_to_db_v2(self, client_id, task_id, package, from_trigger):
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

    """def replace_value_from_context(self, package, context_file):
        # NEW PATTERN: Non-greedy, supports $, dots, and hyphens
        pattern = r"\{\{(?P<variable>[\w\.\-\$]+)\}\}"

        # 3. Define the Callback Replacer
        def replacer(match):
            path = match.group("variable")
            parts = path.split(".")
            
            # Use your existing get_nested_value helper
            val = self.get_nested_value(context_file, parts)
            
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
                        key_path=found_items["key_value"], 
                        key=key,
                        content_to_modify=package, 
                        value=final_value
                    )
        return package"""

    def replace_value_from_context(self, package, context_file):
        # Captures everything inside {{ }} tags safely
        pattern = r"\{\{\s*(.*?)\s*\}\}"

        found_items = crawler(content_to_crawl=package, patterns=[pattern])
        if not found_items:
            return package

        crawler_path_map = found_items.get("key_value") if "key_value" in found_items else found_items.get("key_path", {})

        for key, original_value in found_items["matched_items"].items():
            if not isinstance(original_value, str):
                continue

            # Check if this tag contains an inline function expression
            if "(" in original_value and ")" in original_value:
                
                # 1. Structural Tracking: Find all tokens followed immediately by an opening parenthesis
                function_calls = set(re.findall(r"([\w\-]+)\s*\(", original_value))
                
                # 2. Extract every standalone data/dot-path context word token inside the expression
                all_tokens = re.findall(r"[\w\-]+(?:\.[\w\-]+)*", original_value)
                
                # CRITICAL NESTING FIX: Sort tokens by length descending.
                # This ensures complex/longer paths are replaced BEFORE their shorter base sub-paths.
                all_tokens = sorted(list(set(all_tokens)), key=len, reverse=True)
                
                final_value = original_value
                for raw_path in all_tokens:
                    # STRUCTURAL CHECK: Skip if it's the actual function identifier execution token
                    if raw_path in function_calls:
                        if re.search(rf"\b{re.escape(raw_path)}\b\s*\(", final_value):
                            continue
                        
                    parts = [p.strip() for p in raw_path.split(".") if p.strip()]
                    hydrated_value = self.get_nested_value(context_file, parts)
                    
                    # Replace only if it resolves to a valid value in the run context
                    if hydrated_value is not None:
                        # Enforce strict word boundaries and ensure it's not an active function invocation
                        final_value = re.sub(rf"\b{re.escape(raw_path)}\b(?!\s*\()", str(hydrated_value), final_value)

                package = replace_place_value(
                    key_path=crawler_path_map, 
                    key=key,
                    content_to_modify=package, 
                    value=final_value
                )

            else:
                # Standard non-functional token evaluation path
                single_match = re.fullmatch(pattern, original_value.strip())
                if single_match:
                    path = single_match.group(1).strip()
                    parts = [p.strip() for p in path.split(".") if p.strip()]
                    hydrated_value = self.get_nested_value(context_file, parts)

                    if hydrated_value is None:
                        hydrated_value = original_value

                    package = replace_place_value(
                        key_path=crawler_path_map, 
                        key=key,
                        content_to_modify=package, 
                        value=hydrated_value
                    )
                else:
                    # Mixed text string interpolation fallback
                    def string_replacer(match):
                        path = match.group(1).strip()
                        parts = [p.strip() for p in path.split(".") if p.strip()]
                        val = self.get_nested_value(context_file, parts)
                        return str(val) if val is not None else match.group(0)

                    final_string_value = re.sub(pattern, string_replacer, original_value)
                    package = replace_place_value(
                        key_path=crawler_path_map, 
                        key=key,
                        content_to_modify=package, 
                        value=final_string_value
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
    
    async def call_run_executor(self, event_id, _cont, password, run_id, task_id, client_id, from_trigger: bool=False, is_schedule: bool=False):
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
            run_id=run_id, client_id=client_id, 
            task_id=task_id, 
            is_schedule=is_schedule,
            event_id=event_id
        )
    
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
        # Pass clean explicit global context to avoid referencing system globals
        result = eval(condition, {"__builtins__": None}, {})
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
        