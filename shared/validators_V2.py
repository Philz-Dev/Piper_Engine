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

    for section, content in dsl_file.items():
        # Skip metadata keys like 'version'
        if section == "version":
            continue
    
        # 2. Check for Structural Placement (Top-Level Authorization)
        if section in registry.list_of_keys and not registry.is_section_manager(section):
            line_info = get_line_number(content, section)
            state.add_error(f"in Line {line_info}: [Top-Level] '{section}' is a utility key and cannot be used as a top-level section.")
            continue
         # 4. Blind Dispatch to Specialist
        specialist = registry.get_validator(section)
        if specialist:
            # Specialist handles deep-logic validation (IDs, webhooks, etc.)
            specialist(section, content, registry, state)
    return state.errors

def validate_pipeline(section_key: Any, content: List[Dict], registry: PiperRegistry, state: Optional[ValidationState] = None, **kwargs) -> List:
    # Initialize state once at the start
    if state is None:
        state = ValidationState()

    for n, step in enumerate(content):
        step_ref = f"Step {n} (Depth {state.depth})"

        rules = registry.get_dependency_rules(section_key)
        for map_name, rule in rules.items():
            # Check if step contains a key that exists in the specified map
            # e.g., A_SERVICE_MANAGER_MAP
            line_info = get_line_number(step, section_key)
            found = [k for k in step.keys() if k in getattr(registry, map_name.lower())]
 
            if rule.mandatory and not found:
                state.add_error(f"in Line {line_info}: {step_ref}: Missing mandatory {map_name}")
            if len(found) > rule.support:
                state.add_error(f"in Line {line_info}: {step_ref}: Too many {map_name} keys")

        # 2. Key-by-Key Specialized Validation
        for key, value in step.items():
            check_step_validity(key=key, value=value, top_level_key=section_key, state=state, registry=registry, path=step_ref, parent=step)
            specialist = registry.get_validator(key)
            if specialist:
                specialist(section_key=section_key, step=step, key=key, state=state, value=value, registry=registry, step_ref=step_ref, func=validate_pipeline)
    return state.errors

def validate_recursive(section_key, step, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func):
    # Ensure we get the list from the correct key (e.g., 'steps' or 'on_error')
    target_content = step.get(key)
    
    if not isinstance(target_content, list):
        target_content = [target_content]
        
    # Must pass 'name' back to the recursive function
    state.depth += 1
    recursive_call = func(section_key=section_key, content=target_content, registry=registry, state=state)
    state.depth -= 1
    return recursive_call

def validate_id(section_key, step, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func) -> None:
    
    # Check 2: Uniqueness (The Senior move)
    if value in state.seen_ids:
        line_info = get_line_number(step, key)
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
    if expected_type and not isinstance(actual_value, expected_type):
        actual_type = type(actual_value).__name__
        expected_name = expected_type.__name__ if hasattr(expected_type, '__name__') else str(expected_type)
        
        state.add_error(f"[{path}] Line {line_info}: Type Mismatch on '{key.upper()}'. Expected {expected_name}, got {actual_type}.")
        return False

    return True

def validate_service(step: Dict, key: str, value: str, registry, state, step_ref: str, **kwargs) -> None:
    # 1. Resolve Path and Prefix (ext., script., or lib)
    info = resolve_service_instruction(service_key=value)

    is_list_index = str(key).startswith("index ")
    lookup_key = key if not is_list_index else None
    file_path = info.get("full_path")
    # Get the line number from the parent container
    line_info = get_line_number(step, lookup_key)
    
    if not os.path.exists(file_path):
        state.add_error(f"[{step_ref}] System Error: Service resource '{value}' missing.")
        return
    
    prefix = registry.service_prefix(service_key=key, service_value=value)

    # 2. Dependency Rule Check (Dynamic lookup)
    # This retrieves the rule for 'an_input_manager' from the service's dependency map
    found_input_key = input_manager(registry, step)
    rule_config = registry.get_service_dependency_rules(key, prefix) # e.g., {"an_input_manager": {"mandatory": True, ...}}
    for manager_attr, rule in rule_config.items():
        # Specifically handle input manager dependency
        if manager_attr == "an_input_manager":
            if rule.mandatory and not found_input_key:
                state.add_error(f"in Line {line_info}: [{step_ref}] Dependency Error: Service '{value}' requires an input manager block.")
                return
            
            if len(found_input_key) > rule.support:
                state.add_error(f"in Line {line_info}: [{step_ref}] Configuration Error: Too many input manager keys found: {found_input_key}")
                return
            
    not_defualt_args = []
    handler = registry.get_sub_executor(key, prefix)
    if handler:
        inspect = inspect_function(func=handler)
        core_sys_keys = registry.get_core_syntax_keys()
    for ky, vl in inspect.items():
        if not vl["default"]:
            not_defualt_args.append(ky)
    config_keys = {}
    for k, v in step.items():
        line_info = get_line_number(step, k)
        if k in core_sys_keys:
            continue
        if not k in inspect:
            state.add_error(f"in Line {line_info}: wrong syntax, this service does not required this syntax {k}")
        else:
            config_keys[k] = v

    missing_arg = missing_field(required=not_defualt_args, content_to_check=config_keys)
    if missing_arg:
        state.add_error(f"in Line {line_info}: missing this syntax {missing_arg}")
    
    # 3. Dynamic Sub-Validator Triggering
    
        # Get the sub_validator defined in the 'input' section of schema_reg
        # Usually: registry._raw["input"]["sub_validators"]["input"]
    if found_input_key:
        input_validator = registry.get_sub_validator(found_input_key[0], found_input_key[0])
        
        if input_validator:
            # Execute the input validator (e.g., validate_input)
            input_validator(
                key=found_input_key[0], 
                current_step=step, 
                registry=registry, 
                state=state, 
                context_ref=step_ref,
                service_path=file_path, # Pass path so it can find the app schema
                service_value=value
            )

    # 4. Specialist Delegation (Standard service logic)
    specialist = registry.sub_validator_map[prefix]
    if specialist:
        specialist(key=key, value=value, registry=registry, state=state, step_ref=step_ref)

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

def validate_service_v2(step: Dict, key: str, value: str, registry, state, step_ref: str, **kwargs) -> None:
    # 1. Resolve Path and Prefix (ext., script., or lib)
    prefix = registry.service_prefix(service_key=key, service_value=value)

    # 2. Dependency Rule Check (Dynamic lookup)
    rule_config = registry.get_service_dependency_rules(key, prefix) 
    
    if not check_dependency_validity(state=state, key=key, value=value, step_ref=step_ref, rule_config=rule_config, registry=registry, step=step):
        return
    not_defualt_args = []
    handler = registry.sub_executor_map.get(prefix)
    if not handler:
        state.add_error(f"[{step_ref}] Registry Error: No handler for '{prefix}' mode.")
        return
    inspect = inspect_function(func=handler)
    core_sys_keys = registry.get_core_syntax_keys()
    for ky, vl in inspect.items():
        if not vl["default"]:
            not_defualt_args.append(ky)
    config_keys = {}
    prefix_list = []
    for k, v in step.items():
        role = registry.identify_manager_role(k)
        if role in rule_config:
            prefix_list.append(k)
        line_info = get_line_number(step, k)
        if k in core_sys_keys:
            continue
        if not k in inspect:
            state.add_error(f"in Line {line_info}: wrong syntax, this service does not required this syntax {k}. Available config keys: {inspect.keys()}")
        else:
            config_keys[k] = v

    missing_arg = missing_field(required=not_defualt_args, content_to_check=config_keys)
    if missing_arg:
        state.add_error(f"in Line {line_info}: missing this syntax {missing_arg}")
    
   
    dep_func_validators = registry.find_dependency_func(sub_type="validator", registry=registry, step=step, dependencies=rule_config, prefix=prefix_list)
    sub_validator = {prefix: registry.sub_validator_map.get(prefix)}
    sub_validators = {**dep_func_validators, **sub_validator}

    if sub_validators:
        for k, d in sub_validators.items():
            # Execute the input validator (e.g., validate_input)
            if callable(d):
                d(
                key=k, 
                current_step=step, 
                registry=registry, 
                state=state, 
                step_ref=step_ref, # Pass path so it can find the app schema
                value=value
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

def validate_input(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, full_path: str, value: str):
    """
    PRE-FLIGHT: Replaces the 'missing_field' and 'ValueError' logic.
    """
    run = None
    if "runtime" in current_step:
        run = current_step.get("runtime")
    info = resolve_service_instruction(value, runtime=run)
    is_list_index = str(key).startswith("index ")
    lookup_key = key if not is_list_index else None
    file_path = info["full_path"]
    # Get the line number from the parent container
    line_info = get_line_number(current_step, lookup_key)
    
    if info:
        if not os.path.exists(file_path):
            state.add_error(f"[{step_ref}] System Error: Service resource '{value}' missing.")
            return
        
    line_info = get_line_number(current_step, key)
    input_block = current_step.get(key, {})
    key_matches = check_key_matches(full_path)
    app_schema = key_matches["app_schema"]
    found_items = key_matches["found_items"]
    if not app_schema:
        state.add_error(f"NameError: No such app or action to be taken {value}")
        return
    matched_items = found_items["matched_items"]
    missing = missing_field(required=matched_items, content_to_check=input_block)
    if missing:
        state.add_error(f"in Line {line_info}: this field {missing} is required")

    for user_key in input_block.keys():
        if not user_key in matched_items:
            line_info = get_line_number(current_step, user_key)
            suggestion = get_suggestion(user_key, list(matched_items.keys()))
            msg = f"Line {line_info}: Field '{user_key}' is not recognized by this service."
            if suggestion:
                msg += f" Did you mean '{suggestion}'?"
            else:
                msg += f" List of valid keys: {matched_items.keys()}"

            state.add_error(f"{msg}")

def validate_input_v2(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str):
    run = None
    if "runtime" in current_step:
        run = current_step.get("runtime")
    info = resolve_service_instruction(value, runtime=run)
    is_list_index = str(key).startswith("index ")
    lookup_key = key if not is_list_index else None
    file_path = info["full_path"]
    # Get the line number from the parent container
    line_info = get_line_number(current_step, lookup_key)
    
    if info:
        if not os.path.exists(file_path):
            state.add_error(f"[{step_ref}] System Error: Service resource '{value}' missing.")
            return
        
    line_info = get_line_number(current_step, key)
    input_block = current_step.get(key, {})
    
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
    for user_key in input_block.keys():
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



def validate_condition_syntax(step, key: Any, value: Any, registry, state: ValidationState, step_ref: str, **kwargs):
    line_info = get_line_number(step, key)
    
    # 1. Check for ID existence (Already working)
    tags = re.findall(r"\{\{(?P<id>[\w\-]+)\.(?P<path>[\w\.]+)\}\}", value)
    for ref_id, path in tags:
        if ref_id not in state.seen_ids:
            state.add_error(f"Condition Error: Reference to '{ref_id}' not found, in Line {line_info}.")

    # 2. Advanced Mocking
    # We replace the tag with a valid Python variable name 'var'
    mock_condition = re.sub(r"\{\{.*?\}\}", "var", value)
    
    try:
        tree = ast.parse(mock_condition, mode='eval')
        
        # 3. Security Walk - Add ast.Attribute for 'id.key' style if needed
        allowed_nodes = (
            ast.Expression, ast.Compare, ast.BinOp, ast.BoolOp, 
            ast.UnaryOp, ast.Name, ast.Constant, ast.Load, ast.Attribute,
            ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.Lt, ast.LtE  # Added these
        )
        
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                state.add_error(f"in Line {line_info}: Restricted syntax in condition: {type(node).__name__}")
                return
    except SyntaxError:
        state.add_error(f"Invalid condition syntax: in Line {line_info}, '{value}'. Check your operators (==, !=, >, <).")

def validate_webhook():
    pass

def validate_timer(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str):
    """
    Validates the 'interval' argument for the schedule/timer service.
    Expected format: '30 sec', '1 h', etc.
    """
    # 1. Get the interval from the args/step
    # Depending on your DSL, it might be in step['interval'] or step['args']['interval']
    interval = str(current_step.get('interval') or current_step.get('args', {}).get('interval'))
    
    if not interval:
        # If it's mandatory but missing, add error (or let check_step_validity handle it)
        return

    line_info = get_line_number(current_step, "interval")
    valid_units = {"sec", "min", "h", "d", "m", "y"}

    # 2. Validate Format via Regex
    # Matches: One or more digits + space + exactly one of the valid units
    pattern = r"^\d+\s+(" + "|".join(valid_units) + ")$"

    if not re.match(pattern, interval):
        state.add_error(
            f"Line {line_info}: [{step_ref}] Invalid interval format '{interval}'. "
            f"Expected 'value unit' (e.g., '10 min'). "
            f"Allowed units: {', '.join(valid_units)}"
        )

def validate_script(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str):
    available_lang = ["python", "javascript"]
    runtime = current_step.get("runtime")
    if not runtime:
        return
    if not runtime in available_lang:
        state.add_error(f"Error: Unsupported runtime: {runtime}. valid runtime {available_lang}")
    