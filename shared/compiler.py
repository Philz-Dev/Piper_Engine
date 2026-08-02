"""class WorkflowCompiler:
    def __init__(self):
        self.flat_registry = []
        self.global_id_map = {}

    def compile_block(self, nodes):
        # Process and compile each section of the manifest while keeping the data structure intact
        compiled_manifest = {}

        for section_key, section_content in nodes.items():
            
            if isinstance(section_content, list):
                # Instantiate a compiler per section to isolate independent execution blocks (trigger vs pipeline),
                # while allowing the compiler's internal recursion to handle nested 'steps' without resetting.
                flat_registry, global_id_map = self.compiler(section_content)
                
                compiled_manifest[section_key] = {
                    "instructions": flat_registry,
                    "id_map": global_id_map
                }
            else:
                compiled_manifest[section_key] = section_content

        return compiled_manifest

    def compiler(self, nodes):
        Recursively flattens nodes into an array with pre-computed skip indices.
        
        if isinstance(nodes, list):
            for node in nodes:
                current_index = len(self.flat_registry)
                
                # Map node ID to its absolute index for O(1) goto/call lookups
                if "id" in node:
                    self.global_id_map[node["id"]] = current_index

                flat_node = {
                    **node,  # Retains existing execution config, type, scripts, etc.
                    "skip_index": len(self.flat_registry) # Default fallback
                }
                
                self.flat_registry.append(flat_node)

                # Handle nested children recursively (post-order unwind)
                if "steps" in node and node["steps"]:
                    self.compiler(node["steps"])
                    # Overwrite skip_index to point past the entire nested block
                    flat_node["skip_index"] = len(self.flat_registry)

        return self.flat_registry, self.global_id_map"""


class WorkflowCompiler:
    def __init__(self):
        pass

    def compile_block(self, manifest):
        """
        Processes the manifest dictionary. 
        Resets counting and maps per top-level section (e.g., trigger, pipeline),
        while allowing nested steps to share that section's sequence without isolation.
        """
        compiled_manifest = {}
        
        for section_key, section_content in manifest.items():
            if isinstance(section_content, list):
                # Reset registry and id_map specifically for this section
                flat_registry = []
                global_id_map = {}
                
                self._compile_nodes(section_content, flat_registry, global_id_map)
                
                compiled_manifest[section_key] = {
                    "instructions": flat_registry,
                    "id_map": global_id_map
                }
            else:
                compiled_manifest[section_key] = section_content
                
        return compiled_manifest

    def _compile_nodes(self, nodes, flat_registry, global_id_map):
        """Recursively flattens nodes and nested steps into the section's shared registry."""
        if isinstance(nodes, list):
            for node in nodes:
                current_index = len(flat_registry)
                
                # Map node ID to its absolute index within this section
                if "id" in node:
                    global_id_map[node["id"]] = current_index

                # 🧹 Extract and remove 'steps' from the node so it doesn't stay nested
                steps = node.pop("steps", None)

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
                    self._compile_nodes(steps, flat_registry, global_id_map)
                    # Overwrite skip_index to point past the entire nested block
                    flat_node["skip_index"] = len(flat_registry)

        return flat_registry, global_id_map
        