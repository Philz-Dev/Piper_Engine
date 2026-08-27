import re
import inspect
import os
import shared.helpers
from shared.expression_manager import ExpressionEngine
from shared.tools import parse_pipe_args, unescape_dsl_content
import shlex

class ExpressionMixin:
    def resolve_bracketed_expression(self, expression: str, context_env: dict) -> any:
        match = re.match(r"(\w+)\((.*)\)", expression.strip())
        if not match:
            return self.resolve_tokens(expression, context_env)
        
        func_name, args_str = match.groups()
        args = self.split_args_smart(args_str)
        resolved_args = [self.parse_and_apply_pipes(arg, context_env) for arg in args]
        
        func = self.get_dynamic_function_registry().get(func_name)
        if func:
            return func(*resolved_args)
        return expression

    def resolve_tokens(self, data: str, context_env: dict) -> str:
        data = unescape_dsl_content(data)
        pattern = r"\$([a-zA-Z0-9_.]+)"
        def replacer(match):
            path = match.group(1)
            keys = path.split('.')
            val = context_env
            for k in keys:
                try:
                    if isinstance(val, dict):
                        val = val.get(k)
                    elif isinstance(val, (list, tuple)):
                        idx = int(k)
                        val = val[idx]
                    else:
                        return f"${path}"
                    if val is None:
                        return f"${path}"
                except (ValueError, IndexError, AttributeError):
                    return f"${path}"
            return str(val)
        return re.sub(pattern, replacer, data)
    
    # 1. PUBLIC ENTRY POINT
    def parse_and_apply_pipes(self, value_str: str, context_env: dict) -> any:
        """The main entry point for processing any manifest string."""
        
        # If it has templates, resolve them first.
        if "{{" in value_str:
            return self.resolve_templates(value_str, context_env)
        
        # If no templates, go straight to logic resolution.
        return self._process_logic(value_str, context_env)
    
    def resolve_templates(self, text: str, context_env: dict) -> str:
        pattern = r"\{\{(.*?)\}\}"
        def replacer(match):
            expression_content = match.group(1).strip()
            # We call the logic worker here, NOT the public entry point
            return str(self._process_logic(expression_content, context_env))
        return re.sub(pattern, replacer, text)

    def _process_logic(self, value_str: str, context_env: dict) -> any:
        hydrated_str = self.resolve_tokens(value_str, context_env)
        if "(" in hydrated_str and hydrated_str.strip().endswith(")"):
            if re.match(r"^\w+\(.*\)$", hydrated_str.strip()):
                return self.resolve_bracketed_expression(hydrated_str, context_env)

        if "|" not in hydrated_str:
            return hydrated_str

        parts = [p.strip() for p in re.split(r'(?<!\\)\|', hydrated_str)]
        current_value = self.resolve_tokens(parts[0], context_env)
        
        try:
            func_registry = self.get_dynamic_function_registry()
            for pipe in parts[1:]:
                pipe = pipe.strip()
                if "(" in pipe:
                    match = re.match(r"(\w+)\((.*)\)", pipe)
                    if match:
                        func_name, args_str = match.groups()
                        args = [self.parse_and_apply_pipes(a.strip(), context_env) for a in self.split_args_smart(args_str)]
                        func = func_registry.get(func_name)
                        if func:
                            pos_args, kw_args = parse_pipe_args(args)
                            current_value = func(current_value, *pos_args, **kw_args)
                else:
                    try: tokens = shlex.split(pipe)
                    except ValueError: tokens = pipe.split()
                        
                    if not tokens: continue
                    func_name, args = tokens[0], tokens[1:]
                    func = func_registry.get(func_name)
                    if func:
                        pos_args, kw_args = parse_pipe_args(args)
                        current_value = func(current_value, *pos_args, **kw_args)
            return current_value
        except Exception as e:
            print(f"Error parsing expression '{hydrated_str}': {e}")
            return hydrated_str

    def get_dynamic_function_registry(self) -> dict:
        target_module = shared.helpers
        target_file_path = os.path.realpath(inspect.getfile(target_module))
        return {name: func for name, func in inspect.getmembers(target_module, inspect.isfunction) 
                if os.path.realpath(inspect.getfile(func)) == target_file_path}

    def execute_expression_functions(self, package: any, context_env: dict) -> any:
        def walk_and_resolve(node):
            if isinstance(node, dict): return {k: walk_and_resolve(v) for k, v in node.items()}
            if isinstance(node, list): return [walk_and_resolve(item) for item in node]
            if isinstance(node, str): return self.parse_and_apply_pipes(node, context_env=context_env)
            return node
        return walk_and_resolve(package)

    def eval_condition(self, condition: any, context_env: dict) -> bool:
    
        if isinstance(condition, bool): 
            return condition
        
        # Hydrate tokens (replace $variable.path with its actual value from context_env)
        hydrated_condition = self.resolve_tokens(str(condition), context_env)
        
        engine = ExpressionEngine(context_env)
        try: 
            return bool(engine.evaluate(str(hydrated_condition)))
        except Exception as e: 
            print(f"❌ Evaluation error in [{condition}] (hydrated: [{hydrated_condition}]): {e}")
            return False