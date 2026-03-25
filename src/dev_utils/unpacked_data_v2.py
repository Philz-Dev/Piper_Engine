from functools import partial

class UnZip:
    def __init__(self):
        # ... your existing init ...
        self.unpacked_key_value = {}
        self.key_path = {}
        self.unpacked_data = []
        self.unpacked_data_list = []


    def unpack_bulk_data(self, content, key=None, value=None, hooks=None, key_path=None): 
        """
        hooks: A dict mapping types to functions.
        Example: {dict: my_func, list: other_func, 'primitive': leaf_func}
        """
        # 1. TRIGGER HOOKS: If a function exists for this type, run it now.
        if hooks:
            hook_func = hooks.get(type(content))
        else:
            hook_func = None

        # 3. ROUTE RECURSION (Pass the hooks down the line)
        if isinstance(content, dict):
            self.unzip_dict(package=content, key=key, hooks=hooks, func=hook_func, key_path=key_path)
        elif isinstance(content, list):
            self.unzip_list(package=content, key=key, hooks=hooks, func=hook_func)
        else:
            self.provision_leaf(content=content, key=key, hooks=hooks)

    # Update these to pass hooks through!
    def unzip_dict(self, package: dict, key, hooks=None, func=None, key_path=None):
        if func and key:
            func(content=package, value={key: package}, key=key)
        if not key_path:
            key_path = key
        else:
            key_path += "." + key
        
        for k, v in package.items():
            if key_path:
                self.key_path[key_path + "." + k] = v
            self.unpack_bulk_data(content=v, key=k, hooks=hooks, key_path=key_path)

    def unzip_list(self, package: list, key, hooks=None, func=None, key_path= None):
        value = {}
        for item in package:
            value[key] = item
            self.unpack_bulk_data(content=item, key=None, hooks=hooks)
        if func:
            func(value=value, key=key, content=package)
    
    def provision_leaf(self, content, key, hooks=None):
        """Final collection point for non-iterable data."""
        # Removed 'list' from allowed_type so that lists are always forced to unzip

        allowed_primitives = (str, int, float, bool)
        if isinstance(content, allowed_primitives):
            self.unpacked_data.append(content)
            self.unpacked_key_value[key] = content
            print(self.unpacked_key_value)

        elif content is None:
            pass # Or handle nulls as needed
        else:
            raise TypeError(f"Unpacker reached a leaf but doesn't recognize type: {type(content)}")
        if hooks and "primitive" in hooks:
            hooks["primitive"](content=content, key=key, value={key: content})
