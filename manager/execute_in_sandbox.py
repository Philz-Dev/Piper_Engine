import asyncio
import json
import os
import tempfile
import shutil

LANGUAGE_REGISTRY = {
    "python": {"image": "piper-runner-python:v1", "ext": ".py", "cmd": "python3"},
    "javascript": {"image": "piper-runner-js:v1", "ext": ".js", "cmd": "node"},
    "php": {"image": "piper-runner-php:v1", "ext": ".php", "cmd": "php"},
    "golang": {"image": "piper-runner-go:v1", "ext": ".go", "cmd": "/app/bootstrap"},
    "bash": {"image": "piper-runner-bash:v1", "ext": ".sh", "cmd": "bash"}
    }

async def execute_in_sandbox(user_code_str, context_data, language="python"):
    """
    Production-level Orchestrator:
    - Creates a unique, isolated workspace for the execution.
    - Handles asynchronous process execution.
    - Surgically extracts results from the stdout stream.
    """
    # Inside your Engine's configuration
    
    # 1. Setup unique workspace to prevent race conditions
    tmp_dir = tempfile.mkdtemp(prefix="piper_run_")
    filename = "user_code.py"
    host_path = os.path.join(tmp_dir, filename)
    container_path = f"/app/{filename}"

    try:
        # 2. Write the user's logic to the temporary file
        with open(host_path, "w") as f:
            f.write(user_code_str)

        # 3. Construct the Docker Command
        # We use --network bridge for internet access as requested
        # We limit memory and CPU to prevent a single script from killing the server
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "bridge",
            "--memory", "128m",
            "--cpus", "0.5",
            "-v", f"{host_path}:{container_path}",
            "piper-runner-image",
            "python3", "runner.py", filename
        ]

        # 4. Execute the Process Asynchronously
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 5. Send Context Data and wait for result (with a 30s safety timeout)
        input_payload = json.dumps(context_data).encode()
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=input_payload), 
                timeout=30.0
            )
        except asyncio.TimeoutError:
            process.kill()
            return {"error": "Execution Timed Out", "logs": "Process killed after 30 seconds."}

        # 6. Parse Output
        output_str = stdout.decode()
        error_str = stderr.decode()

        # Surgical Extraction Logic
        if "PIPER_RESULT_START" in output_str:
            try:
                # Split and grab the content between markers
                parts = output_str.split("PIPER_RESULT_START")
                result_part = parts[1].split("PIPER_RESULT_END")[0]
                return json.loads(result_part.strip())
            except (IndexError, json.JSONDecodeError):
                return {
                    "error": "Failed to parse result markers",
                    "raw_output": output_str,
                    "stderr": error_str
                }
        
        # Fallback if markers aren't found (likely a crash)
        return {
            "error": "No result returned from script",
            "stdout": output_str,
            "stderr": error_str
        }

    finally:
        # 7. Cleanup the temporary directory from the host
        shutil.rmtree(tmp_dir, ignore_errors=True)