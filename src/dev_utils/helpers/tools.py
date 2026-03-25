import json
import yaml
import os

def open_json_file(file_path, cont):
    with open(file_path, "w") as f:
        json.dump(cont, f, indent=4)

def retrieve_file(file_path, file_type: str=None, base_dir=False):
    file_type = file_path.split(".")[-1]
    services = {"yml": yaml.safe_load, "json": json.load}
    if base_dir:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(BASE_DIR, file_path)
    try:
        with open(file_path, "r") as f:
            file = services[file_type](f) if file_type and file_type in services else f.read()
            return file
    except FileNotFoundError:
        return None
