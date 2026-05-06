import os
from pathlib import Path
from shared.validators_V2 import main_validator
import yaml
import json
from shared.tools import retrieve_file
from shared.processor import processor
from shared.tools import get_registry_package
from ruamel.yaml import YAML
from shared.interpreter import PiperInterpreter
from shared.encryption_manager import verify_password, get_encryption_key
from shared.database_manager import ContextDB
from shared.redis_queuer import remove_from_redis_queue
from shared.universal_dispatcher_v2 import core

DB = ContextDB()

def is_docker():
    return os.path.exists('/.dockerenv')

async def execute_piper_start(clients=None, dsl=None, password=None, logger=print):
    """
    Core execution logic shared by CLI and FastAPI.
    """
    if not verify_password(password):
        return False, "Incorrect Master Password. Access Denied."

    # Initialize encryption
    fernet = get_encryption_key(password)
    
    # Logic for deployment
    if not clients:
        logger("🚀 Initiating Piper: All client files")
        # await init_build(crypto_engine=fernet, password=password)
        return True, "All clients initiated"

    for client in clients:
        if dsl:
            for d in dsl:
                logger(f"Processing {client} with DSL: {d}...")
                await init_build(file_name=client, dsl_file=d, crypto_engine=fernet, password=password)
        else:
            logger(f"Processing all DSLs for client: {client}...")
            await init_build(file_name=client, crypto_engine=fernet, password=password)
            
    return True, "Execution successful"

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
    yml_file = load_yaml_with_metadata(file_path=formatted_path)
    registry_package = get_registry_package(yml_file)
    registry = registry_package[0]
    state = registry_package[1]
    
    print(f"🛠️  Building {name} -> {target_file}")
    
    if yml_file is None:
        state.add_error(f"💥 ERROR: {target_file} not found for {name}")
        return
    
    main_validator(dsl_file=yml_file, name=name, registry=registry, state=state)
    piper_interpreter = await PiperInterpreter.create(
                            registry=registry, 
                            dsl_file=yml_file, 
                            name=name, 
                            crypto_engine=crypto_engine
                        )
    print(piper_interpreter.manifest)
    
    if state.info:
        for i in state.info:
            print(i)
    if state.Warning:
        for w in state.Warning:
            print(w)
    if state.errors:
        for e in state.errors:
            print(e)
        return
    await processor(_cont=piper_interpreter.manifest, _password=password, _client_name=name, _registry=registry)

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

async def execute_piper_stop(client_id, task_id, password):
    # 1. Setup crypto
    # Verifies the engine state using your master salt logic
    crypto_engine = get_encryption_key(password)
    
    # 2. Get the cleanup schema from the database
    # This retrieves the dynamic 'delete.json' captured during interpretation
    # Note: Ensure DB.get_cleanup_schema is implemented in your ContextDB class
    cleanup_data = DB.get_cleanup_schema(client_id, task_id)
    
    if cleanup_data:
        print(f"🛑 Dynamic Deactivation: Dispatching delete request for {task_id}")
        # Hand the dynamic schema over to the dispatcher to notify external providers
        await core.dispatcher(
            **cleanup_data.get("args"), 
            _crypto_engine=crypto_engine, 
            _client_name=client_id, 
            _task_id=task_id,
            _app_name=cleanup_data.get("app_name")
        )
    
    # 3. Stop Local Redis Processes
    # We use your specific 'remove_from_redis_queue' function.
    # Note: Since your function uses 'run_id', ensure task_id is mapped correctly if they differ.
    try:
        # Removing from the task_queue list
        redis_status = remove_from_redis_queue(task_id)
        
        # Additionally, if you use a set for active tracking (as mentioned in step 3 comments)
        # r.srem(f"active_tasks:{client_id}", task_id) 
        
        print(f"🗑️ Redis cleanup result: {redis_status.get('status')}")
    except Exception as e:
        print(f"⚠️ Redis cleanup warning: {e}")

    try:
        db_purge_success = DB.remove_pipeline_data(client_id, task_id)
        
        # Optional: if you separate cleanup_schema into its own table, add that purge here
        # DB.delete_cleanup_schema(client_id, task_id) 
        
        if db_purge_success:
            print(f"✅ Database record for {task_id} successfully removed.")
    except Exception as e:
        print(f"❌ Critical error during DB cleanup: {e}")

    return {"status": "stopped", "task_id": task_id}