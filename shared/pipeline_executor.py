import copy
import asyncio
from shared.expression_mixin import ExpressionMixin
from shared.controller_mixin import ControllerMixin
from shared.database_manager import ContextDB
from shared.tools import get_registry_by_version
from shared.system_functions import PipelineGlobalExit, ActionSignal
from shared.tools import split_args_smart
from shared.encryption_manager import get_encryption_key
from shared.setup_build import execute_piper_stop_v2
import time
import logging

logger = logging.getLogger("PipelineExecutor")

class PipelineExecutor(ExpressionMixin, ControllerMixin):
    def __init__(self):
        self.context_manager = {}
        self.db = ContextDB()
        self.registry = None
        self.global_id_map = {}
        self.split_args_smart = split_args_smart  # Inject tool
        self.runtime_node_overrides = {}
        self.already_executed = ()
        self.node_execution_state = set()       # 🛡️ Tracks nodes that already ran their main service action
        self.node_operation_pointers = {}       # 📌 Tracks the next operation index for nodes with multiple calls      
        self.node_iteration_counts = {}

        # 🎬 Lifecycle blocks storage
        self.on_complete = None
        self.on_error = None
        self.on_success = None

        self.password = None  # 📌 Store password on instance
        self.client_id = None
        self.task_id = None

        self.should_stop = False
        
    async def _log_live_async(self, run_id, steps_snapshot):
        """Non-blocking background helper to write live logs in a separate thread."""
        await asyncio.to_thread(self.db.update_live_logs, run_id, steps_snapshot)

    async def _log_finalize_async(self, run_id, status, steps_snapshot, error_msg):
        """Non-blocking background helper to finalize logs in a separate thread."""
        await asyncio.to_thread(self.db.finalize_log, run_id, status, steps_snapshot, error_msg)

    async def _save_checkpoint_async(self, run_id, checkpoint_data):
        """Non-blocking background helper to save checkpoints in a separate thread."""
        await asyncio.to_thread(self.db.save_checkpoint, run_id, checkpoint_data)

    async def _run_lifecycle_block(self, block_data, event_id, run_id, task_id, client_id, _crypto_engine):
        """Helper method to isolate and execute lifecycle blocks (on_success, on_error, on_complete)."""
        if not block_data:
            return
        logger.info("🎬 Running lifecycle block...")
        if isinstance(block_data, dict):
            block_manifest = block_data.get("pipeline_data", block_data.get("pipeline", block_data))
        else:
            block_manifest = block_data

        sub_executor = PipelineExecutor()
        sub_executor.registry = self.registry
        sub_executor.context_manager = self.context_manager.copy()
        
        await sub_executor.run_executor(
            manifest=block_manifest,
            event_id=event_id,
            run_id=run_id,
            task_id=task_id,
            client_id=client_id,
            from_trigger=False,
            _crypto_engine=_crypto_engine,
            is_schedule=False
        )
        self.context_manager.update(sub_executor.context_manager)

    async def call_run_executor(self, event_id, _cont, password, run_id, task_id, client_id, from_trigger: bool = False, is_schedule: bool = False):
        self.context_manager = {}
        _crypto_engine = await asyncio.to_thread(get_encryption_key, password=password)
        fresh_manifest_container = copy.deepcopy(_cont)

        self.password = password  # 📌 Store password on instance
        self.client_id = client_id
        self.task_id = task_id
        
        # Reset lifecycle hooks
        self.on_complete = None
        self.on_error = None
        self.on_success = None

        if isinstance(fresh_manifest_container, dict):
            if "pipeline_data" in fresh_manifest_container:
                manifest = fresh_manifest_container["pipeline_data"]
                self.on_complete = fresh_manifest_container.get("on_complete")
                self.on_error = fresh_manifest_container.get("on_error")
                self.on_success = fresh_manifest_container.get("on_success")
            elif "pipeline" in fresh_manifest_container:
                manifest = fresh_manifest_container["pipeline"]
            else:
                manifest = fresh_manifest_container
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

    async def _execute_node_action(self, m, step_id, step_log, can_proceed, dynamic_args, 
                                   _crypto_engine, combined_context, client_id, task_id, 
                                   run_id, ip, next_ip, skip_ip, call_stack, steps_completed):
        """
        Isolated helper method to handle the core service execution, performance timing,
        live logging, checkpoint saving, and error finalization.
        """
        if can_proceed:
            execution_type = m.get("execution_type")
            ACTION_MAP = self.registry.executor_map.get(execution_type) if execution_type else None
            if ACTION_MAP:
                start_time = time.perf_counter()
                try:
                    package = await ACTION_MAP(
                        **dynamic_args, _registry=self.registry, _crypto_engine=_crypto_engine, 
                        _context_data=combined_context, _client_name=client_id, _task_id=task_id
                    )
                except Exception as e:
                    error_msg = str(e)
                    package = {"error": error_msg}
                    # 🛠️ Save error details to context manager for error handling subroutines
                    self.context_manager["_error_message"] = error_msg
                    self.context_manager[f"_error_message_{step_id}"] = error_msg

                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.info(f"⏱️ Step [{step_id}] ({m.get('service_manager')}) executed in {duration_ms:.2f}ms")

                if not package or "error" in str(package).lower():
                    if not isinstance(package, dict):
                        package = {"error": str(package)}

                    step_log.update({"status": "failed", "output_preview": str(package)[:100], "duration_ms": duration_ms, "error": package.get("error")})
                    steps_completed.append(step_log)
                    asyncio.create_task(self._log_live_async(run_id, list(steps_completed)))
                    self.context_manager[step_id] = package
                    self.context_manager["_on_error"] = False
                    self.context_manager["_on_success"] = True
                    return next_ip, True
                else:
                    step_log.update({"status": "success", "output_preview": str(package)[:100], "duration_ms": duration_ms})
                    steps_completed.append(step_log)
                    asyncio.create_task(self._log_live_async(run_id, list(steps_completed)))
                    asyncio.create_task(self._save_checkpoint_async(run_id, {
                        "ip": ip, "call_stack": call_stack, "context": self.context_manager
                    }))
                    self.context_manager[step_id] = package
                    self.context_manager["_on_error"] = True
                    self.context_manager["_on_success"] = False
                    return next_ip, False
            
            return next_ip, False
        else:
            return skip_ip, False

    async def _evaluate_node_conditions(self, m, safe_context_env):
        """
        Isolated, reusable helper method to evaluate cascading if/elif/else condition rules 
        against the given context environment and collect associated operations.
        """

        can_proceed = True
        
        # 1. Gather all operations into a list before executing them
        ops_to_run = []
        matched_any = False
        else_rule = {}

        if "condition" in m:
            condition_data = m["condition"]
            can_proceed = False  # Default to false until explicit execution signal or condition match permits
    
            if isinstance(condition_data, list):
                for rule in condition_data:
                    condition_met = False
                    
                    # Safe cascading if / elif / else evaluation
                    if rule.get("if"):
                        if self.eval_condition(condition=rule["if"], context_env=safe_context_env):
                            condition_met = True
                            matched_any = True
                    elif rule.get("elif") and not matched_any:
                        if self.eval_condition(condition=rule["elif"], context_env=safe_context_env):
                            condition_met = True
                            matched_any = True
                    elif ("else" in rule or rule.get("else") is not None) and not matched_any:
                        
                        else_rule_ops = rule.get("else", [])
                        else_rule = else_rule_ops.get("operations", [])
                        condition_met = True
                        matched_any = True

                    if condition_met:
                        rule_ops = rule.get("operations", []) or else_rule
                        if rule_ops:
                            ops_to_run.extend(rule_ops)

        # Also gather general node-level operations if present
        if m.get("operations"):
            ops_to_run.extend(m["operations"])

        return can_proceed, ops_to_run, matched_any

    async def _process_operations(self, ops_to_run, safe_context_env, next_ip, can_proceed, for_retry=False, step_id=None, nodes_retry_times=None, node_max_retry_times=3, ip=0):
        """Isolated helper to process operations sequentially and gather control flow signals."""
        
        should_retry = False
        has_break = False
        ip_adjustment = None
        redirect_actions = []
        should_continue = False
        execute_signal = False
        has_stop = False
        
        if ops_to_run:
            for op in ops_to_run:
                
                op_to_exec = op.get("else") if isinstance(op, dict) and "else" in op else op
                
                result = await self.execute_operation(op=op_to_exec, context_env=safe_context_env)
                
                if isinstance(result, dict) and "signal" in result:
                    signal = result["signal"]
                    
                    if signal == ActionSignal.EXECUTE:
                        can_proceed = True
                        execute_signal = True

                    elif signal == ActionSignal.STOP:
                        logger.error(f"🛑 Stop signal triggered for task [{self.task_id}]. Executing full teardown...")
                        await execute_piper_stop_v2(
                            client_id=self.client_id, 
                            task_id=self.task_id, 
                            password=self.password
                        )
                        has_stop = True
                        
                    elif signal == ActionSignal.BREAK:
                        has_break = True
                    elif signal == ActionSignal.RETRY:
                        if nodes_retry_times is not None and step_id is not None:
                            current_retries = nodes_retry_times.get(step_id, 0)
                            if current_retries < node_max_retry_times:
                                nodes_retry_times[step_id] = current_retries + 1
                                logger.info(f"🔄 Retry triggered for node [{step_id}]. Attempt {nodes_retry_times[step_id]}/{node_max_retry_times}")
                                should_retry = True
                                ip = ip - 1 if ip > 0 else 0
                                ip_adjustment = ip
                                break
                        should_retry = True
                        ip_adjustment = next_ip - 1
                        
                    elif signal == ActionSignal.GOTO:
                        target = result["target"]
                        redirect_actions.append({"type": "GOTO", "target": target})

                    elif signal == ActionSignal.CONTINUE:
                        should_continue = True

                    elif signal == ActionSignal.CALL:
                        target = result["target"]
                        redirect_actions.append(
                            {"type": "CALL", "target": target, 
                             "args": result.get("args"),
                             "call_type": result.get("type")
                             }
                            )
        
        return can_proceed, should_retry, has_break, ip_adjustment, redirect_actions, should_continue, execute_signal, has_stop

    def _handle_control_flow(self, redirect_actions, instructions, call_stack, current_ip):
        """Isolated helper to handle GOTO and CALL redirects with deepcopy isolation."""
        for action in redirect_actions:
            if action:
                if action["type"] == "GOTO":
                    target = action["target"]
                    if target not in self.global_id_map:
                        raise ValueError(
                            f"GOTO target '{target}' not found in pipeline. "
                            f"Available node ids: {sorted(self.global_id_map.keys())}"
                        )
                    ip = self.global_id_map[target]
                    logger.info(f"🔀 GOTO Jump -> Target Node ID: '{target}' at index: {ip}")
                    
                    return ip, True

                elif action["type"] == "CALL":
                    target = action["target"]
                    if target not in self.global_id_map:
                        raise ValueError(
                            f"CALL target '{target}' not found in pipeline. "
                            f"Available node ids: {sorted(self.global_id_map.keys())}"
                        )
                    target_idx = self.global_id_map[target]
                    target_node = instructions[target_idx]
                    next_index = target_node.get("next_index", target_idx + 1)
                    self.context_manager["_on_call"] = target_idx

                    # 🛡️ Deepcopy isolation: Clone template so shared tape remains pristine
                    subroutine_node = copy.deepcopy(target_node)

                    if action.get("args") and isinstance(action["args"], dict):
                        
                        exe = subroutine_node.get("execution", {})
                        if exe:
                            self.deep_merge(exe, action["args"])

                    self.runtime_node_overrides[target_idx] = subroutine_node

                    # 📌 CRITICAL FIX: Return IP points back to current node index so multi-call nodes resume correctly
                    return_ip = current_ip
                    # 🛠️ FIX: skip_index (not next_index) is what compiler.py overwrites to
                    # point past a node's nested `steps` block. next_index instead points at
                    # the FIRST child of a block, which would return before the subroutine's
                    # children ever ran. Use skip_index when it's a real boundary (> target_idx);
                    # for a leaf/flat target (skip_index == target_idx, compiler's default),
                    # fall back to target_idx + 1.
                   # 🎛️ Explicit invocation type handling
                    call_mode = action.get("call_type", "block") # Default to block or node depending on your preference
                    
                    if call_mode == "single":
                        # Force exit immediately after the target node, ignoring child blocks/skip_index
                        exit_ip = next_index
                    else:
                        # Standard block execution: respect skip_index boundaries
                        raw_skip = target_node.get("skip_index", next_index)
                        exit_ip = raw_skip + 1
                    
                    call_stack.append((return_ip, exit_ip))
                    ip = target_idx
                    logger.info(f"📞 CALL Subroutine -> Target Node ID: '{target}' at index: {ip} (Exit IP: {exit_ip}, Return IP: {return_ip})")
                    return ip, True
        return None, False
    
    async def run_executor(self, manifest, event_id, run_id, task_id, client_id, 
                            from_trigger=False, _crypto_engine=None, is_schedule: bool = False): 

        self.client_id = client_id
        self.task_id = task_id

        current_version = await asyncio.to_thread(self.db.get_version, client_id)
        self.registry = get_registry_by_version(version=current_version)
        existing_checkpoint = await asyncio.to_thread(self.db.get_checkpoint, run_id)

        self.node_execution_state.clear()
        self.node_operation_pointers.clear()
        self.runtime_node_overrides.clear()
        self.node_iteration_counts.clear()
        
        # Extract instructions list and global ID map from manifest container
        
        if isinstance(manifest, dict):
            self.global_id_map = manifest.get("id_map") or {}
            instructions = manifest.get("instructions", [])
        else:
            instructions = manifest
            self.global_id_map = {}

        if existing_checkpoint:
            ip = existing_checkpoint.get("ip", 0)
            call_stack = existing_checkpoint.get("call_stack", [])
            self.context_manager = existing_checkpoint.get("context", {})
            self.runtime_node_overrides = existing_checkpoint.get("runtime_overrides", {})
        else:
            ip = 0
            call_stack = []
            self.runtime_node_overrides = {}
        
        context_file = await asyncio.to_thread(self.db.get_context, client_id, task_id, event_id=event_id) or {}
        steps_completed = []
        nodes_retry_times = {}
        node_max_retry_times = 3
        single_node_count = 0
        mmax_recursion = 100
        try:
            while (0 <= ip < len(instructions)) or (call_stack and ip == call_stack[-1][1]):
                
                if single_node_count >= mmax_recursion:
                    return

                single_node_count += 1

                # 🛠️ FIX: RETURN check. Previously the only way call_stack ever got
                # popped was ip running off the end of the *entire* instructions list,
                # so a CALL never actually returned to its caller - it just kept
                # executing forward through whatever nodes happened to follow the
                # subroutine in the master pipeline. This checks, on every iteration,
                # whether we've reached the exit_ip of the innermost active call and,
                # if so, pops the frame and resumes at the caller.
                if call_stack and ip == call_stack[-1][1]:
                    return_ip, _exit_ip = call_stack.pop()
                    self.node_operation_pointers[return_ip] = self.node_operation_pointers.get(return_ip, 0) + 1
                    logger.info(f"↩️ RETURN from subroutine -> back to caller index: {return_ip}")
                    ip = return_ip
                    continue



                if ip in self.runtime_node_overrides:
                    m = self.runtime_node_overrides[ip]
                else:
                    m = instructions[ip]

                if not m or not m.get("id"):
                    ip = m.get("next_index")
                    continue

                # 🛡️ ON_CALL BLOCK GUARD:
                # If a node is marked as on_call, skip it during normal linear flow 
                # unless it's being actively invoked via the call stack.
                if m.get("on_call") is True:
                    # Check if the current IP matches the top of the call stack's target
                    is_active_call = any(call_target_ip == ip for call_target_ip, _ in call_stack) or (call_stack and call_stack[-1] == ip)
                    # Alternatively, check if the previous instruction was a call redirect landing here.
                    # A simpler, robust check: if call_stack is empty or this node wasn't reached via a call, skip it.
                    # Let's verify using a clean check:
                    if not call_stack:
                        logger.info(f"⏩ Skipping 'on_call' node [{m.get('id')}] at index {ip} (Linear execution bypassed)")
                        if not m.get("skip_index") == ip:
                            ip = m.get("skip_index")
                        else:
                            ip = m.get("next_index")
                        continue
                
                    
                step_id = m.get("id")
                step_log = {"step_id": step_id, "service": m.get("service_manager"), "status": "running", "app_name": m.get("app_name")}

                # Track and increment iteration count for this specific node/step
                current_iterations = self.node_iteration_counts.get(ip, 0) + 1
                self.node_iteration_counts[ip] = current_iterations

                # Inject it into context manager under a convention like _iterations or step-specific keys
                self.context_manager[f"_node_{step_id}_iterations"] = current_iterations
                self.context_manager["_current_node_iterations"] = current_iterations
                
                try:
                    combined_context = {**context_file, **self.context_manager}
                    safe_context_env = {str(k).replace("-", "_"): v for k, v in combined_context.items()}
                    m = self.execute_expression_functions(package=m, context_env=safe_context_env)
                    dynamic_args = m.get("execution")
                    if "_args" in m and isinstance(dynamic_args, dict):
                        m["execution"]["_args"] = await self.process_input_logic(dynamic_args["_args"], safe_context_env)
                    
                    can_proceed = True
                    original_ip = ip  # 🛠️ FIX: _execute_node_action reassigns `ip` to next_ip/skip_ip
                                    # below. Bookkeeping that refers to *this* node (execution
                                    # state, operation pointers, the current_ip handed to
                                    # _handle_control_flow) must use original_ip, not the
                                    # mutated `ip`, or a CALL's return_ip ends up pointing past
                                    # the caller instead of at it - silently skipping whatever
                                    # follows and dropping any remaining ops on this node.
                    next_ip = m.get("next_index", ip + 1)
                    skip_ip = m.get("skip_index", ip + 1)
                    current_index = m.get("index", ip)
                    should_continue = False

                    # 1. Pre-execution condition evaluation
                    can_proceed, ops_to_run, matched_any = await self._evaluate_node_conditions(m, safe_context_env)

                    if "condition" in m and not matched_any:
                        ip = skip_ip
                        continue

                    

                    # 2. Process gathered operations sequentially and aggregate signals
                    should_retry = False
                    has_break = False
                    redirect_action = []

                    # 2. Process gathered operations sequentially one after the other
                    # 2. Process pre-execution operations
                    can_proceed, should_retry, has_break, ip_adjustment, redirect_actions, should_continue, executable, should_stop = await self._process_operations(
                        ops_to_run, safe_context_env, next_ip, can_proceed, for_retry=False, step_id=step_id, nodes_retry_times=nodes_retry_times, node_max_retry_times=node_max_retry_times, ip=ip
                    )

                    if should_stop:
                        return
                    

                    if ip_adjustment is not None and should_retry:
                        ip = ip_adjustment

                    # 3. Execute main service action first
                    should_return = False  # 🛠️ FIX: default so re-visiting an already-executed
                                            # node (e.g. returning from a CALL) can't leave this unbound
                    if original_ip not in self.node_execution_state:
                        ip, should_return = await self._execute_node_action(
                            m=m, step_id=step_id, step_log=step_log, can_proceed=can_proceed,
                            dynamic_args=dynamic_args, _crypto_engine=_crypto_engine,
                            combined_context=combined_context, client_id=client_id, task_id=task_id,
                            run_id=run_id, ip=ip, next_ip=next_ip, skip_ip=skip_ip,
                            call_stack=call_stack, steps_completed=steps_completed
                        )
                        self.node_execution_state.add(original_ip)

                    updated_combined_context = {**context_file, **self.context_manager}
                    updated_safe_env = {str(k).replace("-", "_"): v for k, v in updated_combined_context.items()}
                    
                    _, post_ops_to_run, _ = await self._evaluate_node_conditions(m, updated_safe_env)

                    _, should_retry, _, post_ip_adjustment, _ , _ , _= await self._process_operations(
                        post_ops_to_run, safe_context_env, next_ip, can_proceed, for_retry=True, step_id=step_id, nodes_retry_times=nodes_retry_times, node_max_retry_times=node_max_retry_times, ip=ip
                    )

                    if post_ip_adjustment is not None and should_retry:
                        ip = post_ip_adjustment

                    if should_continue:
                        ip = skip_ip
                        continue

                    if should_return and not should_retry:
                        pass
                        #return

                    if should_retry:
                        continue

                    # 📌 OPERATION POINTER FILTERING: once this node's control-flow op
                    # (GOTO/CALL) has been dispatched, don't dispatch it again when we
                    # land back on this same ip (e.g. returning from a subroutine call).
                    # 📌 OPERATION POINTER FILTERING: dispatch control-flow ops (GOTO/CALL)
                    # one at a time, in order. Each time we land back on this node (e.g.
                    # after a subroutine call returns), current_op_idx has advanced by one
                    # (via the RETURN check above), so the NEXT op in the list gets
                    # dispatched - this is what makes multiple sequential `call` ops on a
                    # single node work, instead of only ever firing the first one.
                    # 📌 OPERATION POINTER FILTERING: scan ops_to_run (not redirect_actions -
                    # 🛠️ FIX: redirect_actions only contains entries for ops that actually
                    # produced a GOTO/CALL signal, so it is NOT index-aligned with ops_to_run
                    # whenever a node mixes control-flow ops with regular ops like "execute".
                    # Using redirect_actions[current_op_idx] silently stalls forever the
                    # moment such a mix occurs - e.g. [call X, execute] - because
                    # redirect_actions never grows past length 1 while current_op_idx keeps
                    # advancing. Scan ops_to_run directly instead, skip anything that isn't
                    # itself a call/goto (already executed for its side effect above), and
                    # dispatch only the next real control-flow op found.
                    current_op_idx = self.node_operation_pointers.get(original_ip, 0)
                    remaining_ops = ops_to_run[current_op_idx:]

                    if not remaining_ops:
                        # All operations in this node are exhausted. Clean up and move forward.
                        self.node_operation_pointers.pop(original_ip, None)
                        self.node_execution_state.discard(original_ip)
                        if matched_any and not executable:
                            ip = skip_ip
                        else:
                            ip = next_ip
                        continue

                    redirected_ip = False
                    scan_idx = current_op_idx
                    next_control_flow = None
                    while scan_idx < len(ops_to_run):
                        scan_op = ops_to_run[scan_idx]
                        scan_op_check = scan_op.get("else", scan_op) if isinstance(scan_op, dict) and "else" in scan_op else scan_op
                        scan_action = scan_op_check.get("action") if isinstance(scan_op_check, dict) else None
                        if scan_action in ("goto", "call"):
                            next_control_flow = {
                                "type": scan_action.upper(),
                                "target": scan_op_check.get("target"),
                                "args": scan_op_check.get("input", {}),
                                "call_type": scan_op_check.get("type"),  # preserves "single"/"block" mode
                            }
                            break
                        scan_idx += 1

                    if next_control_flow:
                        self.node_operation_pointers[original_ip] = scan_idx
                        handled, redirected_ip = self._handle_control_flow([next_control_flow], instructions, call_stack, original_ip)
                        if redirected_ip:
                            ip = handled
                            continue

                    if not next_control_flow:
                        # No more control-flow ops left in this node - clean up and move forward.
                        self.node_operation_pointers.pop(original_ip, None)
                        self.node_execution_state.discard(original_ip)
                        if matched_any and not executable:
                            ip = skip_ip
                        else:
                            ip = next_ip
                        continue

                    if has_break:
                        return

                    if ip >= len(instructions):
                        if call_stack:
                            # 📌 CRITICAL FIX: Unpack the tuple correctly
                            return_ip, exit_ip = call_stack.pop()
                            ip = return_ip
                            continue

                    if self.on_success:
                        try:
                            await self._run_lifecycle_block(self.on_success, event_id, run_id, task_id, client_id, _crypto_engine)
                        except Exception as e:
                            logger.error(f"❌ Error in 'on_success' lifecycle block: {e}")
                        
                except Exception as e:
                    error_msg = str(e)
                    step_log.update({"status": "failed", "error": str(e)})
                    # 🛠️ Propagate global crash exceptions into context
                    self.context_manager["_error_message"] = error_msg
                    self.context_manager["_on_error"] = True
                    self.context_manager["_on_success"] = False
                    print(step_log)
                    steps_completed.append(step_log)
                    asyncio.create_task(self._log_finalize_async(run_id, "failed", list(steps_completed), str(e)))
                    raise e

        except Exception as e:
            # Trigger error and complete lifecycle hooks
            if self.on_error:
                try:
                    await self._run_lifecycle_block(self.on_error, event_id, run_id, task_id, client_id, _crypto_engine)
                except Exception as err:
                    logger.error(f"❌ Error in 'on_error' lifecycle block: {err}")
    

        finally:
            # 'on_complete' always runs regardless of success or failure
            if self.on_complete:
                logger.info("🏁 Executing 'on_complete' finalization hooks...")
                try:
                    await self._run_lifecycle_block(self.on_complete, event_id, run_id, task_id, client_id, _crypto_engine)
                except Exception as err:
                    logger.error(f"❌ Error in 'on_complete' lifecycle block: {err}")
        
            await asyncio.to_thread(
                self.sync_to_db, client_id=client_id, task_id=task_id, event_id=event_id
            )
            if is_schedule and not self.should_stop:
                await asyncio.to_thread(
                    self.db.reschedule_after_completion, client_id, task_id
                )