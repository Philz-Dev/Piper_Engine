import copy
import uuid
from shared.system_functions import PipelineGlobalExit, ActionSignal
from shared.encryption_manager import get_encryption_key

class ControllerMixin:
    def deep_merge(self, base: dict, overrides: dict):
        for key, value in overrides.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self.deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    async def execute_operation(self, op: dict, context_env: dict):
        action_name = op.get("action")
        if action_name in ["goto", "break", "call", "retry", "continue", "execute"]:
            return self.handle_control_flow(action_name, op)
        func = self.get_dynamic_function_registry().get(action_name)
        if not func: raise ValueError(f"Action '{action_name}' not found.")
        kwargs = {k: self.resolve_tokens(v, context_env) if isinstance(v, str) else v 
                  for k, v in op.items() if k != "action"}
        return await func(**kwargs)

    async def process_input_logic(self, input_list: list, context_env: dict) -> list:
        if not isinstance(input_list, list): return input_list
        final_input_list = []
        for entry in input_list:
            if not isinstance(entry, dict):
                final_input_list.append(entry)
                continue
            new_entry = {}
            for key, content in entry.items():
                if not isinstance(content, dict) or ("condition" not in content and "operations" not in content):
                    new_entry[key] = content
                    continue
                value = content.get("value")
                condition_data = content.get("condition")
                operations_data = content.get("operations")
                if condition_data:
                    if isinstance(condition_data, list):
                        for rule in condition_data:
                            if self.eval_condition(condition=rule.get("if", True), context_env=context_env) or "else" in rule:
                                if "operations" in rule:
                                    for op in rule["operations"]:
                                        op_to_exec = op.get("else") if "else" in op else op
                                        await self.execute_operation(op=op_to_exec, context_env=context_env)
                                if "value" in rule: value = rule["value"]
                                break
                if operations_data:
                    for op in operations_data:
                        op_to_exec = op.get("else") if "else" in op else op
                        await self.execute_operation(op=op_to_exec, context_env=context_env)
                new_entry[key] = value
            final_input_list.append(new_entry)
        return final_input_list

    def handle_control_flow(self, action_name, op):
        if action_name == "break": return {"signal": ActionSignal.BREAK}
        if action_name == "goto": return {"signal": ActionSignal.GOTO, "target": op.get("target")}
        if action_name == "call": return {"signal": ActionSignal.CALL, "target": op.get("target"), "type": op.get("type"), "args": op.get("input", {})}
        if action_name == "continue": return {"signal": ActionSignal.CONTINUE}
        if action_name == "retry": return {"signal": ActionSignal.RETRY}
        if action_name == "execute": return {"signal": ActionSignal.EXECUTE}
        return None

    def sync_to_db(self, client_id, task_id, event_id=None):
        if not event_id: event_id = f"evt_{uuid.uuid4().hex[:8]}"
        current_data = self.db.get_context(client_id=client_id, task_id=task_id, event_id=event_id) or {}
        combined_context = {**current_data, **self.context_manager}
        self.db.save_context(client_id, task_id, combined_context, event_id=event_id)

    async def call_run_executor(self, event_id, _cont, password, run_id, task_id, client_id, from_trigger: bool=False, is_schedule: bool=False):
        self.context_manager = {}
        _crypto_engine = get_encryption_key(password=password)
        fresh_manifest_container = copy.deepcopy(_cont)
        manifest = fresh_manifest_container["Pipeline"] if isinstance(fresh_manifest_container, dict) and "Pipeline" in fresh_manifest_container else fresh_manifest_container
        await self.run_executor(
            manifest=manifest, event_id=event_id, run_id=run_id, task_id=task_id,
            client_id=client_id, from_trigger=from_trigger, _crypto_engine=_crypto_engine, is_schedule=is_schedule
        )