from pathlib import Path
from dev_utils.interpreter_v2 import Interpreter
import yaml
import json
from dev_utils.task_managers import retrieve_file
from dev_utils.task_executor import func

inter = Interpreter()
async def init_build(crypto_engine, password, file_name=None):
    f_path = r"templates"
    directory_path = Path(f_path) # or a specific path like Path("C:/Users/Name/Desktop")
    if file_name:
        single_path = f"{f_path}\{file_name}"
        await builder(name=file_name, path=single_path, crypto_engine=crypto_engine, password=password)
    else:
        file_names = [p.name for p in directory_path.iterdir() if not p.is_file()]
        for f in file_names:
            yml_path = f"{f_path}\{f}"
            await builder(name=f, path=yml_path, crypto_engine=crypto_engine, password=password)

async def test_build(crypto_engine, file_path, name, task):
    print(f"testing {name} startup")
    yml_file = retrieve_file(file_path=file_path)
    if not yml_file.get("Pipeline"):
        print(f"the pipeline is empty")
        return
    for n in yml_file["Pipeline"]:
        if not n.get("id"):
            continue
        if e := n["id"] == task:
            yml_file["Pipeline"] = [n]
            interpreted_file = await inter.run_interpreter(file=yml_file, name=name, crypto_engine=crypto_engine)
            await func(_cont=interpreted_file)
            break
    if not e:
        print(f"no such task name {task} in {name} to test")


async def builder(name, path, crypto_engine, password):
    formatted_path = f"{path}\waterfall.yml"
    print(f"building {name} startup")
    yml_file = retrieve_file(file_path=formatted_path)
    interpreted_file = await inter.run_interpreter(file=yml_file, name=name, crypto_engine=crypto_engine)
    await func(_cont=interpreted_file, password=password)



        
    
    



    

    """piper = self.task_manifest["_sys_manifest"]
        if trigg := piper.get("trigger"):
            trigger_exe(_cont = piper)
        #exe.run_executor(manifest=self.task_manifest["_sys_manifest"])"""