import json
import os
from shared.unpacked_data import UnZip
from functools import partial
import re
import inspect
import os
from dotenv import load_dotenv
import importlib
import yaml
from shared.auth_manager import start_auth_flow
from shared.tools import get_auth_config_file
from shared.tools import inspect_function, crawler, replace_place_value_v3, replace_place_value, retrieve_file, open_json_file, check_key_matches, input_manager
from typing import Dict, Any, List
from shared.tools import retrieve_file, replace_place_value, crawler, missing_field, load_schema_registry, missing_field_v2
from shared.registry_V2 import PiperRegistry
from shared.database_manager import ContextDB
from shared.tools import resolve_service_instruction
from shared.reg_schema.schemaid import SchemaID
from shared.compiler import WorkflowCompiler
from shared.tools import load_yaml_with_metadata
# Reused so import/use resolve paths and targets exactly like
# import_validator / use_validator do at validation time - one shared
# implementation instead of two that could quietly drift apart.
from shared.validators_V2 import resolve_dsl_import_path, _find_step_by_id

class PiperInterpreter:
    def __init__(self, registry, crypto_engine=None):
        self.registry = registry
        self.crypto_engine = crypto_engine
        self.manifest = {}

    @classmethod
    async def create(cls, registry, dsl_file, name, crypto_engine=None, state=None, current_file_path=None, visited_files=None):
        # Now this matches the __init__ above
        instance = cls(registry, crypto_engine) 
        
        # This performs the actual manifest generation
        await instance.build_manifest(dsl_file, name, state=state, current_file_path=current_file_path, visited_files=visited_files)
        return instance
    
    async def build_manifest(self, dsl_file: Dict[str, Any], name: str, state=None, current_file_path=None, visited_files=None) -> Dict[str, Any]:
        """
        The entry point. Converts DSL into the final execution dictionary.

        'state' is the ValidationState main_validator already produced for
        this file (see setup_build.builder, which validates before it ever
        calls PiperInterpreter.create). Threading it through here - into
        every section, not just 'import' - means state.import_map (built
        once, by import_validator, before interpretation starts at all) is
        already available to use_interpreter regardless of which section
        happens to contain the 'use:' step, or what order dsl_file.items()
        iterates sections in. Previously use_interpreter could only resolve
        an alias if import_interpreter had already run for THIS build and
        populated registry.import_map first - an ordering dependency on
        'import:' being processed before 'pipeline:' that no longer exists.
        """
        # Process top-level sections
        for section, content in dsl_file.items():
            # If it's a workflow section (like 'pipeline' or 'on_start')
            # current_file_path/visited_files only matter to import_interpreter
            # (self-import/circular-import guard when no validated state is
            # available), but are passed to every section uniformly since
            # every interpreter accepts **kwargs.
            self.manifest[section] = await self.registry.interpreter_map.get(section)(
                key=section, content=content, registry=self.registry,
                crypto_engine=self.crypto_engine, name=name, state=state,
                current_file_path=current_file_path, visited_files=visited_files
            )
        return self.manifest
    
async def condition_interpreter(content, *args, **kwargs):
    return content

async def import_interpreter(key, content, registry, crypto_engine, name, state=None, current_file_path=None, visited_files=None, **kwargs):
    """
    Executes the 'import:' block. Path resolution now prefers the exact
    mapping import_validator already built during validation
    (state.import_map: alias -> absolute file_path), instead of
    re-resolving/re-checking paths itself - validation already ran to
    completion, self-import/circular-import guards included, before
    setup_build.builder ever calls PiperInterpreter.create. Reusing that
    map means a path that validated against one file can never load a
    *different* file at interpretation time, and 'use:' resolution (see
    use_interpreter) is no longer dependent on this function having
    already run for this build.

    If no validated state/import_map is available for this alias (e.g.
    the interpreter is invoked directly without validating first, or a
    nested imported file whose own 'import:' block wasn't captured in the
    parent's state), this falls back to resolving the path itself with
    resolve_dsl_import_path plus the same self-import/circular guards
    import_validator uses - so interpretation never silently skips an
    import, it just loses the "single validated source of truth"
    guarantee for that one alias.
    """
    from_key = registry.get_key_from_id(SchemaID.FROM)
    as_key = registry.get_key_from_id(SchemaID.AS)

    import_manifest = {}

    if isinstance(content, dict):
        content = [content]

    import_map = getattr(state, "import_map", None) or {}

    if visited_files is None:
        visited_files = set()
        if current_file_path:
            visited_files.add(os.path.abspath(current_file_path))

    for c in content:
        if not (isinstance(c, dict) and from_key in c):
            continue

        raw_path = c[from_key]
        alias = c.get(as_key) or c.get(from_key)

        file_path = import_map.get(alias)

        if not file_path:
            # No validated mapping for this alias - fall back to
            # resolving/guarding it ourselves. Same resolver
            # import_validator uses - see resolve_dsl_import_path.
            file_path = resolve_dsl_import_path(raw_path)

            normalized_current = os.path.abspath(current_file_path) if current_file_path else None
            if normalized_current and os.path.normpath(file_path) == os.path.normpath(normalized_current):
                raise ValueError(f"Self-Import detected. File '{raw_path}' is attempting to import itself.")

            if file_path in visited_files:
                raise ValueError(f"Circular dependency detected. File '{file_path}' is part of an import loop.")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Import target path '{file_path}' does not exist.")

        next_visited = visited_files.copy()
        next_visited.add(file_path)

        yml_file = load_yaml_with_metadata(file_path)

        import_cont = await PiperInterpreter.create(
            registry=registry,
            dsl_file=yml_file,
            name=name,
            crypto_engine=crypto_engine,
            current_file_path=file_path,
            visited_files=next_visited,
        )

        import_manifest[alias] = import_cont.manifest

    return import_manifest
    
async def core_interpreter(key: str, content: List, registry, crypto_engine, name, original_key: str = "", state=None, **kwargs):

    # 🛠️ FIX: was `else: key` - a bare expression that evaluates `key` and
    # discards it, so `interpreter_key` was never actually assigned in this
    # branch. It's needed now to thread the current top-level section name
    # (e.g. "pipeline", "on_error") down into use_interpreter, so a
    # `use: alias.main` step resolves against the MATCHING section of the
    # imported file - the same section_key convention already used in
    # compiler.py (_compile_nodes) and validators_V2.py (use_validator).
    if original_key:
       interpreter_key = original_key
    else:
        interpreter_key = key
    
    if not isinstance(content, list):
        content = [target_content] 
    executable_block = []
    service_prefix = None
    for n, step in enumerate(content):

        # 0. 'use' steps are resolved as a whole, not key-by-key: find the
        # 'use' key up front and, if present, hand the entire step off to
        # use_interpreter, which pulls in the target step from the
        # imported file, layers this step's own keys on top of it, and
        # builds the result through this same function - reusing the
        # normal service/input resolution below instead of duplicating it.
        use_key_name, use_value = None, None
        for k, v in step.items():
            if registry.id_map.get(k) == SchemaID.USE:
                use_key_name, use_value = k, v
                break

        if use_key_name:
            entry = await use_interpreter(
                content=use_value, key=use_key_name, registry=registry,
                crypto_engine=crypto_engine, name=name, step=step, state=state,
                section_key=interpreter_key
            )
            # 🛠️ FIX: 'use: alias.main' now returns a LIST of already-
            # interpreted nodes (the matching section from the imported
            # file), not a single dict - appending it as one entry would
            # nest an entire node-list inside what's supposed to be one
            # step. An ordinary 'use: alias.step_id' still returns a single
            # dict as before.
            if isinstance(entry, list):
                executable_block.extend(entry)
            else:
                executable_block.append(entry)
            continue

        entry = {}
        service_prefix = None
        service_config_keys = {}
        path = None

        # 1. First Pass: Resolve Service and Config
        for k, v in step.items():
            if registry.id_map.get(k) == SchemaID.SERVICE:
                service_prefix = registry.service_prefix(service_key=k, service_value=v)
                info = resolve_service_instruction(v)
                path = info.get("full_path")
                service_config_keys = service_func_config_keys(registry, step, k, service_prefix)
                entry["execution"] = {**service_config_keys}
                entry["execution_type"] = k

        for key, value in step.items():

            specialist = registry.interpreter_map.get(key)
            if not specialist:
                if key in registry._raw:
                    entry[key] = value
                continue

            # 2. Execute the specialist
            result = await specialist(
                content=value,
                key=key,
                registry=registry,
                crypto_engine=crypto_engine,
                name=name,
                service_prefix=service_prefix,
                service_path=path,
                service_config_keys=service_config_keys,
                step=step,
                state=state
            )

            if registry.id_map.get(key) == SchemaID.INPUT:
                entry["execution"].update(result)
            else:
                entry[key] = result


        executable_block.append(entry)

    return executable_block

async def assign_key_value(content, **kwargs):
    return content

async def use_interpreter(content, key, registry, crypto_engine, name, step, state=None, section_key=None, **kwargs):
    """
    Resolves a 'use: <alias>.<target_id>' step (e.g. 'use: filego.hubspot_crm_search'),
    the execution-time counterpart to use_validator:

      1. Split into <alias> and <target_id>.
      2. Resolve <alias> via state.import_map - the SAME mapping
         import_validator already built while validating this file's
         top-level 'import:' block, threaded down from setup_build.builder
         through PiperInterpreter.create/build_manifest. Using the
         validator's own map (rather than one import_interpreter builds at
         interpretation time) means 'use' resolution no longer depends on
         'import:' happening to be processed before whatever section holds
         this 'use' step - state.import_map is already complete before
         interpretation starts at all. Falls back to registry.import_map
         (populated by import_interpreter as it runs) only if no state was
         passed in, so this still works if the interpreter is ever invoked
         without validating first.
      3. Load that file and find the step whose 'id' equals <target_id> -
         this is "the targeted node from the other script".
      4. Layer THIS step's own keys on top of that target node: a key this
         step shares with the target (e.g. 'input', 'timeout', 'id')
         overrides the target's value; a key only this step declares gets
         added. 'use' itself is dropped so the merged node re-enters
         core_interpreter as an ordinary step and gets its service/input
         built the normal way (including build_input_v2's own "explicit
         overrides beat defaults" logic for the 'input' block).

    `section_key` is the current top-level section this 'use' step is
    written in (e.g. "pipeline", "on_error") - passed down from
    core_interpreter's `interpreter_key`. It's only used by the 'main' case
    below; an ordinary 'use: alias.step_id' still just finds that one step
    wherever it lives in the imported file, same as before.

    Note: if the target step is itself a 'use' step, the merge naturally
    carries that 'use' key through and it gets resolved again on the
    recursive core_interpreter call below (chained 'use' references work),
    but there's no cycle guard here the way import_interpreter has one for
    imports - a 'use' chain that loops back on itself will recurse until
    Python's recursion limit trips.
    """
    if not isinstance(content, str) or "." not in content:
        raise ValueError(f"Invalid 'use' reference '{content}'. Expected format 'alias.target_id'.")

    alias, target_id = content.rsplit(".", 1)

    import_map = getattr(state, "import_map", None) or getattr(registry, "import_map", None) or {}
    file_path = import_map.get(alias)

    if not file_path:
        raise ValueError(
            f"Unknown import alias '{alias}' in 'use: {content}'. "
            f"Make sure the top-level 'import:' block declares it with 'as: {alias}'."
        )

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Imported file for alias '{alias}' does not exist: '{file_path}'.")

    imported_yml = load_yaml_with_metadata(file_path)
    if not imported_yml:
        raise ValueError(f"Could not parse imported file '{file_path}' for alias '{alias}'.")

    # 'main' isn't a step id -- it's the sentinel use_validator/
    # _resolve_use_target already special-case at validation time to mean
    # "run this alias's matching section here", not "find a step called
    # main" (see v1_0.schema_reg["__main__"]: PIPELINE/TRIGGER/... are that
    # file's own top-level keys, so no step in it will ever have
    # id == "main" for _find_step_by_id to match). Validation lets
    # 'use: alias.main' through with no error, so falling through to the
    # normal step lookup below would always raise "No step with id 'main'
    # found" at interpretation time -- a guaranteed crash on input the
    # validator already accepted.
    #
    # Build a full PiperInterpreter for the imported file, the same way
    # import_interpreter does for every alias in an 'import:' block. state
    # is not threaded through here: the imported file resolves its own
    # 'use'/'import' aliases against its OWN 'import:' block, not this
    # file's, so reusing this file's state.import_map here could resolve
    # an alias name that happens to collide against the wrong file.
    # current_file_path is passed so import_interpreter's fallback
    # self-import/circular guards (see its docstring) still have something
    # to check against.
    #
    # 🛠️ FIX: previously returned `imported_interpreter.manifest` whole -
    # the ENTIRE interpreted file (pipeline, on_error, on_success,
    # on_complete all still nested as raw lists under their own keys) got
    # handed back as if it were a single step's content, then appended as
    # ONE node by core_interpreter's caller. compiler.py would then see a
    # "node" with no top-level 'id' key (its keys are 'version'/'pipeline'/
    # 'on_error'/...), producing an empty id_map and a single malformed
    # instruction entry instead of the imported pipeline's real steps -
    # exactly the "pipeline inside a pipeline, id_map empty" result.
    #
    # 'main' now returns the section MATCHING section_key (the same
    # section this 'use' step is itself written in) as a LIST of already-
    # interpreted nodes - core_interpreter's caller extends those into
    # executable_block instead of appending one blob. This mirrors the same
    # fix already applied to compiler.py's _resolve_use_node and
    # use_validator's placement check: 'use: alias.main' under your
    # `pipeline:` pulls alias's `pipeline`; under your `on_error:` pulls
    # alias's `on_error`; etc.
    #
    # No step-level override_keys are layered on for 'main', unlike the
    # ordinary target_id case below -- there's no single node here to bind
    # them to, which is exactly why use_validator now rejects an 'input'
    # block on a 'use: alias.main' step.
    if target_id == "main":
        imported_interpreter = await PiperInterpreter.create(
            registry=registry,
            dsl_file=imported_yml,
            name=name,
            crypto_engine=crypto_engine,
            current_file_path=file_path,
        )
        matching_section = imported_interpreter.manifest.get(section_key)
        if not matching_section or not isinstance(matching_section, list):
            # Defense in depth: use_validator already reports this at
            # validation time, but the interpreter can run without having
            # validated first (see docstring), so this can't just silently
            # resolve to nothing here.
            raise ValueError(
                f"'use: {content}' has nothing to import - '{alias}' (file '{file_path}') "
                f"has no '{section_key}' section (or it's empty). 'use: alias.main' pulls in "
                f"the SAME section it's written in, so an '{section_key}:' entry must exist "
                f"in '{alias}' to reuse here."
            )
        return matching_section

    target_step = _find_step_by_id(imported_yml, target_id)
    if target_step is None:
        raise ValueError(
            f"No step with id '{target_id}' found in imported file '{file_path}' (alias '{alias}')."
        )

    # Current step's own keys win; 'use' itself is never carried into the merge.
    override_keys = {k: v for k, v in step.items() if k != key}
    merged_step = {**target_step, **override_keys}

    built = await core_interpreter(
        key="use", content=[merged_step], registry=registry,
        crypto_engine=crypto_engine, name=name, state=state
    )
    return built[0] if built else {}

def service_func_config_keys(registry, step, service_key, prefix):
    handler = registry.prefix_executor(service_key, prefix)
    if not handler:
        return {}
    handler_keys = registry.hydrate_from_handler(handler)
    config_keys = {ky: vl for ky, vl in step.items() if ky in handler_keys}
    return config_keys 

async def app_service(registry, content, key: str, crypto_engine, name, service_config_keys, step, service_path, service_prefix, **kwargs):

    list_of_value = content.split(".")

    if len(list_of_value) > 1:
        app_name = list_of_value[0] if list_of_value[0] != service_prefix else list_of_value[1]
        action = list_of_value[-1]
    else:
        app_name = list_of_value[0]
        action = ""
    
    sub_interpreter = registry.prefix_interpreter(key, service_prefix)
    
    system_schema = {}
    if sub_interpreter:
        system_schema[service_prefix] = await sub_interpreter(
            key=service_prefix,
            path=service_path,
            value=content,
            service=app_name,
            client_name=name,
            crypto_engine=crypto_engine,
            current_step=step,
            registry=registry,
            prefix=service_prefix, 
            config_keys=service_config_keys
            
        )
    # Return only the description of the service
    return {
        "app": app_name,
        "action": action,
        "type": service_prefix,
        "engine_internal": system_schema
    }

async def build_input_v2(service_path, crypto_engine, name, content, **kwargs):
    
    key_matches = check_key_matches(service_path=service_path)

    app_schema = key_matches.get("app_schema")
    key_matched_items = key_matches.get("found_items", {})
    found_items = key_matched_items.get("matched_items", {}) if key_matched_items else {}

    if not found_items:
        return
    
    required_key = key_matches.get("found_items")
    required_key_path = required_key.get("key_value") if required_key else {}

    if not  required_key_path:
        return
    
    missing = missing_field(required=found_items, content_to_check=content)
    
    default_regex = r"Default\s*=\s*([\$!\.\w\d_\-\s]+)"

    if missing:   
        for m in missing:
            missing_value = str(found_items.get(m))
            match = re.search(default_regex, missing_value)
            
            if match and m not in content:
                raw_val = match.group(1).strip()
                
                # Logic: Check for escape and strip the slash
                is_escaped = raw_val.startswith("/")
                re_val = raw_val[1:] if is_escaped else raw_val
                
                # EXTRACT ONLY THE VALUE (Cleaned of the slash if it was there)
                extracted_val = f"{{{{{re_val}}}}}"
                
                # Replace surgically using the V2 logic
                app_schema = replace_place_value_v3(
                    key_path=required_key_path, 
                    content_to_modify=app_schema, 
                    key=m,
                    value=extracted_val,
                    is_metadata_replacement=True # CRITICAL
                )
                
                # Auth Logic: Skip if it was escaped
                if is_escaped:
                    continue
                
                # Standard Auth Logic
                if re_val.startswith("$env."):
                    target_service = re_val.replace("$env.", "")
                    app_path = get_auth_config_file(client_name=name, file_type="app_service", service=target_service)
                    w_f = retrieve_file(file_path=app_path, base_dir=True)
                    if w_f:
                        w_f.update({"client_name": name, "app_name": target_service})
                        await start_auth_flow(_cont=w_f, _crypto_engine=crypto_engine)
                continue

    # Handle explicit overrides
    for ke in found_items.keys():
        if ke in content:
            val = content.get(ke)
            app_schema = replace_place_value_v3(
                key_path=required_key_path, content_to_modify=app_schema, key=ke, value=val, is_metadata_replacement=False
            )        
    return {
        "_args": app_schema
    }

async def script_interpreter(current_step, value, **_kwargs):
    """
    VALIDATOR: Resolves paths and ensures the script exists.
    Returns a manifest entry, but DOES NOT execute.
    """
    content_to_modify = {}
    # 1. Resolve Extension
    RUNTIME_EXT_MAP = {
        "python": "py",
        "nodejs": "js",
        "node": "js",
        "javascript": "js"
    }
    runtime = current_step.get("runtime", "python").lower()
    ext = RUNTIME_EXT_MAP.get(runtime, "py")

    # 2. Resolve Paths
    path_parts = value.split('.')
    if path_parts[0] == "script":
        path_parts.pop(0) 
    
    relative_path = os.path.join(*path_parts) + f".{ext}"
    project_root = os.getcwd()
    absolute_script_path = os.path.abspath(os.path.join(project_root, relative_path))

    # 4. Return Metadata (The Manifest Entry)
    content_to_modify["_file_path"] = absolute_script_path
    return  content_to_modify

async def webhook_func(current_step, config_keys, prefix, service, registry, value, key, client_name, crypto_engine, **_kwargs):
    # 1. Dynamically find the key used for inputs
    input_key = None
    for k in current_step.keys():
        if registry.id_map.get(k) == SchemaID.ID:
            input_key = k
            break
    
    target_key = input_key or key

    # 2. Resolve the delete schema path
    internal_value = f"{prefix}.{service}._delete"
    info = resolve_service_instruction(internal_value)
    path = info.get("full_path")
    
    if path:
        # build_input_v2 returns a dict that usually contains {"_args": {...}}
        # We want to extract just that inner schema to avoid double-nesting
        raw_schema_result = await build_input_v2(
            path=path, 
            current_step=current_step, 
            crypto_engine=crypto_engine, 
            client_name=client_name, 
            value=internal_value, 
            key=target_key, 
            service=service, 
            content_to_modify={} 
        )
        final_keys = {**config_keys, **raw_schema_result}
        
        return {
            "args": final_keys,
            "app_name": service
        }
        
    return {}

async def timer_func():
    pass

async def version_interpreter(content, *args, **kwargs):
    # Ensure we return the value (like "1.0") so the manifest builder 
    # can pass it to the processor
    return str(content)