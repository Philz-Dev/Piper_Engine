import os
from pathlib import Path
from .validators_V2 import main_validator, get_project_root
import yaml
import json
from .tools import retrieve_file
from .processor import processor
from .tools import get_registry_package

from .interpreter import PiperInterpreter
from .encryption_manager import verify_password, get_encryption_key
from .database_manager import ContextDB
from .redis_queuer import remove_from_redis_queue
from .universal_dispatcher_v2 import core
import click
from .redis_queuer import handover_password
from shared.compiler import WorkflowCompiler
from shared.tools import load_yaml_with_metadata

DB = ContextDB()

def is_docker():
    return os.path.exists('/.dockerenv')

async def execute_piper_start(clients=None, dsl=None, password=None, logger=print):
    """
    Core execution logic shared by CLI and FastAPI.
    """
    if not verify_password(password):
        click.secho("❌ Error: Incorrect Master Password. Access Denied.", fg="red")
        return False, "Invalid Master Password"
    
    handover_password(password=password)
    # Initialize encryption
    fernet = get_encryption_key(password)
    
    # Logic for deployment
    if not clients:
        logger("🚀 Initiating Piper: All client files")
        await init_build(crypto_engine=fernet, password=password)
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
    # Path discovery now delegates to get_project_root() (shared with
    # validators_V2.resolve_dsl_import_path) so this and DSL 'from:'/'use:'
    # resolution always agree on where 'root' is, regardless of CWD.
    f_path = os.path.join(get_project_root(), "templates")

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

async def builder(name, path, crypto_engine, password, dsl_file=None):
    """Now accepts dsl_file and defaults to waterfall.yml if none provided."""

    target_file = dsl_file if dsl_file else "waterfall.yml"
    # Guard against a bare name like "waterfall" (e.g. from `-d waterfall`) so the
    # resolved path matches what import_validator computes for imported files
    # (which always appends ".yml").
    if not target_file.endswith(".yml"):
        target_file += ".yml"
    formatted_path = os.path.abspath(os.path.join(path, target_file))
    
    yml_file = load_yaml_with_metadata(file_path=formatted_path)
    
    if yml_file is None:
        print(f"❌ Error: The DSL file '{target_file}' was not found for client '{name}' at '{formatted_path}'.")
        print(f"💥 ERROR: {target_file} is empty or could not be parsed for {name}")
        return

    registry, state = get_registry_package(yml_file)
    print(f"🛠️  Building {name} -> {target_file}")
    
    main_validator(dsl_file=yml_file, name=name, registry=registry, state=state, current_file_path=formatted_path)

    if state.info:
        for i in state.info:
            print(i)
    if state.warnings:
        for w in state.warnings:
            print(w)
    if state.errors:
        for e in state.errors:
            print(e)
        # Don't interpret a DSL that failed validation: state.import_map
        # (built by import_validator) is what use_interpreter now relies
        # on to resolve 'use:' references, and an import/self-import/
        # circular error here means that map is incomplete or wrong for
        # at least one alias.
        return

    # state carries the already-validated import_map (alias -> file_path)
    # down into interpretation, so use_interpreter never has to wait for
    # import_interpreter to run first - see interpreter.build_manifest.
    piper_interpreter = await PiperInterpreter.create(
                            registry=registry, 
                            dsl_file=yml_file, 
                            name=name, 
                            crypto_engine=crypto_engine,
                            state=state,
                            current_file_path=formatted_path,
                        )

    compiler = WorkflowCompiler()
    compiled_manifest = compiler.compile_block(piper_interpreter.manifest, registry=registry, state=state)

    await processor(_cont=compiled_manifest, _password=password, _client_name=name, _registry=registry, _dsl_file_name=dsl_file)

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

async def execute_piper_stop_v2(client_id, task_id, password):
    # 1. Setup crypto
    # Verifies the engine state using your master salt logic
    if not verify_password(password):
        return False, "Invalid Master Password"
    
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
            return True, f"Successfully stopped and cleaned up {client_id}."
    except Exception as e:
        print(f"❌ Critical error during DB cleanup: {e}")
        return False, f"Cleanup Error: {str(e)}"

    #return {"status": "stopped", "task_id": task_id}

async def execute_piper_stop(clients=None, dsl=None, password=None):
    """
    Handles the logic for stopping clients. 
    If no clients are provided, it attempts to stop everything active.
    """
    """if not verify_password(password):
        click.secho("❌ Error: Incorrect Master Password. Access Denied.", fg="red")
        return False, "Invalid Master Password"""
    
    # Case 1: No clients specified -> Stop everything in the DB/Queue
    if not clients:
        print("🛑 Shutting down all active pipelines...")
        # Get all active client/task pairs from your DB
        active_pipelines = DB.get_all_active_pipelines() # Ensure this exists in ContextDB
        if not active_pipelines:
            return True, "No active pipelines to stop."
        
        for pipe in active_pipelines:
            await perform_cleanup(pipe['client_id'], pipe['task_id'], password)
        return True, "Entire fleet shutdown complete."

    # Case 2: Specific clients specified
    for client in clients:
        # If specific DSLs/TaskIDs are provided
        if dsl:
            for d in dsl:
                # Remove .yml extension if user typed it, to match Task ID
                task_id = d.replace(".yml", "")
                await perform_cleanup(client, task_id, password)
        else:
            # No DSL specified? Find all tasks for this client in DB and stop them
            tasks = DB.get_tasks_by_client(client) 
            for t_id in tasks:
                await perform_cleanup(client, t_id, password)
                
    return True, "Stop sequence executed for requested targets."

async def perform_cleanup(client_id, task_id, password):
    """Internal helper to do the actual heavy lifting for one task."""
    crypto_engine = get_encryption_key(password)
    cleanup_data = DB.get_cleanup_schema(client_id, task_id)
    
    if cleanup_data:
        response = await core.dispatcher(
            **cleanup_data.get("args"), 
            _crypto_engine=crypto_engine, 
            _client_name=client_id, 
            _task_id=task_id,
            _app_name=cleanup_data.get("app_name")
        )
        if response.get("status") == "error":
             print(f"⚠️ External cleanup failed for {task_id}")
    
    remove_from_redis_queue(task_id)
    DB.remove_pipeline_data(client_id, task_id)
    print(f"✅ Cleaned up: {client_id} (Task: {task_id})")