import copy
import asyncio
from shared.expression_mixin import ExpressionMixin
from shared.controller_mixin import ControllerMixin
from shared.database_manager import ContextDB
from shared.tools import get_registry_by_version
from shared.system_functions import PipelineGlobalExit, ActionSignal
from shared.tools import split_args_smart
from shared.encryption_manager import get_encryption_key
import time
import logging

logger = logging.getLogger("PipelineExecutor")

class PipelineExecutor(ExpressionMixin, ControllerMixin):
    def __init__(self):
        self.context_manager = {}
        self.db = ContextDB()
        self.registry = None
        self.global_id_map = {}
        self.split_args_smart = split_args_smart # Inject tool

    def _build_global_id_map(self, manifest, current_list=None):
        if current_list is None: current_list = manifest
        for i, step in enumerate(manifest):
            if step and step.get("id"):
                self.global_id_map[step["id"]] = (manifest, i)
            if "steps" in step and isinstance(step["steps"], list):
                self._build_global_id_map(step["steps"], step["steps"])

    async def _log_live_async(self, run_id, steps_snapshot):
        """Non-blocking background helper to write live logs in a separate thread."""
        await asyncio.to_thread(self.db.update_live_logs, run_id, steps_snapshot)

    async def _log_finalize_async(self, run_id, status, steps_snapshot, error_msg):
        """Non-blocking background helper to finalize logs in a separate thread."""
        await asyncio.to_thread(self.db.finalize_log, run_id, status, steps_snapshot, error_msg)

    async def _save_checkpoint_async(self, run_id, checkpoint_data):
        """Non-blocking background helper to save checkpoints in a separate thread."""
        await asyncio.to_thread(self.db.save_checkpoint, run_id, checkpoint_data)

    async def call_run_executor(self, event_id, _cont, password, run_id, task_id, client_id, from_trigger: bool=False, is_schedule: bool=False):
            self.context_manager = {}
            _crypto_engine = await asyncio.to_thread(get_encryption_key, password=password)
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

    async def run_executor(self, manifest, event_id, run_id, task_id, client_id, 
                            from_trigger=False, _crypto_engine=None, is_schedule: bool = False): 

        current_version = await asyncio.to_thread(self.db.get_version, client_id)
        self.registry = get_registry_by_version(version=current_version)
        existing_checkpoint = await asyncio.to_thread(self.db.get_checkpoint, run_id)
        
        self.global_id_map = manifest.get("id_map") or {}
        
        if existing_checkpoint:
            execution_stack = existing_checkpoint["execution_stack"]
            idx_stack = existing_checkpoint["idx_stack"]
            call_stack = existing_checkpoint["call_stack"]
            self.context_manager = existing_checkpoint["context"]
        else:
            execution_stack = [manifest]
            idx_stack = [0]
            call_stack = []      
        
        context_file = await asyncio.to_thread(self.db.get_context, client_id, task_id, event_id=event_id) or {}
        steps_completed = []

        while execution_stack:
            if idx_stack[-1] >= len(execution_stack[-1]):
                execution_stack.pop()
                idx_stack.pop()
                if call_stack:
                    parent_manifest, return_idx = call_stack.pop()
                    idx_stack[-1] = return_idx
                else:
                    # ✅ Fix: Advance the parent's pointer past the container node once its steps finish
                    if idx_stack:
                        idx_stack[-1] += 1
                continue

            current_manifest = execution_stack[-1]
            idx = idx_stack[-1]
            m = current_manifest[idx]

            if not m or not m.get("id"):
                idx_stack[-1] += 1
                continue
                
            step_id = m.get("id")
            step_log = {"step_id": step_id, "service": m.get("service_manager"), "status": "running", "app_name": m.get("app_name")}
            
            try:
                combined_context = {**context_file, **self.context_manager}
                safe_context_env = {str(k).replace("-", "_"): v for k, v in combined_context.items()}
                m = self.execute_expression_functions(package=m, context_env=safe_context_env)
                dynamic_args = m.get("execution")
                if "_args" in m and isinstance(dynamic_args, dict):
                    m["execution"]["_args"] = await self.process_input_logic(dynamic_args["_args"], safe_context_env)
                
                can_proceed = True
                action_triggered = False

                if "condition" in m:
                    condition_data = m["condition"]
                    condition_met = False
                    if isinstance(condition_data, list):
                        for rule in condition_data:
                            if self.eval_condition(condition=rule["if"], context_env=safe_context_env) or "else" in rule:
                                condition_met = True
                                operations = rule.get("operations", [])
                                if not operations: continue
                                for op in operations:
                                    op_to_exec = op.get("else") if "else" in op else op
                                    result = await self.execute_operation(op=op_to_exec, context_env=safe_context_env)
                                    if isinstance(result, dict) and "signal" in result:
                                        if result["signal"] == ActionSignal.BREAK: return
                                        if result["signal"] == ActionSignal.GOTO:
                                            target = result["target"]
                                            new_manifest, new_idx = self.global_id_map[target]
                                            # 🔀 Add logger here to track jumps
                                            logger.info(f"🔀 GOTO Jump -> Target Node ID: '{target}' at index: {new_idx}")
                                            execution_stack[-1] = new_manifest
                                            idx_stack[-1] = new_idx
                                            action_triggered = True; break
                                        if result["signal"] == ActionSignal.CALL:
                                            target = result["target"]
                                            call_stack.append((current_manifest, idx + 1))
                                            if "args" in result and isinstance(result["args"], dict): self.context_manager.update(result["args"])
                                            node_container, node_idx = self.global_id_map[target]
                                            patched_node = copy.deepcopy(node_container[node_idx])
                                            if "args" in result and isinstance(result["args"], dict):
                                                patched_node.setdefault("input", {})
                                                self.deep_merge(patched_node["input"], result["args"])
                                            execution_stack.append([patched_node])
                                            idx_stack.append(0)
                                            action_triggered = True; break
                                if action_triggered: break
                        if not condition_met: can_proceed = False
                if action_triggered: continue

                if can_proceed and m.get("operations"):
                    for op in m["operations"]:
                        op_to_exec = op.get("else") if "else" in op else op
                        result = await self.execute_operation(op=op_to_exec, context_env=safe_context_env)
                        if isinstance(result, dict) and "signal" in result:
                            if result["signal"] == ActionSignal.BREAK: return
                            if result["signal"] == ActionSignal.GOTO:
                                target = result["target"]
                                new_manifest, new_idx = self.global_id_map[target]
                                execution_stack[-1] = new_manifest
                                idx_stack[-1] = new_idx
                                action_triggered = True; break
                            if result["signal"] == ActionSignal.CALL:
                                target = result["target"]
                                call_stack.append((current_manifest, idx + 1))
                                if "args" in result and isinstance(result["args"], dict): self.context_manager.update(result["args"])
                                node_container, node_idx = self.global_id_map[target]
                                patched_node = copy.deepcopy(node_container[node_idx])
                                if "args" in result and isinstance(result["args"], dict):
                                    patched_node.setdefault("input", {})
                                    self.deep_merge(patched_node["input"], result["args"])
                                execution_stack.append([patched_node])
                                idx_stack.append(0)
                                action_triggered = True; break
                if action_triggered: continue

                if can_proceed:
                    execution_type = m.get("execution_type")
                    ACTION_MAP = self.registry.executor_map.get(execution_type) if execution_type else None
                    print(f"    action_map:                {ACTION_MAP}")
                    if ACTION_MAP:
                        start_time = time.perf_counter()
                        package = await ACTION_MAP(
                            **dynamic_args, _registry=self.registry, _crypto_engine=_crypto_engine, 
                            _context_data=combined_context, _client_name=client_id, _task_id=task_id
                        )

                        duration_ms = (time.perf_counter() - start_time) * 1000
                        logger.info(f"⏱️ Step [{step_id}] ({m.get('service_manager')}) executed in {duration_ms:.2f}ms")
                        logger.info(f"package:                 {package}")

                        step_log.update({"status": "success", "output_preview": str(package)[:100], "duration_ms": duration_ms})
                        steps_completed.append(step_log)
                        
                        # Non-blocking telemetry hand-off to background thread pool
                        asyncio.create_task(self._log_live_async(run_id, list(steps_completed)))
                        
                        # Non-blocking checkpoint save via background thread pool
                        asyncio.create_task(self._save_checkpoint_async(run_id, {
                            "execution_stack": execution_stack, "idx_stack": idx_stack,
                            "call_stack": call_stack, "context": self.context_manager
                        }))
                        if not package or "error" in str(package).lower():
                            asyncio.create_task(self._log_finalize_async(run_id, "failed", list(steps_completed), f"Error: {package}"))
                            return
                        self.context_manager[step_id] = package
                    if "steps" in m:
                        execution_stack.append(m["steps"])
                        idx_stack.append(0)
                        continue
            except PipelineGlobalExit: raise
            except Exception as e:
                step_log.update({"status": "failed", "error": str(e)})
                logger.info(f"step_log:              {step_log}")
                steps_completed.append(step_log)
                asyncio.create_task(self._log_finalize_async(run_id, "failed", list(steps_completed), str(e)))
                return 
            idx_stack[-1] += 1
        
        # Non-blocking hand-off for final synchronization and scheduling
        await asyncio.to_thread(
            self.sync_to_db, client_id=client_id, task_id=task_id, event_id=event_id
        )
        if is_schedule:
            await asyncio.to_thread(
                self.db.reschedule_after_completion, client_id, task_id
            )