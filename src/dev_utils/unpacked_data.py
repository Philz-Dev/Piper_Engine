class UnZip:
    def __init__(self):
        self.unpacked_key_value = {}
        self.key_path = {} # This will hold the "Final" full paths
        self.unpacked_data = []

    def unpack_bulk_data(self, content, key=None, value=None, hooks=None):
        # Start recursion with an empty string for the path
        self.unzip_content(content=content, current_path="", key=key, value=value, hooks=hooks)

    def unzip_content(self, content, current_path, key=None, value=None, hooks=None):
        if hooks:
            hook_func = hooks.get(type(content))
        else:
            hook_func = None

        if isinstance(content, dict):
            self.unzip_dict(package=content, current_path=current_path, key=key, hook=hooks, func=hook_func)
        elif isinstance(content, list):
            self.unzip_list(package=content, current_path=current_path, key=key, hook=hooks, func=hook_func)
        else:
            self.provision_leaf(content=content, current_path=current_path, key=key, hook=hooks)

    def unzip_dict(self, package: dict, current_path, hook=None, func=None, key=None):
        if func and key:
            func(content=package, value={key: package}, key=key)
        for k, v in package.items():
            # Build the new path segment
            new_path = f"{current_path}.{k}" if current_path else k
            self.unzip_content(content=v, current_path=new_path, key=k, hooks=hook)

    def unzip_list(self, package: list, key, current_path, func=None, hook=None):
        value = {}
        for index, item in enumerate(package):
            value[key] = item
            # For lists, we add the index to the path to keep it unique
            new_path = f"{current_path if current_path else key}.{index}"
            self.unzip_content(content=item, current_path=new_path, key=None, hooks=hook)
            if func:
                func(value=value, key=key, content=package)
    
    def provision_leaf(self, content, key, hook, current_path):
        allowed_primitives = (str, int, float, bool)
        if isinstance(content, allowed_primitives):
            self.unpacked_data.append(content)
            # WE ONLY SAVE HERE: This ensures we only get the full completed path
            self.key_path[current_path if current_path else key] = content
            self.unpacked_key_value[key] = content
        elif content is None:
            self.key_path[current_path] = "Null"
        else:
            raise TypeError(f"Unpacker reached a leaf but doesn't recognize type: {type(content)}")
        if hook and "primitive" in hook:
            hook["primitive"](content=content, key=key, value={key: content})