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
from shared.tools import load_yaml_with_metadata, get_registry_package


def get_project_root() -> str:
    """
    Single source of truth for the DSL project root: the directory whose
    child is 'templates/', and the base that dot-notation 'from:'/'use:'
    import paths are resolved against.

    This mirrors the environment detection that used to live only inside
    setup_build.init_build() (workspace_templates / internal_templates /
    local_templates), so template discovery and import-path resolution can
    never disagree about where 'root' is -- and neither depends on the
    process's current working directory, which varies depending on where
    the CLI happens to be invoked from (that CWD dependency is exactly what
    let a self-import slip past validation earlier: the same file resolved
    to two different path strings depending on where 'piper' was run from).
    """
    docker_workspace_templates = "/app/workspace/templates"
    docker_internal_templates = "/app/templates"

    if os.path.isdir(docker_workspace_templates):
        return os.path.dirname(docker_workspace_templates)
    if os.path.isdir(docker_internal_templates):
        return os.path.dirname(docker_internal_templates)

    # Local/dev fallback: walk up from this module's own location looking
    # for a 'templates' directory, instead of trusting the launching
    # shell's CWD.
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(current, "templates")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Nothing found -- degrade to CWD rather than raising, but this should
    # only ever trigger in an environment with no 'templates' directory at all.
    return os.getcwd()


def resolve_dsl_import_path(dot_path: str) -> str:
    """
    Single source of truth for turning a DSL import reference written in
    dot-notation (e.g. 'templates.client_temp.waterfall.waterfall') into an
    absolute filesystem path (e.g.
    '<project_root>/templates/client_temp/waterfall/waterfall.yml').

    import_validator, from_validator, and use_validator all resolve import
    paths through this single function. Previously each duplicated this
    logic independently -- one call site normalized to an absolute path via
    os.path.abspath() and another didn't, which is what let a self-import
    slip past validation undetected (a relative path never string-equals
    the absolute path it actually points to). Keeping resolution in one
    place means every caller is guaranteed to agree on what a given import
    path resolves to -- and resolving against get_project_root() instead of
    os.getcwd() means that agreement no longer depends on where the process
    happens to be launched from.
    """
    relative_path = dot_path.replace(".", "/") + ".yml"
    return os.path.abspath(os.path.join(get_project_root(), relative_path))


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

def main_validator(dsl_file: Dict[str, Any], registry, state, name: str="", visited_files=None, current_file_path=None):

    # 'action: call' is a LOCAL 'use' - it needs to search THIS file for a
    # step by id (call_validator, via _find_step_by_id), the same way
    # use_validator searches an imported file via state.import_map. Stash
    # the file being validated right now so that lookup has something to
    # search without threading a new kwarg through core_validator's whole
    # recursion the way log_key had to be.
    state.dsl_file = dsl_file

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
    import_key = registry.get_key_from_id(SchemaID.IMPORT)

    def _validate_section(section, content):
        line_info = get_line_number(content, section)

        validate_dependencies_with_prefix(
            section_key=section, 
            content=dsl_file, # Assuming dsl_file is the sibling scope
            registry=registry, 
            state=state, 
            line_info=line_info
        )
        # 🛠️ validate_expression call removed here - now superseded by
        # check_step_validity's primitive-hook wiring, which UnZip's
        # unpack_bulk_data already runs over this same top-level scalar
        # as part of walking the whole dsl_file. Left in both places
        # would double-report the same {{...}} expression's errors.

        section_id = registry.id_map.get(section)
        if section_id is None:
             state.add_error(f"Unknown top-level section: '{section}'")
             return
        if section_id == SchemaID.VERSION:
            return

        # Check if this section is allowed in __main__
        if section in registry.list_of_keys and section_id not in allowed_main_ids:
            state.add_error(
                f"in Line {line_info}: [Top-Level] '{section}' is a utility key and cannot be used as a top-level section."
                f"Allowed sections are: {[id.name for id in allowed_main_ids]}"
            )
            return

        # 2. Check for Structural Placement (Top-Level Authorization)
        if registry.id_map.get(section) in registry.list_of_keys and not registry.is_section_manager(section):
            state.add_error(f"in Line {line_info}: [Top-Level] '{section}' is a utility key and cannot be used as a top-level section.")
            return
         # 4. Blind Dispatch to Specialist
        specialist = registry.get_validator(section)
        if specialist:
            # Specialist handles deep-logic validation (IDs, webhooks, etc.)
            specialist(section, content, registry, state, visited_files=visited_files, current_file_path=current_file_path)

    # Pre-pass: resolve 'import:' first, regardless of where it's declared in
    # the file. A YAML/JSON document has no execution order, so unlike Python
    # source there's no real reason to force 'import:' above 'pipeline:' --
    # we just need state.import_map populated before any 'use:' reference
    # gets checked. Resolving it up front makes section order irrelevant.
    if import_key is not None and import_key in dsl_file:
        _validate_section(import_key, dsl_file[import_key])

    for section, content in dsl_file.items():
        if section == import_key:
            continue  # already handled in the pre-pass above
        _validate_section(section, content)

    
    return state

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

            # 🛠️ Two binding steps were missing here (present in the
            # CLI-style branch below for the first one, absent for both
            # in this function-call branch), which meant this branch
            # always false-flagged the implicit piped value as missing,
            # and never recognized any positional (non key=value) arg at
            # all - see the docstring's note on this fix:
            # a) the value implicitly supplied by the pipe satisfies the
            #    FIRST mandatory param, same as the CLI-style branch.
            for param_name, info in contract.items():
                if info.get("default") is inspect.Parameter.empty:
                    if param_name not in parsed_kwargs:
                        parsed_kwargs[param_name] = "PIPED_INPUT"
                    break
            # b) remaining explicit positional args bind, in order, to
            #    whichever contract params aren't already satisfied by
            #    the piped value or an explicit key=value kwarg - mirrors
            #    how Python itself binds positional arguments.
            remaining_slots = [n for n in contract if n not in parsed_kwargs]
            for pos_val, slot_name in zip(pos_args, remaining_slots):
                parsed_kwargs[slot_name] = pos_val

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

            # 🛠️ Explicit positional CLI args ('replace a b') were never
            # bound to contract param names - only key=value kwargs were
            # ever visible to the missing-argument check below, so
            # correctly-supplied positional args were silently invisible
            # to it. Bind them, in order, to whichever contract params
            # aren't already claimed by the piped value or a kwarg.
            remaining_slots = [n for n in contract if n not in parsed_kwargs]
            for pos_val, slot_name in zip(pos_args, remaining_slots):
                parsed_kwargs[slot_name] = pos_val

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
    
def core_validator(section_key: Any, content: List[Dict] | Dict, registry: PiperRegistry, state: Optional[ValidationState] = None, original_key: str="", previous_key: str="", **kwargs) -> List:
    
    if state is None:
        state = ValidationState()

    if original_key:
        log_key = original_key
    else:
        log_key = section_key

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
        # Always defined (not just inside the 'if service_list:' branch
        # below) so the specialist-dispatch call further down - which now
        # passes service_id through so validate_input_v2 can tell a
        # SERVICE step's 'input:' (checked against a real per-service JSON
        # schema) apart from an ACTION step's (no such schema doc exists;
        # see validate_input_v2) - never hits a NameError for a step with
        # neither key (a pure condition/steps grouping) or a 'use:' step.
        service_id = None
        
        # Dynamically inject service-specific keys for this step only.
        # A step with 'use: alias.id' has no 'service'/'action' of its own,
        # so it can't go through the normal service_map resolution below -
        # but the keys its REFERENCED step's service allows (e.g. 'timeout',
        # 'max_attempts') are still valid to set here, since they end up
        # controlling the SAME underlying dispatcher call either way. Resolve
        # those silently via _resolve_use_target and fold them into the
        # schema, same as a native step's config_keys. use_validator (run
        # later as this step's 'use' specialist) remains the one place that
        # reports actual 'use:' errors - this only prevents legitimate
        # override keys from being flagged as "Unauthorized".
        use_key_name = registry.get_key_from_id(SchemaID.USE)
        if use_key_name and use_key_name in step:
            service_list = []
            use_config_keys, target_service_id, target_service_value = _resolve_use_target(
                step.get(use_key_name), registry, state
            )
            if use_config_keys:
                # These are optional overrides from the use-validator's
                # perspective - use_validator checks the target's mandatory
                # keys against 'input' separately, so don't also make them
                # mandatory at the top level here (that would duplicate/
                # conflict with a check that belongs to a different key).
                current_step_schema.update({k: {"mandatory": False} for k in use_config_keys})

                # 'use:' steps skip validate_input_v2 entirely (service_content
                # stays None for this branch, so its guard clause at the top
                # returns early) -- meaning nothing else checks whether the
                # keys under THIS step's 'input:' are actually accepted by
                # the target service. use_validator separately checks that
                # mandatory keys are present, but never flags a key that
                # shouldn't be there at all. Do that here, as an allow-list
                # check, without touching mandatory/required-field logic
                # (that stays owned by use_validator).
                #
                # Strict split, not a merge: 'input:' holds ONLY schema
                # fields. Executor kwargs (timeout, max_attempts, ...) are
                # a sibling of 'input:' at the step level, and are already
                # covered by current_step_schema above via use_config_keys
                # - they don't belong inside 'input:' too.
                #   - SERVICE target: 'input:' is checked against the real
                #     per-service JSON schema file's fields (e.g. 'value'
                #     nested in HubSpot search's request template),
                #     resolved the same way validate_input_v2 does for
                #     native steps. use_config_keys plays no part here.
                #   - ACTION target: there is no separate schema doc -
                #     the python function's kwargs ARE the input schema,
                #     so use_config_keys is the correct (only) source.
                if target_service_id == SchemaID.SERVICE and isinstance(target_service_value, str):
                    accepted_input_keys = {}
                    service_info = resolve_service_instruction(service_key=target_service_value)
                    schema_path = service_info.get("full_path") if service_info else None
                    if schema_path:
                        key_matches = check_key_matches(schema_path)
                        matched_items = (key_matches.get("found_items", {}) or {}).get("matched_items", {})
                        if matched_items:
                            accepted_input_keys = matched_items
                else:
                    accepted_input_keys = use_config_keys

                input_key_name = registry.get_key_from_id(SchemaID.INPUT)
                current_input = step.get(input_key_name) or {}
                if isinstance(current_input, dict):
                    for user_key in current_input:
                        if user_key not in accepted_input_keys:
                            state.add_error(
                                f"in Line {get_line_number(current_input, user_key)}: {step_ref} "
                                f"'{user_key}' is not an accepted input key for the service used by "
                                f"'use: {step.get(use_key_name)}'."
                            )
        else:
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

        list_partial_section = registry.get_partial_list(section_key)
    
        if list_partial_section:
            partial_key_avalable = False
            for partial_key in list_partial_section:
                if partial_key in step:
                    partial_key_avalable = True
                    break

            if not partial_key_avalable:
                state.add_error(f"in Line {line_info}: [{step_ref}] one of this keys {list_partial_section} is mandatory for this section key")
        
        # 4. Specialist Validation
        for key, value in step.items():
            specialist = registry.get_validator(key)
            child_line_info = get_line_number(step, key)
            
            validate_dependencies_with_prefix(
                section_key=key, 
                content=step, 
                registry=registry, 
                state=state, 
                line_info=child_line_info, # Pass the precise line info here
                
            )

            if isinstance(value, str):
                # validate_expression call removed - superseded by
                # check_step_validity's primitive-hook wiring (covers
                # this same key's value). isinstance(str) guard kept
                # since the unauthorized-key check below is nested under it.
                if key not in current_step_schema:
                    if not key == registry.get_key_from_id(SchemaID.USE):

                        state.add_error(f"in Line {child_line_info}: {step_ref}: Unauthorized child key '{key}' found in '{log_key}'")
            
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
                    service_id=service_id,
                    line_info=child_line_info,                # Usually None for nested blocks
                    func=core_validator,
                    log_key = log_key,
                    original_key = log_key,
                    previous_key = section_key,
                    current_step = step
                )
                  
    return state.errors


def on_group_validator(section_key: str, content: Any, registry: Any, state: Any, line_info: Any = None, key: str = "", value: Any = None, step_ref: str = "", original_key: str = "", previous_key: str="", **kwargs) -> None:

    condition_map = [
            registry.get_key_from_id(SchemaID.IF),
            registry.get_key_from_id(SchemaID.ELIF), 
            registry.get_key_from_id(SchemaID.ELSE)
        ]
    is_conditional_content = False
        
    on_group = [
        registry.get_key_from_id(SchemaID.ON_SUCCESS), 
        registry.get_key_from_id(SchemaID.ON_COMPLETE),
        registry.get_key_from_id(SchemaID.ON_ERROR)
    ]
    
    if previous_key and previous_key not in on_group:
        
        if isinstance(content, dict):
            content = [content]
        
        # FIX: Un-indented so it properly evaluates when content is a list (or was converted to one)
        if isinstance(content, list):
            for cont in content:
                if isinstance(cont, dict):
                    for c in cont.keys():
                        if c in condition_map:
                            is_conditional_content = True
                            break
                if is_conditional_content:
                    break
    
        section_key = registry.get_key_from_id(
                SchemaID.CONDITION if is_conditional_content else SchemaID.OPERATIONS
            )
    else:
        section_key = registry.get_key_from_id(SchemaID.PIPELINE)
    
    use_key = original_key or key
    core_validator(section_key=section_key, content=content, registry=registry, state=state, original_key=use_key)

def validate_recursive(section_key, content, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func, **kwargs):
    # Ensure we get the list from the correct key (e.g., 'steps' or 'on_error')
    
    if not isinstance(content, list):
        content = [content]

    # Forward the caller's log_key (the true top-level section - e.g.
    # 'pipeline' - that this whole chain of nested 'steps' ultimately
    # lives under) as this call's original_key, so core_validator's own
    # log_key keeps resolving to that same top-level section no matter
    # how many 'steps' levels deep we recurse, instead of resetting to
    # 'steps' at every level. Without this, anything downstream that
    # relies on log_key to find the REAL enclosing top-level section
    # (e.g. use_validator's placement check) silently breaks for any
    # 'use:' step nested inside someone else's 'steps:' block.
    inherited_log_key = kwargs.get("log_key") or section_key

    # Must pass 'name' back to the recursive function
    state.depth += 1
    recursive_call = func(section_key=section_key, content=content, registry=registry, state=state, original_key=inherited_log_key)
    state.depth -= 1
    return recursive_call

def validate_id(section_key, line_info, content, key: Any, value: Any, registry, state: ValidationState, step_ref: str, func, **kwargs) -> None:
    
    # Check 2: Uniqueness (The Senior move)
    if value in state.seen_ids:
        state.add_error(f"in Line {line_info}: [{step_ref}] Duplicate ID found: '{value}'. IDs or alias must be unique.")
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

    # 🛠️ Pipe-chain validation now lives here, on the universal primitive
    # walk, instead of only in the three narrow one-level-deep call sites
    # that used to call validate_expression (main_validator's bare-string
    # section check, core_validator's step-key loop, validate_input_v2's
    # input-key loop - all three removed, see their diffs). Those only
    # ever caught a pipe expression written directly on a step's own key
    # or directly under 'input:' - anything nested one level deeper (a
    # list item under 'input', a dict field inside 'input', etc.) never
    # reached validate_expression at all. This hook fires on every string
    # leaf in the whole document regardless of depth, via UnZip's
    # 'primitive' callback, so it's a strict superset of what those three
    # covered - hence removing them instead of leaving both wired up,
    # which would have double-reported the same expression's errors.
    # Guarded to only actual_value being a str: check_step_validity is
    # also the SAME bound function used for the dict/list hooks, where
    # actual_value ends up being the container itself, not a leaf - this
    # skips those calls cleanly rather than passing a dict/list into a
    # function that only accepts strings.
    if isinstance(actual_value, str):
        validate_expression(
            expr_content=actual_value,
            line_info=line_info,
            state=state,
            context_ref=step_ref or path
        )

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

def validate_input_v2(section_key, line_info, content: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str, service_value, service_id=None, **kwargs):
    if service_value is None:
        return
    if service_id == SchemaID.ACTION:
        # ACTION steps (sleep, log, call, ...) have no per-value JSON
        # schema doc the way a SERVICE value like 'Hubspot.search' does -
        # resolve_service_instruction/check_key_matches below would always
        # dead-end looking for e.g. 'call.json' and wrongly report
        # "no such service". The python function's own kwargs ARE the
        # input schema for an action (already established elsewhere in
        # this file - see _resolve_use_target's docstring), and whichever
        # action-specific validator is registered (e.g. call_validator for
        # 'call') already owns checking that step's 'input:' against
        # whatever's appropriate for it - nothing further to do here.
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
    key_matched_items = key_matches.get("found_items", {})
    matched_items = key_matched_items.get("matched_items", {}) if key_matched_items else {}
    if not matched_items:
        state.add_error(f"in Line {line_info} {step_ref} ⚠️ [System] File not found: {file_path}, no such service")
        return

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
            
        # validate_expression call removed here - superseded by
        # check_step_validity's primitive-hook wiring, which now covers
        # this same input key's value (and any nested value this loop
        # never reached, since it only ever looked at content.items()
        # directly, one level deep).

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
    now = None
    if e := service_val.split(".")[-1] == "now":
        now = e
        

    interval = str(current_step.get('interval') or current_step.get('args', {}).get('interval'))
    
    if not interval or now:
        # If it's mandatory but missing, add error (or let check_step_validity handle it)
        state.add_error(
            f"in line {line_info}: [{step_ref}] Validation Error: The 'timer' service require a specific action to be taken. use case: timer.interval or timer.now ...."
        )
        return
    
    line_name = interval or current_step

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

def import_validator(section_key: Any, content: List[Dict[str, Any]] | Dict[str, Any], registry: PiperRegistry, state: Optional[ValidationState] = None, original_key: str="", previous_key: str="", current_file_path: Optional[str] = None, visited_files: Optional[set] = None, **kwargs) -> List:
    """
    Validates top-level import blocks, recursively loads external YAML files,
    and runs the main validator across imported sub-registries while guarding 
    against self-imports and cyclic loops.
    """
    if state is None:
        state = ValidationState()

    import_state_init = ValidationState()

    if visited_files is None:
        visited_files = set()
        # Seed the visited set with the file currently being validated so that
        # cycles which loop back to the root file (A -> B -> A) are caught,
        # not just direct self-imports (A -> A).
        if current_file_path:
            visited_files.add(os.path.abspath(current_file_path))

    # 1. Run standard core validation first
    #
    # state.errors is the ONE shared error list for the entire document
    # walk, not scoped to this import block - core_validator's shape check
    # here can only ever ADD to it, it never starts clean. Checking
    # "if state.errors" therefore bails on ANY earlier, unrelated error
    # anywhere else in the file (e.g. a typo'd input key three steps
    # earlier) before this function ever reaches the alias-registration
    # loop below (state.import_map[alias] = file_path). That produces a
    # misleading cascade: a typo elsewhere makes every 'use:' reference
    # report "Unknown import alias" even though the import: block itself
    # is fine. Snapshot the count before/after so the guard only fires on
    # errors this call itself just added.
    errors_before = len(state.errors)
    core_validator(section_key=section_key, content=content, registry=registry, state=state)

    if len(state.errors) > errors_before:
        return state.errors

    from_key = registry.get_key_from_id(SchemaID.FROM)
    as_key = registry.get_key_from_id(SchemaID.AS)

    if isinstance(content, dict):
        content = [content]

    # Ensure a place for 'use' references to resolve their alias against later,
    # regardless of whether ValidationState declares the attribute up front.
    if getattr(state, "import_map", None) is None:
        state.import_map = {}

    # 2. Extract import paths safely and check for self-imports/cycles
    for c in content:
        if isinstance(c, dict) and from_key in c: 
            raw_path = c[from_key]
            # Convert dot-notation (e.g., file.external_script.go) to an
            # absolute file path -- see resolve_dsl_import_path().
            file_path = resolve_dsl_import_path(raw_path)

            # --- SELF-IMPORT CHECK ---
            normalized_current = os.path.abspath(current_file_path) if current_file_path else None
            if normalized_current and os.path.normpath(file_path) == os.path.normpath(normalized_current):
                state.add_error(f"file {file_path}: \n           System Error: Self-Import detected. File '{raw_path}' is attempting to import itself.")
                continue

            # --- CIRCULAR DEPENDENCY CHECK ---
            if file_path in visited_files:
                state.add_error(f"System Error: Circular dependency detected. File '{file_path}' is part of an import loop.")
                continue

            # --- REGISTER ALIAS FOR 'use' RESOLUTION ---
            # Only a valid, non-cyclic import is worth exposing to 'use:' -
            # this is what use_validator looks up by alias later.
            
            alias = c.get(as_key) or c.get(from_key)
            if alias:
                state.import_map[alias] = file_path

            # Add current file to visited set for deeper recursive child validations
            next_visited = visited_files.copy()
            next_visited.add(file_path)

            yml_file = load_yaml_with_metadata(file_path)
            import_registry, import_state = get_registry_package(yml_file)
            
            # Recursively pass down the history tracker
            import_state = main_validator(dsl_file=yml_file, registry=import_registry, state=import_state_init, visited_files=next_visited)

            # --- PROPAGATE NESTED IMPORT MAP UPWARD ---
            # import_state.import_map was built while main_validator recursed
            # into this imported file's OWN 'import:' block (A -> B -> C).
            # Without this, that map dies with import_state the moment we've
            # pulled .info/.warnings/.errors off it below, and it's not a
            # single validated source of truth: a 'use:' reference for an
            # alias that only exists inside B's import block resolves fine
            # *while B is being validated on its own*, but state.import_map
            # up here at the top only ever had this file's (A's) own direct
            # aliases in it. Folding nested_import_map up means state.import_map
            # ends up holding every alias reachable anywhere in the import
            # tree, not just depth-1 ones -- so use_interpreter/use_validator
            # never have to care how deep the alias they're resolving lives.
            #
            # setdefault so an alias name declared directly in THIS file's
            # 'import:' block always wins over a same-named alias found
            # deeper in the tree -- this file's own 'use:' references were
            # written against its own aliases, and a nested file re-using
            # the same alias string for something else must not shadow them.
            nested_import_map = getattr(import_state, "import_map", None) or {}
            for nested_alias, nested_path in nested_import_map.items():
                state.import_map.setdefault(nested_alias, nested_path)

            if import_state.info:
                state.add_info(f"file {file_path}: \n     {import_state.info}")
            if import_state.warnings:
                state.add_warning(f"file {file_path}: \n   {import_state.warnings}")
            if import_state.errors:
                state.add_error(f"file {file_path}:  \n       {import_state.errors}")
                
    return state

def from_validator(state: ValidationState, step_ref: str, value: str, line_info, **kwargs):
    """Checks if a file path exists based on root path conversion, else flags an error."""
    if isinstance(value, str):
        # Convert dot-notation (e.g., template.client_temp.waterfall.waterfall)
        # to an absolute file path -- see resolve_dsl_import_path().
        file_path = resolve_dsl_import_path(value)

        if not os.path.exists(file_path):
            state.add_error(
                f"Line {line_info}: [{step_ref}]:"
                f"System Error: Imported file path does not exist: '{file_path}'."
            )

def validate_script(key, current_step: Dict, registry: PiperRegistry, state: ValidationState, step_ref: str, value: str, **kwargs):
    available_lang = ["python", "javascript"]
    runtime = current_step.get("runtime")
    if not runtime:
        return
    if not runtime in available_lang:
        state.add_error(f"Error: Unsupported runtime: {runtime}. valid runtime {available_lang}")

def _find_step_by_id(dsl_file: Dict[str, Any], target_id: str) -> Optional[Dict[str, Any]]:
    """
    Walks every step-bearing section of a parsed DSL file (pipeline, trigger,
    on_success, on_error, on_complete -- and any 'steps' / 'condition' blocks
    nested inside those steps) looking for a step dict whose 'id' matches
    target_id. Returns the first match, or None.
    """
    if not isinstance(dsl_file, dict):
        return None

    top_level_sections = ("pipeline", "trigger", "on_success", "on_error", "on_complete")
    nested_keys = ("steps", "condition")

    def _walk(node):
        if isinstance(node, dict):
            if node.get("id") == target_id:
                return node
            for nk in nested_keys:
                if nk in node:
                    found = _walk(node[nk])
                    if found is not None:
                        return found
            return None
        if isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found is not None:
                    return found
        return None

    for section in top_level_sections:
        found = _walk(dsl_file.get(section))
        if found is not None:
            return found

    return None


def _resolve_use_target(value: str, registry, state):
    """
    Resolves a 'use: <alias>.<id>' reference down to the referenced step's
    service/action config_keys, without reporting any errors itself.

    core_validator calls this BEFORE its per-step schema checks run, so that
    a 'use' step's allowed/mandatory-key schema is built from whatever
    service the referenced step actually declares (e.g. 'timeout',
    'max_attempts' overrides) - exactly like a native step gets from its own
    'service' key. Without this, core_validator's blanket "skip service
    resolution for 'use' steps" left those override keys out of the schema
    entirely, so any 'use' step that legitimately set e.g. `timeout: 10`
    got flagged as an "Unauthorized child key" - a false positive.

    use_validator (below) is still the single place that actually reports
    'use:' errors (bad alias, missing target, missing mandatory input,
    wrong placement) - this helper only answers "what keys would be valid
    here", silently, so core_validator can fold them into its schema.

    Returns a 3-tuple (config_keys, target_service_id, target_service_value):
      - config_keys: {} on any failure to resolve (bad alias, missing
        target, no service on the target, etc.) - use_validator will
        surface the real error message for that separately. Comes from
        get_service_keys/get_action_keys, i.e. the PYTHON FUNCTION
        SIGNATURE of the generic per-prefix executor - this is the right
        source for "what top-level override keys does this step accept"
        (timeout, max_attempts, ...), but it is NOT the per-service field
        list (e.g. HubSpot search's 'value' nested inside its JSON body
        template) - callers that need the real accepted 'input:' field
        names for a SERVICE-type target should resolve that separately via
        resolve_service_instruction()/check_key_matches() against
        target_service_value, the same way validate_input_v2 does for
        native steps. Using config_keys for that instead produces false
        "not an accepted input key" positives.
      - target_service_id / target_service_value: the resolved target's
        SchemaID.SERVICE/SchemaID.ACTION and its string value (e.g.
        'Hubspot.search'), or (None, None) on any resolution failure.
    """
    if not isinstance(value, str) or "." not in value:
        return {}, None, None

    alias, target_id = value.rsplit(".", 1)
    if target_id == "main":
        return {}, None, None

    import_map = getattr(state, "import_map", None) or {}
    file_path = import_map.get(alias)
    if not file_path or not os.path.exists(file_path):
        return {}, None, None

    imported_yml = load_yaml_with_metadata(file_path)
    if not imported_yml:
        return {}, None, None

    target_step = _find_step_by_id(imported_yml, target_id)
    if target_step is None:
        return {}, None, None

    service_map = {SchemaID.SERVICE: get_service_keys, SchemaID.ACTION: get_action_keys}
    target_service_list = [k for k in target_step.keys() if registry.id_map.get(k) in service_map]
    if not target_service_list:
        return {}, None, None

    target_service_key = target_service_list[0]
    target_service_id = registry.id_map.get(target_service_key)
    target_service_value = target_step.get(target_service_key)
    resolve_func = service_map.get(target_service_id)

    # A throwaway state so a resolution failure inside get_service_keys/
    # get_action_keys (e.g. "no handler for prefix") doesn't silently land
    # duplicate errors on the real ValidationState - use_validator's own
    # call (with the real state) is what actually surfaces that.
    quiet_state = ValidationState()
    try:
        config_keys = resolve_func(
            value=target_service_value, registry=registry, key=target_service_key,
            state=quiet_state, step_ref=""
        ) or {}
    except Exception:
        config_keys = {}

    return config_keys, target_service_id, target_service_value


def _resolve_use_chain(alias: str, target_id: str, registry, state, line_info, step_ref: str,
                        original_value: str, visited: Optional[List[tuple]] = None) -> Optional[Dict[str, Any]]:
    """
    Recursively follows a 'use: alias.target_id' reference across as many
    files as it takes to land on a step that has an actual service/action
    of its own - i.e. handles 'use' calling into a step that is itself
    'use: other_alias.other_id' in a different file, chained arbitrarily
    deep, the same way the compiler's _resolve_use_node already does at
    compile time (see compiler.py). Previously use_validator only ever
    resolved ONE hop: if the target step had no service/action key it
    just returned early ("nothing further to check"), silently skipping
    the mandatory-input and placement checks for every hop past the
    first. This closes that gap by resolving all the way to the real
    terminal step (or to a genuine dead end) before use_validator's
    mandatory-input/placement checks ever run.

    Each hop reuses the exact same alias -> file_path lookup
    (state.import_map) and step lookup (_find_step_by_id) as the
    single-hop code this replaces, so error wording for a given hop is
    unchanged - the only difference is that failures on hop 2+ now
    surface too, with the chain walked so far attached for
    debuggability, instead of being silently unreachable.

    Cycle guard: `visited` accumulates every (alias, target_id) pair
    resolved so far in this chain. If the same pair is seen again, that's
    a 'use' cycle (A's step uses B's step which uses back to A's step)
    rather than a legitimate dead end - report it explicitly and stop,
    since nothing here previously stopped that from recursing forever.

    A step that resolves to a 'use: alias.main' link mid-chain is treated
    as a terminal, not a dead end: 'main' splices a whole file's sections
    rather than one step, so there is no single service/action to keep
    resolving or to run mandatory-input/placement checks against inside
    this helper. The top-level 'use: alias.main' branch earlier in
    use_validator already walks every node of a directly-referenced
    'main' file; a 'main' link reached indirectly, in the middle of a
    chain, does not get that same per-node walk here.

    Returns the final resolved target_step dict once it has a real
    service/action key, or None if the chain dead-ended (an error has
    already been added to `state`) or terminated at a 'main' link.
    """
    if visited is None:
        visited = []

    chain_so_far = " -> ".join(f"{a}.{t}" for a, t in visited)

    if (alias, target_id) in visited:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'use: {original_value}' forms a circular chain: "
            f"{chain_so_far} -> {alias}.{target_id}."
        )
        return None

    visited = visited + [(alias, target_id)]
    hop_note = f" (resolving chain {chain_so_far} -> {alias}.{target_id})" if chain_so_far else ""

    import_map = getattr(state, "import_map", None) or {}
    file_path = import_map.get(alias)
    if not file_path:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'use: {original_value}' dead-ends at unknown import "
            f"alias '{alias}'{hop_note}. Make sure the top-level 'import:' block declares it with "
            f"'as: {alias}'."
        )
        return None

    if not os.path.exists(file_path):
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'use: {original_value}' dead-ends: imported file for "
            f"alias '{alias}' does not exist: '{file_path}'{hop_note}."
        )
        return None

    imported_yml = load_yaml_with_metadata(file_path)
    if not imported_yml:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'use: {original_value}' dead-ends: could not parse "
            f"imported file '{file_path}' for alias '{alias}'{hop_note}."
        )
        return None

    if target_id == "main":
        # Terminal, not a dead end - see docstring. Nothing further to
        # resolve or check against a single step here.
        return None

    target_step = _find_step_by_id(imported_yml, target_id)
    if target_step is None:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'use: {original_value}' dead-ends: no step with id "
            f"'{target_id}' found in imported file '{file_path}' (alias '{alias}'){hop_note}."
        )
        return None

    use_key = registry.get_key_from_id(SchemaID.USE)
    if use_key and isinstance(target_step, dict) and use_key in target_step:
        next_value = target_step.get(use_key)
        if not isinstance(next_value, str) or "." not in next_value:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'use: {original_value}' dead-ends: step "
                f"'{target_id}' in '{file_path}' (alias '{alias}') has an invalid 'use' reference "
                f"'{next_value}'{hop_note}."
            )
            return None
        next_alias, next_target_id = next_value.rsplit(".", 1)
        return _resolve_use_chain(
            next_alias, next_target_id, registry, state, line_info, step_ref, original_value, visited
        )

    return target_step

def action_validator(section_key: str, line_info, content: Any, key: str, value: str, registry, state,
                   step_ref: str, current_step: Optional[Dict] = None, previous_key: str = "", **kwargs) -> None:
    """
    Validates an 'action: <name>' step (e.g. 'action: call', 'action: sleep',
    'action: goto'). Mirrors validate_service_v2's architecture for
    'service:' steps, since 'action' now carries the same 'prefix' shape in
    the schema (v1_0.py) - one entry per registered action name, each with
    its own 'top_level_parent' and optional 'validator':

      1. Resolve 'value' (e.g. 'call') against action's 'prefix' dict. An
         action name that isn't registered there is a hard error - it can
         never have a handler, unlike a typo'd service prefix which at
         least resolves to native_namespace's fallback.
      2. Confirm the CURRENT top-level section is an allowed placement for
         that action (top_level_parent), same check validate_service_v2
         does for services.
      3. Hand off to that action's own registered validator, if any (e.g.
         'call' -> call_validator, for the local-'use'-style target
         resolution 'call' needs on top of its own target/type contract -
         plain actions like 'sleep'/'goto' have none, and skip this step).
         Some prefix validators here are registered as a "module.func_name"
         string rather than a direct reference (see 'validate_timer' used
         by several other action prefixes) - every one of those lives in
         this module, so resolve the string against THIS module's own
         namespace before calling.
    """
    key_content = registry._raw.get(key, {}) or {}
    prefix_content = key_content.get("prefix", {}) or {}
    cont = prefix_content.get(value)

    if cont is None:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] Unknown action '{value}'. "
            f"Registered actions: {sorted(prefix_content.keys())}."
        )
        return

    top_parent = cont.get("top_level_parent")
    # log_key (threaded through validate_recursive's original_key
    # forwarding) resolves to the true top-level section this step lives
    # under even when nested inside someone else's 'steps:' block;
    # previous_key alone would just be 'steps' in that case.
    top_section_key = kwargs.get("log_key") or previous_key or section_key
    current_section_id = registry.id_map.get(top_section_key)

    if top_parent and current_section_id and current_section_id not in top_parent:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] '{top_section_key}' does not support "
            f"the action type '{value}'."
        )
        return

    prefix_validator = cont.get("validator")
    if isinstance(prefix_validator, str):
        prefix_validator = globals().get(prefix_validator.rsplit(".", 1)[-1])

    if callable(prefix_validator):
        prefix_validator(
            section_key=section_key,
            line_info=line_info,
            content=content,
            key=key,
            value=value,
            registry=registry,
            state=state,
            step_ref=step_ref,
            current_step=current_step,
            previous_key=previous_key,
            **kwargs
        )


def _resolve_call_chain(dsl_file, target_id: str, registry, state, line_info, step_ref: str,
                         original_target: str, visited: Optional[List[tuple]] = None):
    """
    Local-search mirror of _resolve_use_chain: follows a 'call' target's id
    within 'dsl_file' to its step, and if THAT step has no service/action
    of its own because it is itself another 'use:' or 'action: call',
    keeps resolving instead of stopping at the first hop - the local
    equivalent of use_validator chasing a 'use' that points at another
    'use'. A 'use:' hop crosses into whatever file state.import_map
    resolves it to (via the existing _resolve_use_chain, unchanged); a
    'call' hop keeps searching THIS SAME dsl_file, since 'call' has no
    cross-file concept.

    'visited' accumulates (id(dsl_file), target_id) pairs - keyed on the
    file's identity, not just the id, since the same id string could
    legitimately exist in two different files reached via a 'use' hop
    partway through the chain - to catch a cycle across an arbitrary mix
    of local 'call' hops and cross-file 'use' hops.

    Returns the final resolved target_step dict once it has a real
    service/action key, or None if the chain dead-ended/cycled (an error
    has already been added to `state`).
    """
    if visited is None:
        visited = []

    file_marker = (id(dsl_file), target_id)
    if file_marker in visited:
        chain_so_far = " -> ".join(t for _, t in visited)
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'action: call' targeting '{original_target}' forms a "
            f"circular chain: {chain_so_far} -> {target_id}."
        )
        return None
    visited = visited + [file_marker]

    target_step = _find_step_by_id(dsl_file, target_id)
    if target_step is None:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'action: call' targeting '{original_target}' dead-ends: "
            f"no step with id '{target_id}' found in this file."
        )
        return None

    use_key = registry.get_key_from_id(SchemaID.USE)
    if use_key and use_key in target_step:
        next_value = target_step.get(use_key)
        if not isinstance(next_value, str) or "." not in next_value:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'action: call' targeting '{original_target}' dead-ends: "
                f"step '{target_id}' has an invalid 'use' reference '{next_value}'."
            )
            return None
        next_alias, next_use_target_id = next_value.rsplit(".", 1)
        # Crossing into a different file - _resolve_use_chain owns
        # resolution (and its own cycle guard) from here on; it does not
        # continue into a further 'action: call' hop on the other side,
        # since 'call' is a local-only concept for whichever file it's
        # written in. If that's ever needed, the deeper fix belongs in
        # _resolve_use_chain itself, not here.
        return _resolve_use_chain(
            next_alias, next_use_target_id, registry, state, line_info, step_ref, original_target
        )

    action_key = registry.get_key_from_id(SchemaID.ACTION)
    if action_key and target_step.get(action_key) == "call":
        next_target_id = target_step.get("target")
        if not next_target_id or not isinstance(next_target_id, str):
            # target's own missing 'target' - its own mandatory-key check
            # (when IT gets validated as a step) reports that; nothing
            # further to chase here.
            return target_step
        return _resolve_call_chain(
            dsl_file, next_target_id, registry, state, line_info, step_ref, original_target, visited
        )

    return target_step


def call_validator(section_key: str, line_info, content: Any, key: str, value: str, registry, state,
                   step_ref: str, current_step: Optional[Dict] = None, previous_key: str = "", **kwargs) -> None:
    """
    Validates an 'action: call' step - a LOCAL 'use': instead of resolving
    into an imported file via state.import_map/an alias, 'target' names a
    step's 'id' inside THIS SAME file, and this checks that step's own
    service/action config the same way use_validator checks a cross-file
    'use:' target.

    DSL shape - 'target'/'type' are call's OWN config_keys (from
    get_action_keys inspecting system_functions.call's signature: target
    mandatory, type optional), so - like 'timeout' on a native 'service:'
    step (see test_pipe.yml's hubspot_create) - they are TOP-LEVEL SIBLING
    keys of the step, not nested inside 'input:'. core_validator's generic
    mandatory-key check (step 3, before any specialist runs) already
    enforces 'target' is present, using the exact same config_keys this
    function would otherwise re-derive - so this function trusts that and
    doesn't re-report a missing 'target' itself:

        - id: my_call_step
          action: call
          target: "some_local_node_id"
          type: block                 # optional, defaults to "block"
          input:                      # optional override payload, merged
            some_field: "..."         # onto the target's own input at
                                       # execution time (pipeline_executor)

    1. Resolve 'target's value against THIS file (state.dsl_file), chasing
       the chain via _resolve_call_chain if the local target is itself
       another 'use:' or 'action: call' - the local mirror of
       use_validator's _resolve_use_chain. No match/dead end/cycle ->
       error (core_validator's mandatory check only confirms the KEY
       'target' exists, never that its VALUE points at a real step - that
       gap is this function's to close).
    2. Guard against a step calling itself directly.
    3. Resolve the final target step's own service/action config, then:
       a) flag any key in THIS step's 'input:' block the target doesn't
          accept (the accepted-key check core_validator's 'use:' branch
          runs), and
       b) flag any MANDATORY key the target requires that THIS step's
          'input:' doesn't supply - exactly use_validator's step 4,
          resolved locally instead of through state.import_map.
    """
    target_id = current_step.get("target") if isinstance(current_step, dict) else None
    if not target_id or not isinstance(target_id, str):
        # core_validator's generic mandatory-key check (config_keys from
        # get_action_keys) already reports "Missing mandatory child key
        # 'target'" for this - don't duplicate it here.
        return

    dsl_file = getattr(state, "dsl_file", None)
    if not dsl_file:
        return

    if _find_step_by_id(dsl_file, target_id) is current_step:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] 'action: call' cannot target itself ('{target_id}')."
        )
        return

    errors_before_chain = len(state.errors)
    target_step = _resolve_call_chain(dsl_file, target_id, registry, state, line_info, step_ref, target_id)

    if target_step is None:
        # _resolve_call_chain (or _resolve_use_chain, if the chain crossed
        # into another file) already added the specific dead-end/cycle
        # error, unless the len check below shows nothing was added -
        # which only happens if a hop resolved cleanly to a 'use: x.main'
        # link, matching use_validator's own handling of that case.
        return

    service_map = {SchemaID.SERVICE: get_service_keys, SchemaID.ACTION: get_action_keys}
    target_service_list = [k for k in target_step.keys() if registry.id_map.get(k) in service_map]

    if not target_service_list:
        # Target is a pure condition/steps grouping with no service/action
        # of its own - nothing further to check.
        return

    target_service_key = target_service_list[0]
    target_service_id = registry.id_map.get(target_service_key)
    target_service_value = target_step.get(target_service_key)
    resolve_func = service_map.get(target_service_id)

    config_keys = resolve_func(
        value=target_service_value, registry=registry, key=target_service_key,
        state=state, step_ref=step_ref
    ) or {}

    # Same SERVICE-vs-ACTION split use_validator/core_validator's 'use:'
    # branch uses: a SERVICE target's real accepted 'input:' fields come
    # from its own JSON schema doc (resolve_service_instruction /
    # check_key_matches), NOT from config_keys (that's executor kwargs
    # like timeout, not data fields) - an ACTION target has no separate
    # schema doc, so config_keys IS the right (only) source there.
    if target_service_id == SchemaID.SERVICE and isinstance(target_service_value, str):
        accepted_input_keys = {}
        service_info = resolve_service_instruction(service_key=target_service_value)
        schema_path = service_info.get("full_path") if service_info else None
        if schema_path:
            key_matches = check_key_matches(schema_path)
            matched_items = (key_matches.get("found_items", {}) or {}).get("matched_items", {})
            if matched_items:
                accepted_input_keys = matched_items
    else:
        accepted_input_keys = config_keys

    input_key_name = registry.get_key_from_id(SchemaID.INPUT)
    current_input = current_step.get(input_key_name) if isinstance(current_step, dict) else None
    if isinstance(current_input, dict):
        for user_key in current_input:
            if user_key not in accepted_input_keys:
                state.add_error(
                    f"in Line {get_line_number(current_input, user_key)}: [{step_ref}] '{user_key}' is "
                    f"not an accepted override key for the service used by call target '{target_id}'."
                )

    # Mirrors use_validator's step 4: the target's MANDATORY keys must be
    # present in THIS step's 'input:', not just whatever's supplied being
    # accepted. Uses config_keys here (not accepted_input_keys) since
    # mandatory-ness is a property of the executor's own kwargs contract,
    # the same source use_validator checks against for a cross-file 'use:'.
    current_input_for_mandatory = current_input if isinstance(current_input, dict) else {}
    for expected_key, rules in config_keys.items():
        if rules.get("mandatory", False) and expected_key not in current_input_for_mandatory:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'action: call' targeting '{target_id}' is missing "
                f"mandatory input key '{expected_key}' required by call target '{target_id}' "
                f"(service '{target_service_value}')."
            )


def use_validator(section_key: str, line_info, content: Any, key: str, value: str, registry, state,
                   step_ref: str, current_step: Optional[Dict] = None, previous_key: str = "", **kwargs) -> None:
    """
    Validates a 'use: <alias>.<id>' reference (e.g. 'use: filego.telegram_bot10').

    'use' lets a step re-run a step defined in an imported file instead of
    declaring its own 'service'/'action'. core_validator deliberately skips
    its own MANDATORY service-shape validation for steps that carry a 'use'
    key (see the `use_key_name in step` guard in core_validator) - but it
    still merges the referenced step's config_keys into the current step's
    allowed-key schema via `_resolve_use_target`, so this function focuses
    on reporting the actual errors:

      1. Split the reference into <alias> and <target_id>.
      2. Resolve <alias> against state.import_map (populated by
         import_validator while it processed the top-level 'import:' block)
         to get the absolute path of the imported file.
      3. Load that file and search it for a step whose 'id' equals
         <target_id>. No match -> error.
      4. If found, resolve that target step's service/action config keys
         (the same way core_validator resolves them for a native step) and
         check the CURRENT step's 'input' block against the mandatory ones.
      5. Confirm the current top-level section (e.g. 'pipeline') is a valid
         placement for the target step's service type.
    """
    # --- 1. Parse "alias.target_id" ---
    if not isinstance(value, str) or "." not in value:
        state.add_error(
            f"in Line {line_info}: [{step_ref}] Invalid 'use' reference '{value}'. "
            f"Expected format 'alias.target_id' (e.g. 'filego.telegram_bot10')."
        )
        return

    # Use rsplit to safely separate the path/alias from the final item (e.g., target_id or 'main')
    alias, target_id = value.rsplit(".", 1)

    # Check if the last item equals "main"
    if target_id == "main":
        # 'main' doesn't point at one step inside the imported file the way
        # an ordinary target_id does -- it means "run that whole file's
        # pipeline in place of this step." There's no single node left for
        # an 'input' block's kwargs to bind to (step 4 below is exactly that
        # binding, and it only runs for a resolved target_step). A step that
        # writes 'use: alias.main' *and* still declares 'input' looks like it
        # was written expecting node-level parameter passing that 'main'
        # doesn't support, so flag it instead of silently dropping the kwargs.
        input_key = registry.get_key_from_id(SchemaID.INPUT)
        current_input = current_step.get(input_key) if isinstance(current_step, dict) else None
        if current_input:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'use: {value}' targets the whole imported file "
                f"('main'), not a single node -- it cannot also declare an '{input_key}' block, "
                f"since there is no target step to bind those parameters to."
            )

        # --- Confirm placement is valid for EVERY node 'main' will splice in ---
        # 🛠️ UPDATED to match the fixed compiler.py behavior: 'main' now
        # resolves to the imported file's MATCHING section only (same
        # section_key this 'use: alias.main' is written in) - NOT every
        # top-level section flattened together like it used to. A
        # 'use: alias.main' written under your own `on_error:` pulls in
        # alias's `on_error` section specifically, not its `pipeline`/
        # `trigger`/other sections. So this check now only needs to walk
        # (and validate placement for) that one matching section, and can
        # also report the case your requested: the imported file simply
        # doesn't have that section at all, so 'main' would resolve to
        # nothing.
        import_map_use = getattr(state, "import_map", None) or {}
        main_file_path = import_map_use.get(alias)
        if not main_file_path or not os.path.exists(main_file_path):
            state.add_error(
                f"in Line {line_info}: [{step_ref}] Unknown import alias '{alias}' in 'use: {value}'. "
                f"Make sure the top-level 'import:' block declares it with 'as: {alias}'."
            )
            return

        main_imported_yml = load_yaml_with_metadata(main_file_path)
        if not main_imported_yml:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] System Error: Could not parse imported file "
                f"'{main_file_path}' for alias '{alias}'."
            )
            return

        steps_key = registry.get_key_from_id(SchemaID.STEPS)
        id_key = registry.get_key_from_id(SchemaID.ID)
        # Use log_key, not previous_key: previous_key is only the
        # IMMEDIATE parent key (e.g. 'steps' when this 'use: alias.main'
        # is nested inside someone else's 'steps:' block), whereas
        # log_key is threaded through validate_recursive's original_key
        # forwarding and always resolves to the true top-level section
        # (pipeline/trigger/on_error/...) this chain ultimately lives
        # under, no matter how deeply nested.
        top_section_key = kwargs.get("log_key") or previous_key
        current_section_id = registry.id_map.get(top_section_key)

        # 🛠️ compiler.py now namespaces every id a '.main' splice produces
        # with the CALLING STEP'S OWN id (not the import alias) - so
        # "hubspot_crm_search" becomes "call_first.hubspot_crm_search" for
        # a step written as `id: call_first / use: filego.main`. A step's
        # id already has to be unique within its compiled section for
        # global_id_map to mean anything at all, so keying the namespace
        # off it makes a collision structurally impossible regardless of
        # how many times the same alias gets reused, or under how many
        # aliases the same file gets imported - no duplicate-alias
        # bookkeeping needed here anymore (there used to be a
        # state._seen_main_imports check on (top_section_key, alias) pairs
        # right here; removed, since alias identity was never actually the
        # thing that needed to be unique).
        #
        # What IS now required: the calling step must have an id of its
        # own to namespace with. Several step contexts don't mandate 'id'
        # in their base schema (see v1_0.py) - fine for an ordinary step,
        # but '.main' makes this step's id load-bearing as a namespace, so
        # it needs its own explicit check rather than inheriting whatever
        # the surrounding container happens to require.
        id_key_for_main = registry.get_key_from_id(SchemaID.ID)
        call_id = current_step.get(id_key_for_main) if isinstance(current_step, dict) else None
        if not call_id:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'use: {value}' needs its own '{id_key_for_main}' - "
                f"every node it imports gets namespaced under THIS step's id (e.g. "
                f"'{id_key_for_main}: my_call' -> 'my_call.hubspot_crm_search'), so there's nothing to "
                f"namespace with here."
            )
            return

        # 🛠️ 'main' now resolves relative to top_section_key specifically -
        # error out if the imported file has no such section (or it's empty),
        # since 'use: alias.main' would otherwise silently resolve to nothing.
        matching_section_content = main_imported_yml.get(top_section_key)
        if not matching_section_content or not isinstance(matching_section_content, list):
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'use: {value}' has nothing to import - "
                f"'{alias}' (file '{main_file_path}') has no '{top_section_key}' section "
                f"(or it's empty). 'use: alias.main' pulls in the SAME section it's written "
                f"in, so an '{top_section_key}:' entry must exist in '{alias}' to reuse here."
            )
            return

        def _walk_nodes(nodes):
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                yield n
                if steps_key and n.get(steps_key):
                    yield from _walk_nodes(n[steps_key])

        for node in _walk_nodes(matching_section_content):
            node_service_keys = [
                k for k in node.keys() if registry.id_map.get(k) == SchemaID.SERVICE
            ]
            if not node_service_keys:
                continue

            node_service_key = node_service_keys[0]
            node_service_value = node.get(node_service_key)
            if not isinstance(node_service_value, str):
                continue

            node_prefix = registry.service_prefix(service_key=node_service_key, service_value=node_service_value)
            node_key_content = registry._raw.get(node_service_key, {}) or {}
            node_prefix_content = (node_key_content.get("prefix") or {}).get(node_prefix, {}) or {}
            node_top_parent = node_prefix_content.get("top_level_parent")

            if node_top_parent and current_section_id and current_section_id not in node_top_parent:
                node_id = node.get(id_key, "<unknown>")
                state.add_error(
                    f"in Line {line_info}: [{step_ref}] 'use: {value}' would place '{node_id}' "
                    f"(from '{alias}' section '{top_section_key}', service prefix '{node_prefix}') "
                    f"under '{top_section_key}', which that service type does not support."
                )

        return

    

    # --- 2/3. Resolve the alias -> file -> step, following the chain
    # recursively if the resolved step is itself another 'use' reference
    # (possibly into yet another file). _resolve_use_chain reports the
    # specific hop where resolution dead-ends (unknown alias, missing
    # file, unparsable file, missing step id, or a cycle) via
    # state.add_error and returns None in that case; a None return here
    # with no NEW error means the chain terminated cleanly at a 'main'
    # link mid-chain, which isn't a single step to check further.
    errors_before_chain = len(state.errors)
    target_step = _resolve_use_chain(alias, target_id, registry, state, line_info, step_ref, value)

    if target_step is None:
        if len(state.errors) == errors_before_chain:
            # Chain resolved cleanly but ended at 'use: alias.main' -
            # nothing further to check against a single step.
            return
        # A dead end (or cycle) was hit partway through the chain -
        # _resolve_use_chain already added the specific error.
        return

    # --- 4. Resolve the target step's service/action config keys ---
    service_map = {SchemaID.SERVICE: get_service_keys, SchemaID.ACTION: get_action_keys}
    target_service_list = [k for k in target_step.keys() if registry.id_map.get(k) in service_map]

    if not target_service_list:
        # The used step has no service/action of its own (e.g. it's a pure
        # condition/steps grouping) -- nothing further to check.
        return

    target_service_key = target_service_list[0]
    target_service_id = registry.id_map.get(target_service_key)
    target_service_value = target_step.get(target_service_key)
    resolve_func = service_map.get(target_service_id)

    config_keys = resolve_func(
        value=target_service_value,
        registry=registry,
        key=target_service_key,
        state=state,
        step_ref=step_ref
    ) or {}

    # Check the CURRENT step's 'input' block against the target's mandatory keys.
    current_input = {}
    if isinstance(current_step, dict):
        input_key = registry.get_key_from_id(SchemaID.INPUT)
        current_input = current_step.get(input_key) or {}

    for expected_key, rules in config_keys.items():
        if rules.get("mandatory", False) and expected_key not in current_input:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] 'use: {value}' is missing mandatory input key "
                f"'{expected_key}' required by '{target_id}' (service '{target_service_value}')."
            )

    # --- 5. Confirm placement is valid for the target service's prefix ---
    if target_service_id == SchemaID.SERVICE and isinstance(target_service_value, str):
        prefix = registry.service_prefix(service_key=target_service_key, service_value=target_service_value)
        key_content = registry._raw.get(target_service_key, {}) or {}
        prefix_content = (key_content.get("prefix") or {}).get(prefix, {}) or {}
        top_parent = prefix_content.get("top_level_parent")
        # log_key (threaded through validate_recursive) resolves to the
        # true top-level section this step lives under even when nested
        # inside someone else's 'steps:' block; previous_key alone would
        # just be 'steps' in that case, which never matches top_parent.
        top_section_key = kwargs.get("log_key") or previous_key
        current_section_id = registry.id_map.get(top_section_key)

        if top_parent and current_section_id and current_section_id not in top_parent:
            state.add_error(
                f"in Line {line_info}: [{step_ref}] '{top_section_key}' does not support the service type "
                f"used by '{target_id}' (prefix '{prefix}')."
            )
