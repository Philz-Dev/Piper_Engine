import os
from pathlib import Path
from shared.validators_V2 import main_validator
import yaml
import json
from shared.tools import retrieve_file
from shared.executor import trigger_exe
import click
from shared.tools import get_registry_package
from ruamel.yaml import YAML
from shared.interpreter import PiperInterpreter

def is_docker():
    return os.path.exists('/.dockerenv')

async def init_build(crypto_engine, password, file_name=None, dsl_file=None):
    # ... (Path discovery logic stays the same) ...
    workspace_templates = "/app/workspace/templates"
    internal_templates = "/app/templates"
    local_templates = "./templates"

    if os.path.exists(workspace_templates): f_path = workspace_templates
    elif os.path.exists(internal_templates): f_path = internal_templates
    else: f_path = local_templates

    directory_path = Path(f_path)
    
    # CASE 1: Running for specific client(s)
    if file_name:
        client_waterfall_path = Path(f_path) / file_name / "waterfall"
        
        if not client_waterfall_path.exists():
            print(f"⚠️  Skipping {file_name}: No 'waterfall' folder found.")
            return

        # If user specified a file (-d setup.yml), run ONLY that
        if dsl_file:
            await builder(name=file_name, path=client_waterfall_path, 
                          crypto_engine=crypto_engine, password=password, dsl_file=dsl_file)
        else:
            # If no -d, loop through EVERY .yml in that client's waterfall folder
            print(f"🔄 Running all DSLs for {file_name}...")
            for yml in client_waterfall_path.glob("*.yml"):
                await builder(name=file_name, path=client_waterfall_path, 
                              crypto_engine=crypto_engine, password=password, dsl_file=yml.name)

    # CASE 2: Global Mode (piper start) - Run for ALL clients
    else:
        client_dirs = [p for p in directory_path.iterdir() if p.is_dir()]
        for client_path in client_dirs:
            # Recurse back into init_build for each client to keep logic consistent
            await init_build(crypto_engine, password, file_name=client_path.name)

def load_yaml_with_metadata(file_path):
    yaml = YAML(typ='rt')
    with open(file_path, 'r') as f:
        return yaml.load(f)
        # ruamel objects have a .lc attribute (line/column info)

async def builder(name, path, crypto_engine, password, dsl_file=None):
    """Now accepts dsl_file and defaults to waterfall.yml if none provided."""
    target_file = dsl_file if dsl_file else "waterfall.yml"
    formatted_path = os.path.join(path, target_file)
    
    print(f"🛠️  Building {name} -> {target_file}")
    yml_file = load_yaml_with_metadata(file_path=formatted_path)
    
    if yml_file is None:
        print(f"💥 ERROR: {target_file} not found for {name}")
        return
    registry_package = get_registry_package(yml_file)
    registry = registry_package[0]
    state = registry_package[1]
    main_validator(dsl_file=yml_file, name=name, registry=registry, state=state)
    piper_interpreter = await PiperInterpreter.create(
                            registry=registry, 
                            dsl_file=yml_file, 
                            name=name, 
                            crypto_engine=crypto_engine
                        )

    
    """try:
        validator.run_validator(dsl_file=yml_file, name=name)
        #interpreted_file = Interpreter()
        # await trigger_exe(_cont=yml_file, password=password)
    except Exception as e:
        print(f"❌ Execution failed for {name} ({target_file}): {e}")"""

async def test_build(crypto_engine, file_path, name, task):
    """Directly tests a single task within a pipeline."""
    print(f"testing {name} startup")
    yml_file = retrieve_file(file_path=file_path)
    
    if not yml_file or not yml_file.get("Pipeline"):
        print(f"the pipeline is empty or missing 'Pipeline' key")
        return
        
    found_task = False
    for n in yml_file["Pipeline"]:
        if n.get("id") == task:
            found_task = True
            yml_file["Pipeline"] = [n]
            #interpreted_file = await inter.run_interpreter(file=yml_file, name=name, crypto_engine=crypto_engine)
            #await trigger_exe(_cont=interpreted_file)
            break
            
    if not found_task:
        print(f"no such task name {task} in {name} to test")