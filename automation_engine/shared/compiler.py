import os
import re
import copy
from shared.reg_schema.schemaid import SchemaID
from shared.registry_V2 import PiperRegistry
from shared.validators_V2 import _find_step_by_id
from shared.tools import load_yaml_with_metadata

class WorkflowCompiler:
    def __init__(self):
        pass

    def compile_block(self, manifest, registry: PiperRegistry, state=None):
        """
        Processes the manifest dictionary.
        Resets counting and maps per top-level section (e.g., trigger, pipeline),
        while allowing nested steps to share that section's sequence without isolation.

        'registry' is required now (was previously unused) so key lookups go
        through registry.get_key_from_id like the validator/interpreter do,
        instead of hardcoded "id"/"steps" strings - and so a still-unresolved
        'use' node can be inlined here too (see _resolve_use_node). 'state'
        carries state.import_map (built by import_validator at validation
        time) so that resolution uses the exact same alias -> file_path
        mapping as everywhere else, rather than re-deriving it.
        """
        compiled_manifest = {}
        
        for section_key, section_content in manifest.items():
            if isinstance(section_content, list):
                # Reset registry and id_map specifically for this section
                flat_registry = []
                global_id_map = {}
                
                self._compile_nodes(section_content, flat_registry, global_id_map, registry, state, section_key)
                
                compiled_manifest[section_key] = {
                    "instructions": flat_registry,
                    "id_map": global_id_map
                }
            else:
                compiled_manifest[section_key] = section_content
                
        return compiled_manifest

    def _compile_nodes(self, nodes, flat_registry, global_id_map, registry: PiperRegistry, state=None, section_key=None):
        """Recursively flattens nodes and nested steps into the section's shared registry.

        `section_key` is the current top-level section's raw string key (e.g.
        "pipeline", "on_error") - the same value validators_V2.py already
        threads through its own traversal (see validate_service_v2) so a
        'use: alias.main' resolves relative to WHICH section it's written in,
        not a hardcoded section. It stays constant across the recursion into
        nested 'steps', since those still belong to the same top-level section.
        """
        id_key = registry.get_key_from_id(SchemaID.ID)
        steps_key = registry.get_key_from_id(SchemaID.STEPS)
        use_key = registry.get_key_from_id(SchemaID.USE)

        if isinstance(nodes, list):
            for node in nodes:
                # 🛠️ Defensive 'use' resolution - see _resolve_use_node's
                # docstring. Splices the resolved node(s) in at this exact
                # position and lets the SAME recursion assign their
                # next_index/skip_index/index, so a chained 'use' (the
                # resolved node is itself a 'use') or a 'use: alias.main'
                # (resolves to many nodes) both fall out naturally - no
                # separate flattening pass needed.
                if use_key and isinstance(node, dict) and use_key in node:
                    resolved_nodes = self._resolve_use_node(node, use_key, registry, state, section_key)
                    self._compile_nodes(resolved_nodes, flat_registry, global_id_map, registry, state, section_key)
                    continue

                current_index = len(flat_registry)
                
                # Map node ID to its absolute index within this section
                if id_key in node:
                    global_id_map[node[id_key]] = current_index

                # 🧹 Extract and remove 'steps' from the node so it doesn't stay nested
                steps = node.pop(steps_key, None)

                # Determine initial forward links
                next_index = current_index + 1
                skip_index = current_index  # Default fallback if no steps/children

                flat_node = {
                    **node,  # Retains remaining keys (execution config, type, condition, etc.) without 'steps'
                    "next_index": next_index,
                    "skip_index": skip_index,
                    "index": current_index
                }
                
                flat_registry.append(flat_node)

                # Handle nested children recursively using the section's shared registry (no reset)
                if steps:
                    self._compile_nodes(steps, flat_registry, global_id_map, registry, state, section_key)
                    # Overwrite skip_index to point past the entire nested block
                    flat_node["skip_index"] = len(flat_registry)

        return flat_registry, global_id_map

    def _resolve_use_node(self, node, use_key, registry: PiperRegistry, state, section_key=None):
        """
        Resolves a still-unresolved 'use: <alias>.<target_id>' (or
        'use: <alias>.main') node into the list of raw step dict(s) it
        should be replaced by at THIS position, using the exact same
        alias -> file_path lookup (state.import_map) and step lookup
        (_find_step_by_id) as use_validator/_resolve_use_target
        (validators_V2.py) and use_interpreter (interpreter.py). Always
        returns a list, even for the single-target_id case, so the caller
        can splice it in with one recursive _compile_nodes call regardless
        of whether it's one node or a whole imported pipeline.

        By the time interpretation has run, core_interpreter/use_interpreter
        should already have resolved every 'use' node before compile_block
        ever sees it - this exists so the compiler doesn't produce a
        broken/incomplete instruction list if it's ever handed content that
        skipped that step. Silently returns [] on anything it can't resolve
        (unknown alias, missing file, missing target step) rather than
        raising - that resolution failure is use_validator's job to report
        with a proper error message; the compiler isn't the place to
        duplicate it.
        """
        value = node.get(use_key)
        if not isinstance(value, str) or "." not in value:
            return []

        alias, target_id = value.rsplit(".", 1)

        import_map = getattr(state, "import_map", None) or getattr(registry, "import_map", None) or {}
        file_path = import_map.get(alias)
        if not file_path or not os.path.exists(file_path):
            return []

        imported_yml = load_yaml_with_metadata(file_path)
        if not imported_yml:
            return []

        if target_id == "main":
            fallback_key = registry.get_key_from_id(SchemaID.PIPELINE)
            target_section_key = section_key or fallback_key
            matching_section = imported_yml.get(target_section_key, [])
            if not isinstance(matching_section, list):
                return []

            # 🛠️ Namespace every id this splice introduces with the
            # CALLING step's own id (not the import alias). A step's id
            # already has to be unique within its compiled section for
            # global_id_map to mean anything at all - global_id_map[id] is
            # already a flat per-section dict today, so two ordinary
            # (non-'use') steps sharing an id would silently collide there
            # too, independent of '.main' - so that uniqueness is an
            # existing assumption this leans on, not a new one. Given that,
            # prefixing with the calling step's id makes a collision
            # structurally impossible: it holds regardless of alias, so the
            # SAME alias's '.main' can be reused freely as long as it's
            # written under different step ids (it always will be, since
            # id uniqueness is what makes it a valid step to begin with) -
            # no duplicate-alias bookkeeping needed at all anymore (see the
            # removed state._compiled_main_imports tracking this used to
            # need here, and the matching state._seen_main_imports check in
            # use_validator - both gone; nothing to track when collision
            # can't happen by construction).
            #
            # See _prefix_imported_ids' docstring for why bare id-renaming
            # alone would have broken this file's own internal '$id.field'
            # cross-references (e.g. test_pipe.yml's hubspot_create ->
            # "$hubspot_crm_search.total"), and why the rewrite has to
            # travel with the rename.
            call_id_key = registry.get_key_from_id(SchemaID.ID)
            call_id = node.get(call_id_key)
            if not call_id:
                # use_validator requires '.main' steps to have their own id
                # (load-bearing now as the namespace, unlike an ordinary
                # step where a missing id is a softer gap) and reports it
                # there with a proper error - nothing to safely prefix with
                # here, so bail the same way every other unresolvable case
                # in this function does.
                return []

            return self._prefix_imported_ids(matching_section, call_id, registry)

        target_step = _find_step_by_id(imported_yml, target_id)
        if target_step is None:
            return []

        # Current node's own keys win; 'use' itself is never carried into the merge.
        override_keys = {k: v for k, v in node.items() if k != use_key}
        merged_step = {**target_step, **override_keys}
        return [merged_step]

    def _prefix_imported_ids(self, nodes, prefix_id, registry: PiperRegistry):
        """
        Namespaces every 'id' in 'nodes' (recursively through nested
        'steps') with 'prefix_id' - the id of the STEP THAT WROTE
        'use: alias.main' (not the import alias itself) - so
        "hubspot_crm_search" becomes "call_first.hubspot_crm_search" for a
        step written as `id: call_first / use: filego.main`.

        Keying off the calling step's own id instead of the alias makes a
        collision structurally impossible rather than something to detect
        after the fact: a step's id already has to be unique within its
        compiled section (global_id_map is a flat per-section dict), so
        prefixing with it guarantees every '.main' splice gets a distinct
        namespace regardless of how many times the same alias gets reused,
        or under how many different aliases the same file gets imported -
        no duplicate-alias bookkeeping needed anywhere (see the empirical
        proof that motivated namespacing in the first place: two DIFFERENT
        aliases pointing at the same file, both splicing '.main' into one
        pipeline, left global_id_map with only 3 entries instead of 6,
        silently pointing at the second copy only - alias identity was
        never actually the right thing to key uniqueness off of).

        Renaming the id alone isn't enough: this same file's own nodes can
        reference each other by BARE id in a template string - e.g.
        test_pipe.yml's hubspot_create step has
        `condition: "$hubspot_crm_search.total == 0"`, a sibling reference
        within the same imported subtree. If hubspot_crm_search's id gets
        renamed to 'call_first.hubspot_crm_search' but that condition
        string is left untouched, the condition silently starts
        referencing an id that no longer exists in the compiled output. So
        this collects the full set of ORIGINAL ids in this subtree first,
        then rewrites BOTH the id fields AND every '$<old_id>' occurrence
        found in any string value anywhere in this same subtree to
        '$<prefix_id>.<old_id>' - so referencing a namespaced node
        elsewhere (a 'call:'/'goto:' target, or a sibling condition) uses
        the SAME '<calling_step_id>.<original_id>' shape the compiled
        output itself now uses, rather than the alias.

        A reference to something OUTSIDE this subtree - the calling file's
        own trigger ('$Typeform_webhook...'), '$env.*', etc. - is never
        touched, since its id was never in the collected set to begin with.
        """
        id_key = registry.get_key_from_id(SchemaID.ID)
        steps_key = registry.get_key_from_id(SchemaID.STEPS)

        def _collect_ids(items, out):
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                if id_key in item:
                    out.add(item[id_key])
                if steps_key in item and item[steps_key]:
                    _collect_ids(item[steps_key], out)

        original_ids = set()
        _collect_ids(nodes, original_ids)
        if not original_ids:
            return copy.deepcopy(nodes)

        # Longest-first so a shorter id that happens to be a prefix of a
        # longer one never gets matched inside it - belt-and-suspenders on
        # top of the \b boundary below, which already guards this since a
        # trailing '_' or alnum char is a \w character and blocks the
        # boundary match.
        patterns = [
            (re.compile(r"\$" + re.escape(old_id) + r"\b"), f"${prefix_id}.{old_id}")
            for old_id in sorted(original_ids, key=len, reverse=True)
        ]

        def _rewrite_value(value):
            if isinstance(value, str):
                for pattern, replacement in patterns:
                    if "$" in value:
                        value = pattern.sub(replacement, value)
                return value
            if isinstance(value, dict):
                return {k: _rewrite_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_rewrite_value(v) for v in value]
            return value

        renamed = _rewrite_value(copy.deepcopy(nodes))

        def _rename_ids(items):
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                if id_key in item and item[id_key] in original_ids:
                    item[id_key] = f"{prefix_id}.{item[id_key]}"
                if steps_key in item and item[steps_key]:
                    _rename_ids(item[steps_key])

        _rename_ids(renamed)
        return renamed