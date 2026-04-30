import subprocess
import json
from typing import Dict

P_LANGUAGE_IMAGES = {
    "python": "piper-runner-python:v1",
    "nodejs": "piper-runner-node:v1",
}


async def execute_in_sandbox(_file_path, _context_data: Dict, runtime: str, timeout: int=30, **_kwargs):
    selected_image = P_LANGUAGE_IMAGES.get(runtime)
    # Save code to a temp file
    """with open("user_code.py", "w") as f:
        f.write(user_code_str)"""

    # Run Docker (Simplified example)
    #cmd = ["docker", "run", "--rm", "-i", "-v", f"{tmp_path}:/app/user_code", selected_image]
    
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network", "bridge", 
        "-v", "$(pwd)/user_code.py:/app/user_code.py",
        selected_image
    ]
    
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    stdout, _ = process.communicate(input=json.dumps(_context_data))

    # Extract the JSON between PIPER_RESULT markers
    # This prevents the Context Manager from being corrupted by random prints
    if "PIPER_RESULT_START" in stdout:
        result_json = stdout.split("PIPER_RESULT_START")[1].split("PIPER_RESULT_END")[0]
        return json.loads(result_json.strip())
    
    return {"raw": stdout}