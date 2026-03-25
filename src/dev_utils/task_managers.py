import json
import os
from dev_utils.unpacked_data import UnZip
from functools import partial
import re
import inspect
import os
from dotenv import load_dotenv
import dev_utils.universal_webhook as webhoock_app
import importlib
import yaml
from dev_utils.auth_manger import start_auth_flow

IMPORT_LIST = ["SK-SECRET-12345"]

async def metadata_tk(regs):
    pass

async def sentinel_tk(regs):
    pass

async def add_version(regs):
    pass

def get_auth_config_file(client_name, file_type: str="auth"):
    services = {
        "auth": f".\\templates\{client_name}\\auth_config.json",
        "env": f".\\templates\{client_name}\.env",
        ".piper_vault": f".\\templates\{client_name}\.piper_vault"
        }
    return services[file_type]

async def import_tk(regs):
    services = {"vault": run_vault}
    client_name = regs["client_name"]
    auth_path = get_auth_config_file(client_name=client_name, file_type="auth")
    cont = regs["content"]
    list_of_import = []
    for c in cont:
        split_key = c.split(".") if "." in c else None
        if not (k := split_key[0] if split_key else None) in services:
            raise ImportError(f"module not exist {c}")
        key = services[k](content=split_key, client_name=regs["client_name"])
        list_of_import.append(key)
    try:
        loaded_file = retrieve_file(file_path=auth_path)
        loaded_file["import"] = list_of_import
        open_json_file(file_path=auth_path, cont=loaded_file)
    except FileNotFoundError:
        loaded_file = {}
        loaded_file["import"] = list_of_import
        open_json_file(file_path=auth_path, cont=loaded_file)

def run_vault(content: list, client_name: str):
    secret_key = content[1]
    env_path = get_auth_config_file(client_name=client_name, file_type=".piper_vault")
    r = retrieve_file(file_path=env_path)
    if r and secret_key in r:
        return secret_key
    raise ModuleNotFoundError(f"Error no such secret key {secret_key}")

async def run_pipeline(regs, manifest=[], id_name_list=[], exe_manifest={}):

    for n in range(0, len(content := (regs["content"]))):
        c = content[n]
        if not type(c) is dict:
            raise TypeError("wrong command")
        if id_key := next((k for k in set(c.keys()) if k in (id_map := regs["id_map"]) and k in (allow_key := regs["allow_key"])), None):
            id_name_list = regs["tk_map"][id_key](regs=regs, cont=c, id_name_list=id_name_list)
        if not id_key:
            raise ValueError(f"id manager is required, include one")
        manifest.append({})
        for k, v in c.items():
            if not k in allow_key[regs["key"]]:
                raise SyntaxError(f"this key {k} is not required in this block")
            if k in (trig_map := regs["trig_map"]):
                exe_manifest["trigger"] = {}
                exe_manifest["trigger"][id_key] = id_name_list[-1]
                exe_manifest["trigger"]["service_manager"] = k
                exe_manifest["trigger"]["args"] = await regs["tk_map"][k](regs=regs, cont=c, key=k)
                exe_manifest["trigger"]["_type"] = v.split(".")[1]
                continue
            elif k in regs["service_reg"]:
                manifest[n][id_key] = id_name_list[-1]
                manifest[n]["args"] = {}
                manifest[n]["args"] = verify_config(regs=regs, content=c, key=k, manifest=manifest[n]["args"])
                manifest[n]["service_manager"] = k
                manifest[n] = await regs["tk_map"][k](regs=regs, manifest=manifest[n], cont=c, key=k)
            elif k in regs["con_map"]:
                manifest[n]["condition"] = v
            elif k in regs["rec_map"]:
                pass
                manifest[n]["steps"] = []
                regs["content"]= c[k]
                await run_pipeline(
                    regs=regs, manifest=manifest[n][k], id_name_list=id_name_list,
                    exe_manifest=exe_manifest
                    )
    exe_manifest["Pipeline"] = manifest
    exe_manifest["crypto_engine"] = regs["crypto_engine"]
    return exe_manifest

def verify_config(regs, content, key, manifest=None):
    func=regs["handlers"][key]
    not_defualt_args = []
    inspect = inspect_function(func=func)
    for ky, vl in inspect.items():
        if not vl["default"]:
            not_defualt_args.append(ky)
    config_keys = {}
    for k, v in content.items():
        if k in regs["reg"]:
            continue
        if not k in inspect:
            raise SyntaxError(f"wrong syntax, this block does not required this syntax {k}")
        expected_type = inspect[k]["annotation"]
        validate_type(content=v, key=k, expected_type=expected_type)
        manifest[k] = v
        config_keys[k] = v

    missing_arg = missing_field(required=not_defualt_args, content_to_check=config_keys)
    if missing_arg:
        raise SyntaxError(f"missing this syntax {missing_arg}")
    return manifest
    

def naming(regs, cont, id_name_list):
    for k, v in cont.items():
        if k in regs["id_map"]:
            if id_name_list and v in id_name_list:
                    raise ValueError(f"the id {v} already exist")
            if k not in regs["d_map"][regs["key"]]:
                raise SyntaxError(f"this {k} is not supported by this block")
            id_name_list.append(v)
    return id_name_list

def all_config_keys(func_list:list, handler):
    all_config_list = {}
    for f in func_list:
        confg_list = inspect_function(func=handler[f])
        for k, v in confg_list.items():
            all_config_list[k] = v
    return all_config_list

def inspect_function(func):
    details = {}
    sig = inspect.signature(func)
    for name, param in sig.parameters.items():
        if name.startswith("_"):
            continue
        details[name] = {"default": param.default if not type(param.default) is type else None,
                         "annotation": param.annotation
                         }
    return details

async def app_service(regs, cont, key=None, manifest=None):
    app_service_value = cont[key]
    app_name, action = app_service_value.split(".")
    manifest["app_name"] = app_name
    if (p := regs["ad_map"][key]):
        if (e := regs["fl_map"][key]):
            path = p + "/" + app_name + "/" + action + "." + e
    app_schema = await core_service_func(regs=regs, crypto_engine=regs["crypto_engine"], cont=cont, key=key, path=path, service=app_name, action=action)
    manifest["args"]["_args"] = app_schema
    return manifest
    
async def build_with(service, crypto_engine, client_name, cont, content_to_modify, unzip_key_app, found_items, key, action):
    map = cont.get(key)
    if found_items and not map:
        raise SyntaxError(f"{key} block required and its required keys: {found_items.keys()}")
    elif map and not found_items:
        raise SyntaxError(f"{key} block not required")
    missing = missing_field(required=found_items, content_to_check=map)
    verify_missing_list = []
    if missing:
        for m in missing:
            missisng_value = found_items.get(m)
            if not type(missisng_value) is int and missisng_value.startswith("{{$.") and missisng_value.endswith("}}"):
                app_path = f"apps\{service}\_auth_config.json"
                w_f = retrieve_file(file_path=app_path, base_dir=True)
                if w_f:
                    w_f["client_name"] = client_name
                    w_f["app_name"] = service
                    await start_auth_flow(_cont=w_f, _crypto_engine=crypto_engine)
                    continue
            verify_missing_list.append(m)
    if verify_missing_list:
        raise SyntaxError(f"this field {verify_missing_list} is required")
    
    if not map and not found_items:
        return content_to_modify if content_to_modify else None

    for key, value in map.items():
        if not key in found_items:
            raise ValueError(f"this filed {key} is not required")
        content_to_modify = replace_place_value(
            key_path=unzip_key_app, content_to_modify=content_to_modify, key=key, value=value
            )
            
    return content_to_modify
    

def replace_place_value(key_path, key, value, content_to_modify=None):
    for k, v in key_path.items():
        split_key = k.split(".")
        
        if split_key[-1] == key:
            temp = content_to_modify
            for ky in split_key[:-1]:
                if ky.isdigit():
                    ky = int(ky)
                temp = temp[ky]
            
            # Update the final key
            temp[split_key[-1]] = value
    return content_to_modify

def crawler(content_to_crawl: dict, patterns: list | str, is_regex: bool = True):
    matched_field = {}
    unzip_app_schema = UnZip()
    unzip_app_schema.unpack_bulk_data(content_to_crawl)
    if isinstance(patterns, str):
        patterns = [patterns]
    for p in patterns:
        # If we want a literal search, escape special characters
        # e.g., "price?" becomes "price\?" so regex treats it as text
        search_pattern = p if is_regex else re.escape(p)
        for key, value in unzip_app_schema.unpacked_key_value.items():
            if re.fullmatch(search_pattern, str(value)):
                matched_field[key] = value
    package = {
        "matched_items": matched_field,
        "key_path": unzip_app_schema.key_path
    }
    
    return package if matched_field else None

def missing_field(required: list|dict, content_to_check: list|dict):
    content = required.keys() if type(required) is dict else required
    cont_to_check = content_to_check.keys() if type(content_to_check) is dict else content_to_check
    return set(content) - set(cont_to_check)

def validate_type(key, expected_type, content=None):
    if not isinstance(content, expected_type):
        raise TypeError(
            f"DATA TYPE MISMATCH: {key} expects {expected_type.__name__}, "
            f"but got {type(content).__name__}."
        )

async def trigger(regs, cont, key=None):
    services = {"webhook": webhook_func, "timer": timer_func}
    raw_cont = cont[key]
    if not "." in raw_cont:
        raise SyntaxError(f"unknown request peharps you forgot a namespace dot {raw_cont}")
    service, action = raw_cont.split(".")
    if (p := regs["ad_map"][key]):
        if (e := regs["fl_map"][key]):
            path = p + "/" + service + "/" + action + "." + e
    if service_func := services.get(action):
        response = await service_func(cont=cont, regs=regs, key=key, path=path, service=service, action=action)
        response["app_name"] = service
    else:
        raise (f"this trigger services is not recognise, this are the list of supported trigger service(s) {set(services.keys())}")
    return response

def open_json_file(file_path, cont):
    with open(file_path, "w") as f:
        json.dump(cont, f, indent=4)

def retrieve_file(file_path, file_type: str=None, base_dir=False):
    file_type = file_path.split(".")[-1]
    services = {"yml": yaml.safe_load, "json": json.load, "piper_vault": json.load, "context_manager": json.load}
    if base_dir:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(BASE_DIR, file_path)
    try:
        with open(file_path, "r") as f:
            file = services[file_type](f) if file_type and file_type in services else f.read()
            return file
    except FileNotFoundError:
        return None

def check_for_import(cont: dict, client_name: str):
    unzip_app_schema = UnZip()
    unzip_app_schema.unpack_bulk_data(cont)
    unzip_cont = unzip_app_schema.unpacked_key_value
    auth_config = get_auth_config_file(client_name=client_name, file_type="auth")
    for k, v in unzip_cont.items():
        if type(v) is int or not v.startswith("{{$.") or not v.endswith("}}"):
            continue
        l = retrieve_file(file_path=auth_config)
        try:
            imp = l["import"]
            if not (i := v.strip("{{$.}}")) in imp:
                raise TypeError(f"this module was not imported {i}")
        except KeyError:
            raise ImportError(f"the import block was not define, define the report block")

async def core_service_func(regs, crypto_engine, cont, path, service, action, key=None):
    client_name = regs["client_name"]
    secret_key_pattern = r"\{\{\$\.\s*(\w+)\s*\}\}"
    pattern = [r"\{\{\w+\}\}", secret_key_pattern]
    app_schema = retrieve_file(file_path=path, base_dir=True)
    if not app_schema:
        raise NameError(f"No such app or action to be taken {service}.{action}")
    found_items = crawler(content_to_crawl=app_schema, patterns=pattern)
    check_for_import(cont=cont, client_name=client_name)
    for d in regs["d_map"][key]:
        app_schema = await regs["tk_map"][d](
            cont=cont, found_items=found_items["matched_items"], 
            unzip_key_app=found_items["key_path"], key=d, content_to_modify=app_schema, 
            service=service, action=action, client_name=client_name, crypto_engine=crypto_engine
            )
    app_schema["client_name"] = client_name
    #add_to_config(service=service, cont=app_schema, client_name=client_name)
    return app_schema

def check_for_secret_keys():
    pass

def add_to_config(cont, service, client_name):
    auth_file_path = get_auth_config_file(client_name=client_name, file_type="auth")
    auth_file = retrieve_file(file_path=auth_file_path)
    if not auth_file.get("app_service"):
        auth_file["app_services"]  = []
    auth_file["app_services"].append(service) if service else None
    unzip = UnZip()
    unzip.unpack_bulk_data(cont)
    unzip.unpacked_key_value
    for key, v in unzip.unpacked_key_value.items():
        if type(v) is int or not v.startswith("{{$.") or not v.endswith("}}") or auth_file.get(service):
            continue
        auth_file[service] = v
        open_json_file(file_path=auth_file_path, cont=auth_file)

async def webhook_func(regs, service, action, cont, path, key=None):
    return await core_service_func(regs=regs, crypto_engine=regs["crypto_engine"], cont=cont, path=path, key=key, action=action, service=service)

async def timer_func():
    pass
