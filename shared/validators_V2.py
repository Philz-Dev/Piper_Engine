from shared.tools import retrieve_file, inspect_function, crawler, missing_field, get_suggestion, get_all_dsl_keys_v2, get_line_number, resolve_service_instruction, check_key_matches, input_manager
import os
import inspect
from shared.unpacked_data import UnZip
from functools import partial
from typing import Callable
import ast
import re
import shared.helpers as helpers
from typing import Dict, List, Any, Optional
from shared.registry_V2 import PiperRegistry, ValidationState 
from shared.reg_schema.schemaid import SchemaID
import inspect
from typing import Dict, Any
from shared.tools import parse_pipe_args
import re
import inspect
import shared.system_functions as system_functions
from shared.tools import split_args_smart, unescape_dsl_content # Import the shared utility
import shlex  # Add this to your imports

def validate_dependencies_with_prefix(section_key: str, content: Any, registry: PiperRegistry, state: ValidationState, line_info: str):
    """
    Checks dependencies for a section. Safely handles both Dict and List content types.
    """

    # 1. Defensive Check: Ensure content is a dictionary
    if not isinstance(content, dict):
        # If content is a list (CommentedSeq), we cannot resolve a prefix 
        # from a dictionary key. Log a warning or return safely.
        return

    # 2. Safe retrieval of value
    # Use .get() to prevent KeyErrors
    raw_val = content.get(section_key)
    
    # Ensure the value is a string before attempting .split()
    if not isinstance(raw_val, str):
        # If the value is None or not a string, we cannot determine a prefix
        prefix = None
    else:
        # Determine prefix safely
        # Check if the registry has a prefix map for this key
        if hasattr(registry, 'has_prefix') and registry.has_prefix(key=section_key):
            prefix = raw_val.split(".")[0]
            
            # Verify prefix existence in registry map
            if prefix not in registry.prefix_map.get(section_key, []):
                # Fallback to native namespace
                prefix = registry._raw.get(section_key, {}).get("native_namespace")
        else:
            prefix = None

    # 3. Get the appropriate rules
    if prefix:
        sibling_rules = registry.get_service_dependency_rules(section_key, prefix)
    else:
        sibling_rules = registry.get_dependency_rules(section_key)

    if not sibling_rules:
        return
    
    for id_map_name, rule in sibling_rules.items():
        map_name = registry.get_key_from_id(target_id=id_map_name)
        
        # Use .get() if 'rule' is a dict, or getattr() if it is a class instance.
        # Since your registry returns a dict, use .get()
        is_mandatory = rule.get('mandatory', False) if isinstance(rule, dict) else getattr(rule, 'mandatory', False)
        is_supported = rule.get('support', False) if isinstance(rule, dict) else getattr(rule, 'support', False)
        
        if is_mandatory and map_name not in content:
            state.add_error(
                f"in Line {line_info}: Missing mandatory dependency '{map_name}' "
                f"for {section_key} (Prefix: {prefix if prefix else 'None'})  "
            )

        if not is_supported and map_name in content:
            state.add_error(
                f"in Line {line_info}: this service does not support the key '{map_name}' "
                f"for {section_key} (Prefix: {prefix if prefix else 'None'}) "
                f"in Line {get_line_number(content, map_name)}"
            )

def main_validator(name: str, dsl_file: Dict[str, Any], registry, state):
    print(f"--- Starting Pre-Flight Validation for: {name} ---")
    get_all_dsl_keys_v2(dsl_file=dsl_file, registry=registry, state=state)
    bound_validator = partial(check_step_validity, registry=registry, state=state)
    hook = {
        dict: bound_validator, 
        list: bound_validator,
        "primitive": bound_validator
    }
    unzip = UnZip()
    unzip.unpack_bulk_data(content=dsl_file, hooks=hook)
    allowed_main_ids = registry.get_allowed_ids("__main__")

    for section, content in dsl_file.items():
        # Skip metadata keys like 'version'
        # 2. Structural Placement Check
        line_info = get_line_number(content, section)

        validate_dependencies_with_prefix(
            section_key=section, 
            content=dsl_file, # Assuming dsl_file is the sibling scope
            registry=registry, 
            state=state, 
            line_info=line_info
        )
        if isinstance(content, str):
            validate_expression(
                expr_content=content, 
                line_info=line_info, 
                state=state
            )

        section_id = registry.id_map.get(section)
        if section_id is None:
             state.add_error(f"Unknown top-level section: '{section}'")
             continue
        if section_id == SchemaID.VERSION:
            continue

        # Check if this section is allowed in __main__
        if section in registry.list_of_keys and section_id not in allowed_main_ids:
            state.add_error(
                f"in Line {line_info}: [Top-Level] '{section}' is a utility key and cannot be used as a top-level section."
                f"Allowed sections are: {[id.name for id in allowed_main_ids]}"
            )
            continue
    
        # 2. Check for Structural Placement (Top-Level Authorization)
        if registry.id_map.get(section) in registry.list_of_keys and not registry.is_section_manager(section):
            line_info = get_line_number(content, section)
            state.add_error(f"in Line {line_info}: [Top-Level] '{section}' is a utility key and cannot be used as a top-level section.")
            continue
         # 4. Blind Dispatch to Specialist
        specialist = registry.get_validator(section)
        if specialist:
            # Specialist handles deep-logic validation (IDs, webhooks, etc.)
            specialist(section, content, registry, state)

    print(state.errors)
    return state.errors

def validate_expression_v2(expr_content: str, line_info: str, state: ValidationState, context_ref: str = ""):
    """
    Orchestrates the validation of all {{...}} blocks within a string.
    """
    if not isinstance(expr_content, str):
        return

    # Find all occurrences of {{ ... }}
    matches = re.findall(r"\{\{(.*?)\}\}", expr_content)
    
    for expr in matches:
        _validate_single_pipe_chain(expr.strip(), line_info, state, context_ref)

def validate_expression(expr_content: str, line_info: str, state: ValidationState, context_ref: str = ""):
    if not isinstance(expr_content, str):
        return

    # Regex: Matches {{...}} only if NOT preceded by \
    # We use re.DOTALL to ensure it captures multi-line expressions if needed
    pattern = r"(?<!\\)\{\{(.*?)(?<!\\)\}\}"
    matches = re.findall(pattern, expr_content, re.DOTALL)
    
    for expr in matches:
        # Before validating, we "clean" the expression of escape characters
        # so logic sees '{{ $env.var }}' instead of '{{ \$env.var }}'
        cleaned_expr = unescape_dsl_content(expr.strip())
        _validate_single_pipe_chain(cleaned_expr, line_info, state, context_ref)

def _validate_single_pipe_chain(pipe_chain: str, line_info: str, state: ValidationState, context_ref: str):
    """
    Validates a single chain: '$variable | func1 | func2(args) | func3 arg1 arg2'
    Supports recursive validation for nested functions: func1(func2(arg))
    """
    # 1. FIXED: Split by | but not \| using regex
    parts = [p.strip() for p in re.split(r'(?<!\\)\|', pipe_chain)]
    if not parts:
        return

    # 1. Validate Source
    source = parts[0]
    # Note: If source can have escapes, you might unescape this too, 
    # but typically sources like $env.var are literal keys.
    if not (source.startswith("$") or source.startswith("'") or source.startswith('"')):
        state.add_error(f"[{context_ref}] Line {line_info}: Invalid source '{source}'. Must start with '$' or be a literal.")

    # 2. Nested validator to handle recursive function calls
    def validate_call(segment: str):
        segment = segment.strip()
        # Basic check to see if it is a function call
        if "(" in segment and segment.endswith(")"):
            match = re.match(r"^([\w.]+)\((.*)\)$", segment)
            if not match:
                state.add_error(f"[{context_ref}] Line {line_info}: Invalid function syntax '{segment}'")
                return
            
            func_name, args_raw = match.groups()
            func = getattr(helpers, func_name, None)
            if not func:
                state.add_error(f"[{context_ref}] Line {line_info}: Function '{func_name}' not found in system functions")
                return

            # RECURSION: Get arguments and validate them
            arg_list = split_args_smart(args_raw)
            for arg in arg_list:
                # UNESCAPE: Clean the arg of escapes for validation purposes
                clean_arg = unescape_dsl_content(arg.strip())
                # If the argument is another function, recurse
                if "(" in clean_arg and clean_arg.endswith(")"):
                    validate_call(clean_arg)
            
            # Validate contract for the current function
            pos_args, parsed_kwargs = parse_pipe_args(arg_list)
            contract = inspect_function(func=func)

            if len(pos_args) > len(contract):
                state.add_error(f"[{context_ref}] Line {line_info}: Too many arguments for '{func_name}'. Expected max {len(contract)}, got {len(pos_args)}.")
            
            for key in parsed_kwargs.keys():
                if key not in contract:
                    state.add_error(f"[{context_ref}] Line {line_info}: Argument '{key}' is invalid for '{func_name}'.")
            
            for param_name, info in contract.items():
                is_mandatory = info.get("default") is inspect.Parameter.empty
                if is_mandatory and param_name not in parsed_kwargs:
                    state.add_error(f"[{context_ref}] Line {line_info}: Missing mandatory argument '{param_name}' for '{func_name}'.")

    # 3. Validate Pipe Functions
    for pipe_segment in parts[1:]:
        # UNESCAPE: Clean the segment of escapes before processing
        pipe_segment = unescape_dsl_content(pipe_segment.strip())
        
        # Determine Mode
        if "(" in pipe_segment:
            # --- MODE: FUNCTION-STYLE (Calls our recursive helper) ---
            validate_call(pipe_segment)
        else:
            # --- MODE: CLI-STYLE ---
            try:
                tokens = shlex.split(pipe_segment)
            except ValueError:
                tokens = pipe_segment.split()
                
            if not tokens:
                continue
            func_name = tokens[0]
            arg_list = tokens[1:] 

            # Check Function Existence
            func = getattr(helpers, func_name, None)
            if not func:
                state.add_error(f"[{context_ref}] Line {line_info}: Function '{func_name}' not found in system functions")
                continue
                
            # Parse arguments
            pos_args, parsed_kwargs = parse_pipe_args(arg_list)
            contract = inspect_function(func=func)

            if len(pos_args) > len(contract):
                state.add_error(f"[{context_ref}] Line {line_info}: Too many arguments for '{func_name}'. Expected max {len(contract)}, got {len(pos_args)}.")
            
            # Check for Invalid Arguments
            for key in parsed_kwargs.keys():
                if key not in contract:
                    state.add_error(f"[{context_ref}] Line {line_info}: Argument '{key}' is invalid for '{func_name}'.")

            for param_name, info in contract.items():
                if info.get("default") is inspect.Parameter.empty:
                    # If the user didn't explicitly provide this argument, assume it's filled by the pipe
                    if param_name not in parsed_kwargs:
                        parsed_kwargs[param_name] = "PIPED_INPUT"
                    break  # We only automatically satisfy the first positional input
            
            # Check for Missing Mandatory Arguments
            for param_name, info in contract.items():
                is_mandatory = info.get("default") is inspect.Parameter.empty
                if is_mandatory and param_name not in parsed_kwargs:
                    state.add_error(f"[{context_ref}] Line {line_info}: Missing mandatory argument '{param_name}' for '{func_name}'.")

def _validate_single_pipe_chain_v2(pipe_chain: str, line_info: str, state: ValidationState, context_ref: str):
    """
    Validates a single chain: '$variable | func1 | func2(args) | func3 arg1 arg2'
    Supports recursive validation for nested functions: func1(func2(arg))
    """
    parts = [p.strip() for p in pipe_chain.split('|')]
    if not parts:
        return

    # 1. Validate Source
    source = parts[0]
    if not (source.startswith("$") or source.startswith("'") or source.startswith('"')):
        state.add_error(f"[{context_ref}] Line {line_info}: Invalid source '{source}'. Must start with '$' or be a literal.")

    # NEW: Nested validator to handle recursive function calls
    def validate_call(segment: str):
        segment = segment.strip()
        # Basic check to see if it is a function call
        if "(" in segment and segment.endswith(")"):
            match = re.match(r"^([\w.]+)\((.*)\)$", segment)
            if not match:
                state.add_error(f"[{context_ref}] Line {line_info}: Invalid function syntax '{segment}'")
                return
            
            func_name, args_raw = match.groups()
            func = getattr(helpers, func_name, None)
            if not func:
                state.add_error(f"[{context_ref}] Line {line_info}: Function '{func_name}' not found in system functions")
                return

            # RECURSION: Get arguments and validate them
            arg_list = split_args_smart(args_raw)
            for arg in arg_list:
                # If the argument is another function, recurse
                if "(" in arg and arg.strip().endswith(")"):
                    validate_call(arg.strip())
            
            # Validate contract for the current function
            pos_args, parsed_kwargs = parse_pipe_args(arg_list)
            contract = inspect_function(func=func)

            if len(pos_args) > len(contract):
                state.add_error(f"[{context_ref}] Line {line_info}: Too many arguments for '{func_name}'. Expected max {len(contract)}, got {len(pos_args)}.")
            # --- FIXED LOGIC END ---
            
            for key in parsed_kwargs.keys():
                if key not in contract:
                    state.add_error(f"[{context_ref}] Line {line_info}: Argument '{key}' is invalid for '{func_name}'.")
            
            for param_name, info in contract.items():
                is_mandatory = info.get("default") is inspect.Parameter.empty
                if is_mandatory and param_name not in parsed_kwargs:
                    state.add_error(f"[{context_ref}] Line {line_info}: Missing mandatory argument '{param_name}' for '{func_name}'.")

    # 2. Validate Pipe Functions
    for pipe_segment in parts[1:]:
        pipe_segment = pipe_segment.strip()
        
        # Determine Mode
        if "(" in pipe_segment:
            # --- MODE: FUNCTION-STYLE (Calls our recursive helper) ---
            validate_call(pipe_segment)
        else:
            # --- MODE: CLI-STYLE ---
            try:
                tokens = shlex.split(pipe_segment)
            except ValueError:
                tokens = pipe_segment.split()
                
            if not tokens:
                continue
            func_name = tokens[0]
            arg_list = tokens[1:] 

            # Check Function Existence
            func = getattr(helpers, func_name, None)
            if not func:
                state.add_error(f"[{context_ref}] Line {line_info}: Function '{func_name}' not found in system functions")
                continue
                
            # Parse arguments
            pos_args, parsed_kwargs = parse_pipe_args(arg_list)
            contract = inspect_function(func=func)

            if len(pos_args) > len(contract):
                state.add_error(f"[{context_ref}] Line {line_info}: Too many arguments for '{func_name}'. Expected max {len(contract)}, got {len(pos_args)}.")
            
            # Check for Invalid Arguments
            for key in parsed_kwargs.keys():
                if key not in contract:
                    state.add_error(f"[{context_ref}] Line {line_info}: Argument '{key}' is invalid for '{func_name}'.")

            for param_name, info in contract.items():
                if info.get("default") is inspect.Parameter.empty:
                    # If the user didn't explicitly provide this argument, assume it's filled by the pipe
                    if param_name not in parsed_kwargs:
                        parsed_kwargs[param_name] = "PIPED_INPUT"
                    break  # We only automatically satisfy the first positional input
            
            # Check for Missing Mandatory Arguments
            for param_name, info in contract.items():
                is_mandatory = info.get("default") is inspect.Parameter.empty
                if is_mandatory and param_name not in parsed_kwargs:
                    state.add_error(f"[{context_ref}] Line {line_info}: Missing mandatory argument '{param_name}' for '{func_name}'.")

def get_service_keys(value, registry, key, state, step_ref):
    prefix = registry.service_prefix(service_key=key, service_value=value)
    config_keys = {}
    handler = registry.prefix_executor(key=key, prefix_name=prefix)
    
    if not handler:
        state.add_error(f"[{step_ref}] Registry Error: No handler for '{prefix}' mode.")
        return config_keys
        
    inspect = inspect_function(func=handler)

    for ky, vl in inspect.items():
        # Set mandatory status correctly based on the 'default' value
        is_mandatory = not vl.get("default", False)
        config_keys[ky] = {"mandatory": is_mandatory}
    
    return config_keys

def get_action_keys(value, registry, key, state, step_ref):
    """
    Retrieves the required arguments for an 'action' by inspecting 
    the underlying Python function signature.
    """
    config_keys = {}
    
    # 1. Retrieve the handler from the registry
    # Ensure this matches the method added to PiperRegistry
    handler = registry.get_action_handler(value)
    
    if not handler:
        state.add_error(f"[{step_ref}] Registry Error: No action handler found for '{value}'.")
        return config_keys
        
    # 2. Inspect the Python function signature
    # (Assuming inspect_function is available from your tools import)
    contract = inspect_function(func=handler)

    # 3. Build the config keys mapping
    for arg_name, info in contract.items():
        # Mandatory if the argument has no default value (inspect.Parameter.empty)
        is_mandatory = (info.get("default") is inspect.Parameter.empty)
        config_keys[arg_name] = {"mandatory": is_mandatory}
    
    return config_keys

def validate_condition(section_key, line_info, content, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func, **kwargs) -> None:
    if not isinstance(content, list):
        state.add_error(f"in Line {line_info}: {step_ref}: Condition must be a list of blocks.")
        return

    # Track validation state
    seen_if = False
    seen_else = False

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            state.add_error(f"in Line {line_info}: {step_ref}: Item at index {i} is not a valid block.")
            continue

        # Check which keys exist in this block
        has_if = registry.get_key_from_id(SchemaID.IF) in block
        has_elif = registry.get_key_from_id(SchemaID.ELIF) in block  # Assuming your user uses 'elif' key
        has_else = registry.get_key_from_id(SchemaID.ELSE) in block

        # Rule 1: A single block cannot contain multiple types
        if (has_if + has_elif + has_else) > 1:
            state.add_error(f"in Line {line_info}: {step_ref}: Block {i} cannot contain more than one of 'if', 'elif', or 'else'.")
            continue

        # Rule 2: Handle 'if'
        if has_if:
            if seen_else:
                state.add_error(f"in Line {line_info}: {step_ref}: 'if' found at index {i} after an 'else' block.")
            seen_if = True

        # Rule 3: Handle 'elif'
        elif has_elif:
            if not seen_if:
                state.add_error(f"in Line {line_info}: {step_ref}: 'elif' found at index {i} without a preceding 'if'.")
            if seen_else:
                state.add_error(f"in Line {line_info}: {step_ref}: 'elif' found at index {i} after an 'else' block.")

        # Rule 4: Handle 'else'
        elif has_else:
            if not seen_if:
                state.add_error(f"in Line {line_info}: {step_ref}: 'else' found at index {i} without a preceding 'if'.")
            if seen_else:
                state.add_error(f"in Line {line_info}: {step_ref}: Multiple 'else' blocks are not allowed.")
            seen_else = True
        
        else:
            state.add_error(f"in Line {line_info}: {step_ref}: Block {i} is missing a valid 'if', 'elif', or 'else' key.")

    if not seen_if and len(content) > 0:
        state.add_error(f"in Line {line_info}: {step_ref}: Condition list must contain at least one 'if' statement.")
    
    core_validator(
            section_key=section_key,            # The child key becomes the new section key
            content=content,              # Pass only the relevant sub-content
            key=key, 
            state=state, 
            value=value, 
            registry=registry
        )
    
def core_validator(section_key: Any, content: List[Dict] | Dict, registry: PiperRegistry, state: Optional[ValidationState] = None, **kwargs) -> List:
    if state is None:
        state = ValidationState()

    # Get the base definition (do this once)
    base_allowed_keys = registry.get_allowed_keys_definition(section_key)
    service_map = {SchemaID.SERVICE: get_service_keys, SchemaID.ACTION: get_action_keys}
    if isinstance(content, Dict):
        content = [content]

    for n, step in enumerate(content):
        step_ref = f"Step {n} (Depth {state.depth})"
        line_info = get_line_number(step, section_key)
        
        # Start with a clean slate for this specific step
        current_step_schema = base_allowed_keys.copy()
        service_content = None
        
        # Dynamically inject service-specific keys for this step only
        service_list = [k for k in step.keys() if registry.id_map.get(k) in service_map]
       
        if service_list:
            service_key = service_list[0]
            service_id = registry.id_map.get(service_key)
            service_content = step.get(service_key)
            resolve_func = service_map.get(service_id)
            
            config_keys = resolve_func(value=service_content, registry=registry, 
                                       key=service_key, state=state, step_ref=step_ref)
            if config_keys:
                current_step_schema.update(config_keys)

        if not isinstance(step, Dict):
            continue

        # 3. Mandatory Key Check
        for expected_key, rules in current_step_schema.items():
            if rules.get("mandatory", False) and expected_key not in step:
                state.add_error(f"in Line {line_info}: {step_ref}: Missing mandatory child key '{expected_key}'")
        
        # 4. Specialist Validation
        for key, value in step.items():
            specialist = registry.get_validator(key)
            child_line_info = get_line_number(step, key)
            
            validate_dependencies_with_prefix(
                section_key=key, 
                content=step, 
                registry=registry, 
                state=state, 
                line_info=child_line_info # Pass the precise line info here
            )

            if isinstance(value, str):
                validate_expression(
                    expr_content=value, 
                    line_info=child_line_info, 
                    state=state, 
                    context_ref=step_ref
                )

            if key not in current_step_schema:
                state.add_error(f"in Line {child_line_info}: {step_ref}: Unauthorized child key '{key}' found in '{section_key}'")
            
            if specialist:
                # IMPORTANT: Pass 'value' (the child content) instead of 'step' (the parent content).
                specialist(
                    section_key=key,            # The child key becomes the new section key
                    content=value,              # Pass only the relevant sub-content
                    key=key, 
                    state=state, 
                    value=value, 
                    registry=registry, 
                    step_ref=f"{step_ref} -> {key}", # Improved path tracking
                    service_value=service_content,
                    line_info=child_line_info,                # Usually None for nested blocks
                    func=core_validator
                )
                  
    return state.errors

def validate_recursive(section_key, content, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func, **kwargs):
    # Ensure we get the list from the correct key (e.g., 'steps' or 'on_error')
    
    if not isinstance(content, list):
        content = [content]
        
    # Must pass 'name' back to the recursive function
    state.depth += 1
    recursive_call = func(section_key=section_key, content=content, registry=registry, state=state)
    state.depth -= 1
    return recursive_call

def validate_id(section_key, line_info, content, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func, **kwargs) -> None:
    
    # Check 2: Uniqueness (The Senior move)
    if value in state.seen_ids:
        state.add_error(f"in Line {line_info}: [{step_ref}] Duplicate ID found: '{value}'. IDs must be unique.")
    else:
        state.seen_ids.append(value)

def check_step_validity(key: Any, value: Any, registry: PiperRegistry, state: ValidationState, step_ref: str = None, top_level_key=None, path=None, parent=None, **kwargs):
    # 1. SETUP & LINE INFO
    # Determine if we are looking at a real key or just a list position

    # Get the line number from the parent container
    is_list_index = str(key).startswith("index ")
    line_info = get_line_number(parent, key)

    # Get the actual data value
    actual_value = value[key] if isinstance(value, dict) and key in value else value
    if top_level_key and not is_list_index:
        allowed_for_block = registry.allowed_keys_map.get(top_level_key, [])
        if allowed_for_block and key not in allowed_for_block and key not in registry.handler_config_keys:
            state.add_error(f"[{path}] Line {line_info}: Key '{key}' is valid in Piper, but not allowed inside a '{top_level_key}' block.")
            return False

    # 2. EXISTENCE CHECK (Tier 1)
    # Skip this if it's just a list index (e.g. "pipeline.0")
    if not is_list_index:
        if key not in registry.list_of_keys and key not in registry.list_of_runtime_keys:
            suggestion = get_suggestion(key, list(set(registry.list_of_keys) | registry.list_of_runtime_keys))
            msg = f"Unknown key '{key}'"
            if suggestion:
                msg += f". Did you mean '{suggestion}'?"
            else:
                available = ", ".join(list(registry.type_map.keys())[:5])
                msg += f". (Available: {available}...)"
            
            state.add_error(f"[{path}] Line {line_info}: {msg}")
            return False


    # 4. TYPE CHECK (Tier 3)
    # We only type check keys that are in our registry
    expected_type = registry.type_map.get(key)

    # --- ADD THIS BLOCK ---
    if isinstance(expected_type, list):
        expected_type = tuple(expected_type)
    # ----------------------

    if expected_type and not isinstance(actual_value, expected_type):
        actual_type = type(actual_value).__name__
        expected_name = expected_type.__name__ if hasattr(expected_type, '__name__') else str(expected_type)
        
        state.add_error(f"[{path}] Line {line_info}: Type Mismatch on '{key.upper()}'. Expected {expected_name}, got {actual_type}.")
        return False

    return True

def check_dependency_validity(state, key, value, step_ref, rule_config, registry, step):
    step_keys = set(step.keys())
    error_count = 0
    for manager_role, rule in rule_config.items():
        allowed_keys_for_role = set(registry.manager_map.get(manager_role, []))
        
        # Intersection: which keys in the step are managers of this role?
        found_managers = step_keys.intersection(allowed_keys_for_role)
        manager_count = len(found_managers)

        # FIX: Get a valid key for line number lookup
        # If we found keys, pick the first one. If not, use the current service key.
        error_key = list(found_managers)[0] if found_managers else key
        line_info = get_line_number(step, error_key)

        # A. Mandatory Check
        if rule.mandatory and manager_count == 0:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] Dependency Error: "
                f"Service '{value}' requires a manager for '{manager_role}' (e.g., {allowed_keys_for_role})."
            )
            error_count += 1
            continue 

        display_role = manager_role.replace("_", " ").replace("an ", "").title()

        if rule.support == 0 and manager_count > rule.support:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] Configuration Error: "
                f"This {display_role} is not allowed in this blocks. "
                f"Maximum allowed is {rule.support}, but you used {manager_count}: {list(found_managers)}"
            )
            error_count += 1
            continue

        if manager_count > rule.support:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] Configuration Error: "
                f"Too many {display_role} blocks found. "
                f"Maximum allowed is {rule.support}, but you used {manager_count}: {list(found_managers)}"
            )
            error_count += 1
    if error_count > 0:
        return False
    return True

def validate_service_v2(section_key: str, line_info, content: Dict, key: str, value: str, registry, state, step_ref: str, **kwargs) -> None:
    # 1. Resolve Path and Prefix
    prefix = registry.service_prefix(service_key=key, service_value=value)

    key_content = registry._raw.get(key)
    prefix_content = key_content.get("prefix")
    
    if prefix_content and registry.top_level_key.get(section_key):
        cont = prefix_content.get(prefix)
        top_parent = cont.get("top_level_parent")
        
        # --- FIX STARTS HERE ---
        # Get the ID of the current section (e.g., convert "trigger" -> SchemaID.TRIGGER)
        current_section_id = registry.id_map.get(section_key)
        
        if top_parent and current_section_id:
            # Check using the ID instead of the string key
            if current_section_id not in top_parent:
                state.add_error(
                    f"in Line {line_info}: [{step_ref}] This top level key '{section_key}' "
                    f"does not support this type of service prefix: '{prefix}'."
                )
                return
        
    prefix_validator = registry.get_prefix_validator(key=key, prefix_name=prefix)


    if prefix_validator:
        if callable(prefix_validator):
            prefix_validator(
            key=key, 
            current_step=content, 
            registry=registry, 
            state=state, 
            step_ref=step_ref, # Pass path so it can find the app schema
            value=value,
            line_info=line_info
        )

def verify_config(handler: Callable, content: Dict, registry: PiperRegistry, state: ValidationState, context_ref: str, step):
    """
    Refactored for V2: Validates a DSL block against a Python handler's signature.
    """
    # 1. Inspect the Python Function Contract
    # Returns: { "arg_name": {"annotation": type, "default": value} }
    contract = inspect_function(func=handler)
    
    # 2. Identify Infrastructure Keys to Ignore
    # We don't want to validate 'service', 'id', 'pipeline', etc., against the Python function
    infra_keys = registry.get_core_syntax_keys()
    
    # 3. Check for Unknown Keys (Typos)
    for key in content.keys():
        if key in infra_keys:
            continue
            
        if key not in contract:
            is_list_index = str(key).startswith("index ")
            lookup_key = key if not is_list_index else None
    
            # Get the line number from the parent container
            line_info = get_line_number(step, lookup_key)
            suggestion = get_suggestion(key, list(contract.keys()))
            msg = f"Unknown key '{key}' for this handler, in Line {line_info}. "
            if suggestion:
                msg += f" Did you mean '{suggestion}'?"
            else:
                msg += f"list of config keys for this service {list(contract.keys())}"
            
            state.add_error(f"[{context_ref}] {msg}")

    # 4. Check for Missing Mandatory Arguments & Type Mismatches
    for arg_name, info in contract.items():
        # A field is mandatory if it has no default value in Python
        is_mandatory = info["default"] is inspect.Parameter.empty
        val_in_dsl = content.get(arg_name)

        # Angle: Missing Field
        if is_mandatory and arg_name not in content:
            state.add_error(f"[{context_ref}] Missing mandatory argument: '{arg_name}'")
            continue

def validate_input_v2(section_key, line_info, content: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str, service_value, **kwargs):
    if service_value is None:
        return
    # ----------------------
    run = None
    if "runtime" in content:
        run = content.get("runtime")
    info = resolve_service_instruction(service_key=service_value, runtime=run)
    
    # 2. Get Schema
    file_path = info.get("full_path")
    if not file_path:
        return
    
    key_matches = check_key_matches(file_path)
    matched_items = key_matches["found_items"]["matched_items"]

    # 3. Check for Missing Required Fields
    required_but_missing = []
    for field, schema_val in matched_items.items():
        schema_str = str(schema_val)
        has_default = "Default=" in schema_str or "Default =" in schema_str
        is_in_dsl = field in content # Now checking the flat dictionary!

        if not is_in_dsl and not has_default:
            required_but_missing.append(field)
        
        # Check for empty values
        if is_in_dsl:
            val = content[field]
            if val is None or (isinstance(val, str) and not val.strip()):
                state.add_error(f"in Line {line_info}: Value for '{field}' cannot be empty.")

    if required_but_missing:
        state.add_error(f"in Line {line_info}: Missing required fields: {set(required_but_missing)}")

    # 4. Check for Unknown/Typo Keys
   
    for user_key, value in content.items():
        child_line_num = get_line_number(content, user_key)
        if user_key not in matched_items:
            
            # --- NEW PRECISION LOGIC ---
            # 1. Find the exact dictionary that contains this key
            target_dict = next(
                (item for item in content if isinstance(item, dict) and user_key in item), 
                content
            )
            
            # 2. Get the line number from the specific target object
            sub_line_info = get_line_number(target_dict, user_key)
            # ---------------------------

            suggestion = get_suggestion(user_key, list(matched_items.keys()))
            msg = f"Line {sub_line_info}: Field '{user_key}' unknown."
            if suggestion: 
                msg += f" Did you mean '{suggestion}'?"
            else:
                msg += f" Valid keys: {list(matched_items.keys())}"
            
            state.add_error(msg)
            
        if isinstance(value, str):
            validate_expression(
                expr_content=value, 
                line_info=child_line_num, 
                state=state, 
                context_ref=step_ref
            )

def validate_input_v1(key, step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str, service_value, **kwargs):
    run = None
    if "runtime" in step:
        run = step.get("runtime")
    
    info = resolve_service_instruction(service_key=service_value, runtime=run)
    is_list_index = str(key).startswith("index ")
    lookup_key = key if not is_list_index else None
    file_path = info["full_path"]
    # Get the line number from the parent container
    line_info = get_line_number(step, lookup_key)
    
    if info:
        if not os.path.exists(file_path):
            state.add_error(f"[{step_ref}] System Error: Service resource '{value}' missing.")
            return
        
    line_info = get_line_number(step, key)
    input_block = step.get(key, {})
    
    key_matches = check_key_matches(file_path)
    matched_items = key_matches["found_items"]["matched_items"]

    required_but_missing = []

    for field, schema_val in matched_items.items():
        # 1. Parse the schema string for a Default value
        # Example schema_val: "{{DataType=str, Default=$.Hubspot}}"
        schema_str = str(schema_val)
        has_default = "Default=" in schema_str or "Default =" in schema_str
        is_in_dsl = field in input_block

        # If it's missing AND has no default, it's an error
        if not is_in_dsl and not has_default:
            required_but_missing.append(field)
        
        # 2. If it IS in the DSL, check if the user left it empty
        if is_in_dsl:
            val = input_block[field]
            if val is None or (isinstance(val, str) and not val.strip()):
                state.add_error(f"in Line {get_line_number(input_block, field)}: Value for '{field}' cannot be empty.")

    if required_but_missing:
        state.add_error(f"in Line {line_info}: Missing required fields: {set(required_but_missing)}")

    # 3. Typo / Unknown Key Check
    for container in input_block:
        for user_key in container.keys():
            if user_key not in matched_items:
                suggestion = get_suggestion(user_key, list(matched_items.keys()))
                msg = f"Line {get_line_number(input_block, user_key)}: Field '{user_key}' unknown."
                if suggestion: 
                    msg += f" Did you mean '{suggestion}'?"
                else:
                    msg += f" List of valid keys: {matched_items.keys()}"
                state.add_error(msg)


def validate_dsl_helpers(value: str, state, line_info, step_ref):
    """
    Scans a DSL string for helper functions and verifies 
    they exist in the helpers.py module.
    """
    if not isinstance(value, str):
        return

    # Find patterns like 'func_name('
    functions_found = re.findall(r"(\w+)\s*\(", value)

    for func_name, args_str in functions_found:
        # Check if the function exists in our helpers.py file
        if not hasattr(helpers, func_name):
            state.add_error(f"Line {line_info}: Function '{func_name}' not found.")
            continue
        func = getattr(helpers, func_name, None)
        if not callable(func):
            state.add_error(
                f"in Line {line_info}: [{step_ref}] The helper function "
                f"'{func_name}' was not found in helpers.py."
            )
        required_params = inspect_function(func=func)

        provided_args_count = len([a for a in args_str.split(',') if a.strip()])
        
        if provided_args_count < len(required_params):
            state.add_error(f"Line {line_info}: '{func_name}' missing arguments. Expected {len(required_params)}.")



def validate_condition_syntax(content, key: Any, line_info, value: Any, registry, state: ValidationState, step_ref: str, **kwargs):
    # 1. Check for ID existence
    # Regex updated to target '$' prefix
    tags = re.findall(r"\$(?P<id>[\w\-]+)\.(?P<path>[\w\.]+)", value)
    for ref_id, path in tags:
        if ref_id not in state.seen_ids:
            state.add_error(f"Condition Error: Reference to '{ref_id}' not found, in Line {line_info}.")

    # 2. Advanced Mocking
    # Update regex to find '$variable' and replace with 'var'
    mock_condition = re.sub(r"\$[\w\-\.]+", "var", value)
    
    # 3. Handle Pipe/Contains logic if you are using custom string operations
    # If your DSL supports 'contains', you might need to replace it with a standard call 
    # so AST can parse it, e.g., mock_condition = mock_condition.replace('| contains', 'in')
    
    try:
        tree = ast.parse(mock_condition, mode='eval')
        
        allowed_nodes = (
            ast.Expression, ast.Compare, ast.BinOp, ast.BoolOp, 
            ast.UnaryOp, ast.Name, ast.Constant, ast.Load, ast.Attribute,
            ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.Lt, ast.LtE, 
            ast.In, ast.BitOr # Added In for 'in' keyword and BitOr for pipe '|'
        )
        
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                state.add_error(f"in Line {line_info}: Restricted syntax in condition: {type(node).__name__}")
                return
    except SyntaxError:
        state.add_error(f"Invalid condition syntax: in Line {line_info}, '{value}'. Check your operators (==, !=, >, <).")

def validate_webhook():
    pass

def validate_timer(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str, line_info: str, **kwargs):
    """
    Validates the 'interval' argument for the schedule/timer service.
    Expected format: '30 sec', '1 h', etc.
    """
    # 1. Get the interval from the args/step
    # Depending on your DSL, it might be in step['interval'] or step['args']['interval']
    service_val = value if isinstance(value, str) else str(current_step)
    if not "." in service_val:
        state.add_error(
            f"in line {line_info}: [{step_ref}] Validation Error: The 'timer' service is not a single-token service "
            f"and must include dot notation (got '{service_val}')."
        )
        return

    interval = str(current_step.get('interval') or current_step.get('args', {}).get('interval'))
    now = str(current_step.get('now') or current_step.get('args', {}).get('now'))
    
    if not interval or now:
        # If it's mandatory but missing, add error (or let check_step_validity handle it)
        state.add_error(
            f"in line {line_info}: [{step_ref}] Validation Error: The 'timer' service require a specific action to be taken. use case: timer.interval or timer.now ...."
        )
        return
    
    line_name = interval or now

    line_info = get_line_number(current_step, line_name)
    valid_units = {"sec", "min", "h", "d", "m", "y"}

    # 2. Validate Format via Regex
    # Matches: One or more digits + space + exactly one of the valid units
    pattern = r"^\d+\s+(" + "|".join(valid_units) + ")$"
    if interval:
        if not re.match(pattern, interval):
            state.add_error(
                f"Line {line_info}: [{step_ref}] Invalid interval format '{interval}'. "
                f"Expected 'value unit' (e.g., '10 min'). "
                f"Allowed units: {', '.join(valid_units)}"
            )

def validate_script(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str, **kwargs):
    available_lang = ["python", "javascript"]
    runtime = current_step.get("runtime")
    if not runtime:
        return
    if not runtime in available_lang:
        state.add_error(f"Error: Unsupported runtime: {runtime}. valid runtime {available_lang}")

#def validate_action
    