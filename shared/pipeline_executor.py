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
from shared.reg_schema.schemaid import SchemaID
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

        self.loop_scopes = []          # 🔁 List of tuples: (continue_ip, break_ip, node_indices_range)

        # 🎬 Lifecycle blocks storage
        self.on_complete = None
        self.on_error = None
        self.on_success = None

        self.password = None  # 📌 Store password on instance
        self.client_id = None
        self.task_id = None

        self.should_stop = False
        self.check_complete = False
        self.check_success = False
        self.node_fired_conditions = {}

        # 🛠️ FIX: previously run_executor either fell off the end of the while
        # loop (real completion) or silently `return`-ed early when
        # single_node_count hit max_recursion - both look identical to a
        # caller, since neither raises nor communicates anything. Track an
        # explicit status so callers (tests, schedulers, etc.) can tell a
        # genuine completion apart from a forced abort instead of trusting a
        # print statement that fires unconditionally either way.
        self.execution_status = "not_started"
        self.execution_abort_reason = None
        
    async def _log_live_async(self, run_id, steps_snapshot):
        """Non-blocking background helper to write live logs in a separate thread."""
        await asyncio.to_thread(self.db.update_live_logs, run_id, steps_snapshot)

    async def _log_finalize_async(self, run_id, status, steps_snapshot, error_msg):
        """Non-blocking background helper to finalize logs in a separate thread."""
        await asyncio.to_thread(self.db.finalize_log, run_id, status, steps_snapshot, error_msg)

    async def _save_checkpoint_async(self, run_id, checkpoint_data):
        """Non-blocking background helper to save checkpoints in a separate thread."""
        await asyncio.to_thread(self.db.save_checkpoint, run_id, checkpoint_data)

    def check_on_group_condition(self, block, registry):
        condition_map = [
            registry.get_key_from_id(SchemaID.IF),
            registry.get_key_from_id(SchemaID.ELIF), 
            registry.get_key_from_id(SchemaID.ELSE)
        ]
        is_conditional_content = False
        
        # FIX: Properly handle both dict and list inputs to avoid NameError
        if isinstance(block, dict):
            content = [block]
        elif isinstance(block, list):
            content = block
        else:
            content = [block]
                
        for cont in content:
            if isinstance(cont, dict):
                for c in cont.keys():
                    if c in condition_map:
                        is_conditional_content = True
                        break
            if is_conditional_content:
                break
    
        return is_conditional_content

    def _frame_key(self, ip, call_stack):
        """
        🛠️ FIX (stack-aware tracking): node_execution_state, node_operation_pointers,
        and node_fired_conditions used to be keyed by raw node index alone. For a
        self-referential CALL (a node whose subroutine target is itself), every
        recursive re-entry lands on the exact same index, so a flat dict/set can't
        tell "this is a brand-new nested activation" apart from "this is the
        continuation of an outer activation that a nested call is unwinding back
        into" - both collide on the same key. Scoping the key to
        (node_index, len(call_stack)) gives each recursion depth its own isolated
        slot: the outer frame's "did my service already run" flag doesn't leak
        into the inner frame's, and vice versa, so true recursive re-runs work
        without needing to unconditionally wipe state on every CALL dispatch
        (which also had the side effect of erasing node_fired_conditions markers
        that were meant to be one-shot, as with hubspot_update's own base-case rule).
        """
        return (ip, len(call_stack))

    def _resolve_continue(self, current_ip, skip_ip):
        """Check if current_ip belongs to an active loop scope; if so, jump to continue_ip, else go to skip/next."""
        for scope in reversed(self.loop_scopes):
            continue_ip, break_ip, node_indices = scope
            if current_ip in node_indices:
                return continue_ip
        return skip_ip

    def _resolve_break(self, current_ip, next_ip):
        """Check if current_ip belongs to an active loop scope; if so, pop scope and jump to break_ip, else go to next."""
        for idx, scope in enumerate(reversed(self.loop_scopes)):
            continue_ip, break_ip, node_indices = scope
            if current_ip in node_indices:
                actual_idx = len(self.loop_scopes) - 1 - idx
                popped_scope = self.loop_scopes.pop(actual_idx)
                return break_ip
        return next_ip


    

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
        logger.info(f"_cont:                     {_cont}")
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
            
        # 🛠️ FIX: was `for job in list:` - `list` is the bare Python builtin type
        # (never assigned to anything), and `job` was never referenced in the loop
        # body. This is what threw "'type' object is not iterable" - iterating a
        # type itself, not an instance. Looks like leftover code from an earlier
        # version that looped over multiple jobs/manifests; there's only ever one
        # manifest to run here, so just call run_executor directly.
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
                        _context_data=combined_context, _client_name=client_id, _task_id=task_id,
                        _cont=m
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
                    self.context_manager["_on_error"] = True
                    self.context_manager["_on_success"] = False
                    return next_ip, True
                else:
                    step_log.update({"status": "success", "output_preview": str(package)[:100], "duration_ms": duration_ms})
                    steps_completed.append(step_log)
                    asyncio.create_task(self._log_live_async(run_id, list(steps_completed)))
                    asyncio.create_task(self._save_checkpoint_async(run_id, {
                        "ip": ip, "call_stack": call_stack, "context": self.context_manager
                    }))
                    self.context_manager[step_id] = package
                    self.context_manager["_on_error"] = False
                    self.context_manager["_on_success"] = True
                    return next_ip, False
            
            return next_ip, False
        else:
            return skip_ip, False

    async def _evaluate_node_conditions(self, m, safe_context_env, ip, call_stack=None):
        """
        Isolated, reusable helper method to evaluate cascading if/elif/else condition rules 
        against the given context environment and collect associated operations.
        """

        can_proceed = True
        
        # 1. Gather all operations into a list before executing them
        ops_to_run = []
        matched_any = False
        else_rule = {}
        indices_to_pop = []

        # 🛠️ FIX (stack-aware tracking): key fired-condition markers by
        # (node, call_stack depth), not just node index - see _frame_key.
        # call_stack defaults to [] for any caller that doesn't have one handy,
        # which just means "top-level / depth 0", same as before.
        frame_key = self._frame_key(ip, call_stack if call_stack is not None else [])
        fired_indices = self.node_fired_conditions.setdefault(frame_key, set())

        if isinstance(m, list):
            # Called directly with a list of if/elif/else rules (e.g. on_error,
            # on_success, on_complete blocks) - must match a rule to proceed.
            condition_data = m
            can_proceed = False
        elif "condition" in m:
            condition_data = m["condition"]
            can_proceed = False  # Must match a rule (if/elif/else) to proceed
        else:
            condition_data = None
            can_proceed = True  # No condition block on this node => always proceed

        if isinstance(condition_data, list):
            for index, rule in enumerate(condition_data):
                if index in fired_indices:
                    continue
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
                    can_proceed = True
                    rule_ops = rule.get("operations", []) or else_rule
                    if rule_ops:
                        ops_to_run.extend(rule_ops)

                    # Mark this condition rule as consumed so it never fires again
                    fired_indices.add(index)

        # this line is rerun twice it needs to be out of here

        return can_proceed, ops_to_run, matched_any

    async def _process_operations(self, ops_to_run, safe_context_env, next_ip, can_proceed, for_retry=False, step_id=None, nodes_retry_times=None, node_max_retry_times=3, ip=0):
        """Isolated helper to process operations sequentially and gather control flow signals."""
        
        should_retry = False
        has_break = False
        ip_adjustment = None
        redirect_actions = []
        should_continue = False
        has_stop = False
        has_exit = False
        has_ignore = False
        
        if ops_to_run:
            for op in ops_to_run:
                
                op_to_exec = op.get("else") if isinstance(op, dict) and "else" in op else op

                result = await self.execute_operation(op=op_to_exec, context_env=safe_context_env)
            
                if isinstance(result, dict) and "signal" in result:
                    signal = result["signal"]

                    if signal == ActionSignal.SLEEP:
                        duration = self._resolve_sleep_seconds(op_to_exec)
                        logger.info(f"😴 Sleep for {duration}s" + (f" [node {step_id}]" if step_id else ""))
                        if duration > 0:
                            await asyncio.sleep(duration)

                    elif signal == ActionSignal.IGNORE:
                        has_ignore = True

                    elif signal == ActionSignal.STOP:
                        logger.error(f"🛑 Stop signal triggered for task [{self.task_id}]. Executing full teardown...")
                        await execute_piper_stop_v2(
                            client_id=self.client_id, 
                            task_id=self.task_id, 
                            password=self.password
                        )
                        should_stop = True
                        self.should_stop = True
                        
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
                            else:
                                # 🛠️ FIX: this used to fall through to the unconditional
                                # retry below regardless of the counter, so
                                # node_max_retry_times was never actually enforced - a
                                # permanently-failing node retried forever (until the
                                # global single_node_count cap), not just 3 times.
                                logger.warning(
                                    f"🚫 Retry limit reached for node [{step_id}] "
                                    f"({current_retries}/{node_max_retry_times}). Not retrying further."
                                )
                                should_retry = False
                        else:
                            # No retry-count tracking available for this caller (e.g.
                            # nodes_retry_times/step_id not supplied) - fall back to a
                            # single unconditional retry, matching prior behavior for
                            # callers that don't track attempts at all.
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

                    elif signal == ActionSignal.EXIT:
                        has_exit = True
        
        return can_proceed, should_retry, has_break, ip_adjustment, redirect_actions, should_continue, has_stop, has_exit, has_ignore


    @staticmethod
    def _resolve_sleep_seconds(op):
        """Pulls a duration (in seconds) off a `sleep` op, supporting a few unit spellings."""
        if not isinstance(op, dict):
            return 0
        if "seconds" in op:
            return max(0, float(op["seconds"]))
        if "duration" in op:
            return max(0, float(op["duration"]))
        if "minutes" in op:
            return max(0, float(op["minutes"]) * 60)
        if "ms" in op:
            return max(0, float(op["ms"]) / 1000)
        if "milliseconds" in op:
            return max(0, float(op["milliseconds"]) / 1000)
        return 0

    

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
                    next_ip = current_ip + 1

                    # 🔁 Clear execution state and operation pointers for all nodes in the
                    # loop block. 🛠️ FIX (stack-aware tracking): GOTO doesn't push/pop
                    # call_stack - it's a same-depth jump within the current frame - so
                    # every node in the loop body is cleared at the CURRENT call_stack
                    # depth (see _frame_key), not by raw index alone.
                    for loop_idx in range(ip, current_ip + 1):
                        loop_key = self._frame_key(loop_idx, call_stack)
                        self.node_execution_state.discard(loop_key)
                        self.node_operation_pointers.pop(loop_key, None)
                        self.node_fired_conditions.pop(loop_key, None)

                    loop_node_indices = list(range(ip, current_ip + 1))
                    self.loop_scopes.append((current_ip, next_ip, loop_node_indices))
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
                        # 🛠️ FIX: was `exe = subroutine_node.get("execution", {}); if exe:`
                        # - an empty {} is falsy in Python, so a target whose execution
                        # block is empty (or missing entirely, where .get()'s fallback
                        # {} was never attached back to subroutine_node anyway) silently
                        # dropped every injected arg with no error. setdefault ensures
                        # subroutine_node always has a real, attached execution dict to
                        # merge into, whether it started empty, missing, or populated.
                        exe = subroutine_node.setdefault("execution", {})
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
                        exit_ip = raw_skip
                    
                    call_stack.append((return_ip, exit_ip))
                    ip = target_idx

                    # 🛠️ FIX (stack-aware tracking): clear state at the frame the target
                    # is about to run at (post-push depth), not by raw index. Because
                    # frame keys already isolate each depth automatically, this mainly
                    # matters as a defensive reset for the self-recursive case (target
                    # is the same node that's calling it) and for re-entrant subroutines
                    # invoked with stale runtime_node_overrides from a prior run.
                    target_frame_key = self._frame_key(target_idx, call_stack)
                    self.node_execution_state.discard(target_frame_key)
                    self.node_operation_pointers.pop(target_frame_key, None)
                    self.node_fired_conditions.pop(target_frame_key, None)

                    logger.info(f"📞 CALL Subroutine -> Target Node ID: '{target}' at index: {ip} (Exit IP: {exit_ip}, Return IP: {return_ip})")
                    return ip, True
        return None, False
    
    async def run_executor(self, manifest, event_id, run_id, task_id, client_id, 
                            from_trigger=False, _crypto_engine=None, is_schedule: bool = False): 

        self.client_id = client_id
        self.task_id = task_id

        current_version = await asyncio.to_thread(self.db.get_version, client_id)
        
        if self.registry is None:
            self.registry = get_registry_by_version(version=current_version)
        existing_checkpoint = await asyncio.to_thread(self.db.get_checkpoint, run_id)

        self.node_execution_state.clear()
        self.node_operation_pointers.clear()
        self.runtime_node_overrides.clear()
        self.node_iteration_counts.clear()
        self.node_fired_conditions.clear()
        self.execution_status = "running"
        self.execution_abort_reason = None
        
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
        max_recursion = 500
        try:
            while (0 <= ip < len(instructions)) or (call_stack and ip == call_stack[-1][1]):

                if single_node_count >= max_recursion:
                    self.execution_status = "aborted_max_iterations"
                    self.execution_abort_reason = (
                        f"single_node_count exceeded max_recursion={max_recursion} at ip={ip}"
                    )
                    logger.error(f"🛑 {self.execution_abort_reason}")
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
                    # 🛠️ FIX (stack-aware tracking): pop happens first, so len(call_stack)
                    # here is already back to the depth the caller was originally running
                    # at when it dispatched this call - this matches the same frame key
                    # the caller used, so the bump lands on the right slot.
                    return_frame_key = self._frame_key(return_ip, call_stack)
                    self.node_operation_pointers[return_frame_key] = self.node_operation_pointers.get(return_frame_key, 0) + 1
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
                node_on_error = m.get("on_error", [])
                node_on_success = m.get("on_success", [])
                node_on_complete = m.get("on_complete", [])


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

                    # 🛠️ FIX (stack-aware tracking): computed once per node visit, at the
                    # current call_stack depth (before this visit might itself push a new
                    # frame). All bookkeeping for *this* activation of the node uses this
                    # key, so a self-recursive CALL's nested activation gets its own slot
                    # instead of colliding with this one.
                    original_frame_key = self._frame_key(original_ip, call_stack)

                    # 1. Build the active operation stages list dynamically based on execution state
                    operation_stages = []

                    # 1. Pre-execution condition evaluation
                    can_proceed, ops_to_run, matched_any = await self._evaluate_node_conditions(m, safe_context_env, ip, call_stack=call_stack)

                    # Also gather general node-level operations if present
                    if m.get("operations"):
                        ops_to_run.extend(m["operations"])

                    if ops_to_run:
                        operation_stages.append(("pre_execution", ops_to_run))  

                    updated_safe_env = safe_context_env
                    if original_frame_key not in self.node_execution_state:
                        if can_proceed:
                            ip, should_return = await self._execute_node_action(
                                m=m, step_id=step_id, step_log=step_log, can_proceed=can_proceed,
                                dynamic_args=dynamic_args, _crypto_engine=_crypto_engine,
                                combined_context=combined_context, client_id=client_id, task_id=task_id,
                                run_id=run_id, ip=ip, next_ip=next_ip, skip_ip=skip_ip,
                                call_stack=call_stack, steps_completed=steps_completed
                            )
                            self.node_execution_state.add(original_frame_key)

                            updated_combined_context = {**context_file, **self.context_manager}
                            updated_safe_env = {str(k).replace("-", "_"): v for k, v in updated_combined_context.items()}
                        

                    

                    can_proceed, post_ops_to_run, matched_any = await self._evaluate_node_conditions(m, updated_safe_env, ip, call_stack=call_stack)
                    
                    if post_ops_to_run:
                        operation_stages.append(("post_execution", post_ops_to_run))


                    if self.context_manager.get("_on_success"):
                        if node_on_success:
                            is_condition = self.check_on_group_condition(node_on_success, self.registry)
                            if is_condition:
                                can_proceed, check_node_on_success, matched_any = await self._evaluate_node_conditions(node_on_success, safe_context_env, ip, call_stack=call_stack)
                            else:
                                check_node_on_success = node_on_success
                            operation_stages.append(("on_success", check_node_on_success))
                        else:
                            self.check_success = True

                    if node_on_complete:
                        is_condition = self.check_on_group_condition(node_on_complete, self.registry)
                        if is_condition:
                            can_proceed, check_node_on_complete, matched_any = await self._evaluate_node_conditions(node_on_complete, safe_context_env, ip, call_stack=call_stack)
                        else:
                            check_node_on_success = node_on_complete
                        operation_stages.append(("on_complete",  check_node_on_complete))

                    # 2. Process all stages uniformly in a single clean loop
                    stage_interrupted = False

                    redirect_actions = []
    
                    for stage_name, ops in operation_stages:
                        can_proceed, should_retry, has_break, ip_adjustment, stage_redirects, should_continue, has_stop, has_exit, has_ignore = await self._process_operations(
                            ops, updated_safe_env, next_ip, can_proceed, step_id=step_id, 
                            nodes_retry_times=nodes_retry_times, node_max_retry_times=node_max_retry_times, ip=ip
                        )
                        
                        if stage_redirects:
                            redirect_actions.extend(stage_redirects)

                        if has_stop:
                            self.execution_status = "stopped"
                            return

                        if has_exit:
                            logger.info(f"🚪 Exit signal triggered for task [{self.task_id}]. Ending this run.")
                            self.execution_status = "exited"
                            return

                        if has_break:
                            ip = self._resolve_break(original_ip, next_ip)
                            stage_interrupted = True
                            break

                        if should_continue:
                            ip = self._resolve_continue(original_ip, skip_ip)
                            stage_interrupted = True
                            break

                        if stage_name == "on_error" and should_retry:
                            if ip_adjustment is not None:
                                ip = ip_adjustment
                            stage_interrupted = True
                            break

                        # 🙈 IGNORE (used inline in a node's own operations, e.g. reacting to
                        # `_on_error`): suppress the error this pass just saw - clear the error
                        # flags so downstream conditions don't treat this node as failed - and
                        # keep going. Still logged as failed in step_log/steps_completed already.

                        if stage_name == "on_error" and has_ignore:
                            logger.info(f"🙈 Ignore triggered for node [{step_id}]. Suppressing error, continuing.")
                            self.context_manager["_on_error"] = False
                            self.context_manager["_on_success"] = True

                    if stage_interrupted:
                        continue

                
                    if ip >= len(instructions):
                        if call_stack:
                            # 📌 CRITICAL FIX: Unpack the tuple correctly
                            return_ip, exit_ip = call_stack.pop()
                            ip = return_ip
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
                    current_op_idx = self.node_operation_pointers.get(original_frame_key, 0)
                    remaining_ops = redirect_actions[current_op_idx:]

                    if self.context_manager.get("_on_error"):
                        raise RuntimeError(
                            self.context_manager.get(f"_error_message_{step_id}")
                            or self.context_manager.get("_error_message")
                            or f"node [{step_id}] failed"
                        )

                    if not remaining_ops:
                        # All operations in this node are exhausted. Clean up and move forward.
                        self.node_operation_pointers.pop(original_frame_key, None)
                        self.node_execution_state.discard(original_frame_key)
                        # 🛠️ UPDATED: If condition exists and nothing matched, skip. Otherwise, proceed to next.
                        if "condition" in m and not matched_any:
                            ip = skip_ip
                        else:
                            ip = next_ip
                        continue

                    redirected_ip = False
                    scan_idx = current_op_idx
                    next_control_flow = None
                    while scan_idx < len(redirect_actions):
                        scan_op = redirect_actions[scan_idx]
                        next_control_flow = scan_op
                        scan_idx += 1
                        break

                    if next_control_flow:
                        self.node_operation_pointers[original_frame_key] = scan_idx
                        handled, redirected_ip = self._handle_control_flow([next_control_flow], instructions, call_stack, original_ip)
                        if redirected_ip:
                            # 🛠️ FIX: GOTO is a one-way jump - nothing returns to this node
                            # via call_stack, so the pointer bump above goes stale. If we
                            # revisit this same node later (e.g. looping back around to it
                            # again), the stale pointer against the freshly-rebuilt
                            # (length-1) redirect_actions list makes it look "exhausted" and
                            # silently swallows the GOTO on the next pass. Only CALL expects
                            # a future return (via call_stack) to resume at the advanced
                            # pointer, so only clear it for GOTO.
                            if next_control_flow.get("type") == "GOTO":
                                self.node_operation_pointers.pop(original_frame_key, None)
                                self.node_execution_state.discard(original_frame_key)
                            ip = handled
                            continue

                    if not next_control_flow:
                        # No more control-flow ops left in this node - clean up and move forward.
                        self.node_operation_pointers.pop(original_frame_key, None)
                        self.node_execution_state.discard(original_frame_key)
                        if "condition" in m and not matched_any:
                            ip = skip_ip
                        else:
                            ip = next_ip
                        continue
                                           
                except Exception as e:
                    error_msg = str(e)
                    step_log.update({"status": "failed", "error": str(e)})

                    
                    # Store error details in context manager
                    self.context_manager["_error_message"] = error_msg
                    self.context_manager[f"_error_message_{step_id}"] = error_msg
                    self.context_manager["_on_error"] = True
                    self.context_manager["_on_success"] = False
                    
                    steps_completed.append(step_log)
                    asyncio.create_task(self._log_live_async(run_id, list(steps_completed)))

                    # 🛡️ Catch and process local node 'on_error' operations before crashing
                    if node_on_error:
                        is_condition = self.check_on_group_condition(node_on_error, self.registry)
                        if is_condition:
                            can_proceed, check_node_on_error, matched_any = await self._evaluate_node_conditions(node_on_error, safe_context_env, ip, call_stack=call_stack)
                        else:
                            check_node_on_error = node_on_error
                        logger.info(f"⚠️ Exception caught in node [{step_id}]. Executing local 'on_error' block...")
                        _, should_retry, has_break, ip_adjustment, stage_redirects, should_continue, has_stop, has_exit, has_ignore = await self._process_operations(
                            check_node_on_error, safe_context_env, next_ip, can_proceed=False, step_id=step_id, 
                            nodes_retry_times=nodes_retry_times, node_max_retry_times=node_max_retry_times, ip=ip
                        )
                        
                        if has_stop:
                            self.execution_status = "stopped"
                            return

                        if has_exit:
                            logger.info(f"🚪 Exit signal triggered during node [{step_id}] error recovery.")
                            self.execution_status = "exited"
                            return

                        if has_ignore:
                            logger.info(f"🙈 Ignore triggered in 'on_error' for node [{step_id}]. Suppressing crash.")
                            self.context_manager["_on_error"] = False
                            self.context_manager["_on_success"] = True
                            ip = next_ip
                            continue

                        # 🛠️ FIX: Handle control-flow redirects (such as CALL / GOTO) emitted by on_error operations
                        if stage_redirects:
                            handled, redirected_ip = self._handle_control_flow(stage_redirects, instructions, call_stack, original_ip)
                            if redirected_ip:
                                ip = handled
                                continue

                        if should_retry:
                           
                            # 🛠️ FIX: node_execution_state marks this node as "already ran
                            # its service action" the moment _execute_node_action runs, and
                            # nothing was clearing that mark on retry. Every retry pass was
                            # therefore skipping _execute_node_action entirely (the real
                            # service call never fired again) while still burning down the
                            # retry counter, until retries were exhausted on a node that had
                            # only actually executed once. Discard the mark so the retried
                            # pass re-invokes the service action.
                            self.node_execution_state.discard(original_frame_key)
                            # 🛠️ FIX: the on_error rule's "if" (e.g. iterations < 3) gets
                            # marked as fired in node_fired_conditions the first time it
                            # matches, and that mark is keyed by (ip, call_stack) - which
                            # stays identical across repeated failures of the same node, so
                            # it was never re-evaluated past the first retry. Clear it so the
                            # on_error condition can match again on the next failure.
                            self.node_fired_conditions.pop(self._frame_key(ip, call_stack), None)
                            if ip_adjustment is not None:
                                ip = ip_adjustment
                            continue

                        if should_continue:
                            ip = self._resolve_continue(original_ip, skip_ip)
                            stage_interrupted = True
                            break

                    # Fallback: if no local handler catches it or recovery fails, finalize and raise
                    print(step_log)
                    asyncio.create_task(self._log_finalize_async(run_id, "failed", list(steps_completed), str(e)))
                    raise e

            # 🛠️ FIX: reaching this point means the while loop exited by its own
            # condition going false (ip walked off the end / call_stack drained) -
            # the only other ways out of the loop are the early `return`s above
            # (which already set an "aborted_*" status) or an exception (caught
            # below). So this is the one place it's safe to call it "completed".
            self.execution_status = "completed"

            if self.on_success:
                try:
                    await self._run_lifecycle_block(self.on_success, event_id, run_id, task_id, client_id, _crypto_engine)
                except Exception as e:
                    logger.error(f"❌ Error in 'on_success' lifecycle block: {e}")

        except Exception as e:
            self.execution_status = "failed"
            self.execution_abort_reason = str(e)
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