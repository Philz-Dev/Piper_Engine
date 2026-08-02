import os
import yaml
import docker
from sqlalchemy import text
from shared.setup_build import execute_piper_start, execute_piper_stop
from shared.database_manager import ContextDB
# Import your helper functions (get_global_stats_sync, etc)
from shared.encryption_manager import verify_password, initialize_salt, MASTER_SALT, CONFIG_DIR
from fastapi import HTTPException
import logging

class PiperService:
    def __init__(self):
        self.db = ContextDB()
        self.client = self.init_docker()
        self.project_root = os.getenv("CONTAINER_ROOT", "/app")
        self.template_dir = os.path.join(self.project_root, "templates")
        self.eaterfall_dir = os.path.join(self.project_root, "waterfall")
        self.master_password = None
        self.logger = logging.getLogger("uvicorn.error")

    def init_docker(self):
        try:
            # Priority 1: Explicit DOCKER_HOST from environment
            if os.getenv("DOCKER_HOST"):
                client = docker.DockerClient(base_url=os.getenv("DOCKER_HOST"), timeout=10)
            else:
                # Priority 2: Auto-detect (Socket or default env)
                client = docker.from_env(timeout=10)
                
            client.ping()
            print(f"✅ Docker Connected via: {client.api.base_url}")
            return client
        except Exception as e:
            print(f"❌ Docker Init Failed: {e}")
            return None

    # Add this to the PiperService class in shared/engine_server_utils.py

    def get_system_state(self):
        """
        Retrieves all clients, their automations, and their associated 
        valid custom scripts found within the configurations.
        """
        system_state = []
        clients = self.list_clients()

        for i, client_name in enumerate(clients):
            client_data = {
                "id": i + 1,  # Added this field
                "name": client_name,
                "automations": [],
                "scripts": set()
            }
            
            # 1. Get Automations
            automations = self.get_automations(client_name)
            client_data["automations"] = automations

            # 2. Parse Automation Files for 'service: script.external_script.*'
            client_path = os.path.join(self.template_dir, client_name, "waterfall")
            
            if os.path.exists(client_path):
                for file in os.listdir(client_path):
                    if file.endswith(('.yml', '.yaml')):
                        file_path = os.path.join(client_path, file)
                        try:
                            with open(file_path, 'r') as f:
                                config = yaml.safe_load(f)
                                print(f"config:              {config}")
                                print(f"client_name:              {client_name}")
                                if config:
                                    # Find and verify scripts
                                    found_scripts = self._extract_and_verify_scripts(config, client_name)
                                    print(f"found scripts:              {found_scripts}")
                                    client_data["scripts"].update(found_scripts)
                        except yaml.YAMLError:
                            continue
            
            client_data["scripts"] = list(client_data["scripts"])
            system_state.append(client_data)
            
        return system_state

    def _extract_and_verify_scripts(self, data, client_name):
        """
        Recursively searches the config for 'service: script.external_script.<name>'
        and verifies if <name>.<ext> exists in the client's script directory.
        """
        found_scripts = set()

        def _traverse(obj):
            if isinstance(obj, dict):
                # Check for script identification: service: script.external_script.<name>
                service_val = obj.get('service', '')
                if isinstance(service_val, str) and service_val.startswith('script.'):
                    script_p = service_val.split('.', 1)[1]
                    script_name = script_p.replace('.', '/')
                    runtime = obj.get('runtime', 'python')
                    
                    # Map runtime to file extension
                    extension = 'js' if runtime == 'javascript' else 'py'
                    script_filename = f"{script_name}.{extension}"
                    script_path = os.path.join(self.project_root, script_filename)
                    print(f"script_path:              {script_path}")
                    
                    # Only add if file exists
                    if os.path.exists(script_path):
                        found_scripts.add(script_path)
                
                # Maintain original traversal for nested structures
                for v in obj.values():
                    _traverse(v)
            elif isinstance(obj, list):
                for item in obj:
                    _traverse(item)

        _traverse(data)
        return found_scripts

    def get_file_tree(self, path=None):
        """
        Recursively traverses the project file path and returns a 
        VS Code-like hierarchical tree structure.
        """
        target_path = path if path else self.project_root
        
        if not os.path.exists(target_path):
            return []

        def build_tree(current_path):
            tree = []
            try:
                # Sort entries: directories first, then files alphabetically
                entries = sorted(
                    os.listdir(current_path), 
                    key=lambda e: (not os.path.isdir(os.path.join(current_path, e)), e.lower())
                )
                for entry in entries:
                    # Skip hidden files/folders (e.g., .git, .DS_Store)
                    if entry.startswith('.'):
                        continue
                        
                    full_path = os.path.join(current_path, entry)
                    is_dir = os.path.isdir(full_path)
                    
                    node = {
                        "name": entry,
                        "path": full_path,
                        "type": "directory" if is_dir else "file"
                    }
                    
                    if is_dir:
                        node["children"] = build_tree(full_path)
                        
                    tree.append(node)
            except PermissionError:
                pass
            return tree

        return build_tree(target_path)

    def get_script_content(self, client_name, file_name, is_absolute=False):
        """
        Fetches the raw content of a YML or script file.
        :param is_absolute: If True, treats file_name as an absolute path in the container.
                            If False, uses the strict template/waterfall directory structure.
        """

        if not file_name:
            raise HTTPException(status_code=400, detail="file_name parameter is required")
        
        if is_absolute:
            # SECURITY: Ensure the absolute path resides within the project root
            # to prevent unauthorized access to system files (e.g., /etc/passwd)
            if not file_name.startswith(self.project_root):
                raise PermissionError("Access denied: Path is outside the authorized project directory.")
            
            file_path = file_name
            
        else:
            # Strict mode: existing logic for config files
            safe_client = os.path.basename(client_name)
            safe_file = os.path.basename(file_name)
            
            # Construct and validate the path using 'waterfall' to maintain consistency
            target_dir = os.path.join(self.template_dir, safe_client, "waterfall")
            file_path = os.path.join(target_dir, safe_file)
        
        # Verify the file existence
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Script not found at path: {file_path}")
            
        with open(file_path, 'r') as f:
            return f.read()

    def unlock(self, password):
        if not password:
            raise HTTPException(status_code=400, detail="Password required")
        if not os.path.exists(MASTER_SALT):
            if not os.path.exists(CONFIG_DIR):
                os.makedirs(CONFIG_DIR)
            initialize_salt(password)
            self.master_password = password
            return {"status": "created", "message": "Master password initialized"}

        # 2. Otherwise, VERIFY against the CLI manager logic
        if verify_password(password):
            self.master_password = password
            return {"status": "unlocked", "message": "Access granted"}
        else:
            # feedback for the UI to display "wrong or incorrect password"
            raise HTTPException(status_code=401, detail="Incorrect Master Password")

    def get_status(self):
        return {
            "locked": self.master_password is None,
            "exists": os.path.exists(MASTER_SALT)
        }

    def list_clients(self):
        print(f"DEBUG: Checking template_dir path -> {self.template_dir}")
        print(f"DEBUG: Does template_dir exist? -> {os.path.exists(self.template_dir)}")
        
        if not os.path.exists(self.template_dir): 
            print("DEBUG: template_dir path not found, returning empty.")
            return []
            
        clients = [d for d in os.listdir(self.template_dir) if os.path.isdir(os.path.join(self.template_dir, d))]
        print(f"DEBUG: Found clients: {clients}")
        return clients

    def get_automations(self, client_name):
        automations = []
        client_path = os.path.join(self.template_dir, client_name, "waterfall")
        
        if not os.path.exists(client_path):
            return []
        
        try:
            running_containers = {c.name: c.status for c in self.client.containers.list(all=True)}
        except:
            running_containers = {}

        # 1. Fetch all currently active tasks for this client from the DB
        try:
            query = text("SELECT dsl_name FROM pipeline_storage WHERE client_id = :c_id")
            with self.db.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_name}).fetchall()
                active_dsls = {row[0] for row in result if row[0]}
        except Exception as e:
            self.logger.error(f"DB Status Check Error: {e}")
            active_dsls = set()

        for file in os.listdir(client_path):
            if file.endswith(('.yml', '.yaml')):
                file_path = os.path.join(client_path, file)
                clean_name = os.path.splitext(file)[0]
                with open(file_path, 'r') as f:
                    try:
                        config = yaml.safe_load(f)
                        name = config.get('name', clean_name)
                        status = "running" if file in active_dsls else "stopped"
                        
                        automations.append({
                            "id": name,
                            "name": name,
                            "status": status,
                            "file_path": file_path,
                            "cpu": "0%",
                            "mem": "0B"
                        })
                    except yaml.YAMLError:
                        continue
        return automations

    async def toggle_container(self, client_name, container_name, action):
        try:
            if action == "start":
                success, message = await execute_piper_start(
                    clients=[client_name], 
                    dsl = [container_name if container_name.endswith(('.yml', '.yaml')) else f"{container_name}.yml"], 
                    password=self.master_password
                )
                
            else:
                pipeline_info = self.db.get_pipeline_by_client(client_name)
                
                active_task_id = pipeline_info.get("task_id") if pipeline_info else container_name
                
                print(f"DEBUG: Stopping client {client_name} with Task ID {active_task_id}")
                success, message = await execute_piper_stop(
                    clients=[client_name],           
                    dsl=[f"{active_task_id}.yml"],   
                    password=self.master_password
                )

            if not success:
                raise HTTPException(status_code=500, detail=message)
        
            return {"status": "success", "message": message}

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def delete_automation(self, client_name, container_name):
        # Move logic from @app.delete(...)
        pass

    def get_stats(self, client_name):
        # Aggregates your existing stats functions
        return {
            "total": self.get_global_stats_sync(),
            "grouped": self.get_grouped_client_stats_sync(client_name),
            "client_stat": self.get_total_client_stats_sync(client_name)
        }
    
    def get_global_stats_sync(self):
        try:
            if not self.client:
                return {"total_cpu": "OFFLINE", "total_ram": "OFFLINE", "total_disk": "---"}

            containers = self.client.containers.list(filters={"status": "running"})
            if not containers:
                return {"total_cpu": "0.00%", "total_ram": "0.00MB", "total_disk": "11.05GB"}

            total_cpu = 0.0
            total_mem_mb = 0.0
            sample_containers = containers[:5] 

            for container in sample_containers:
                try:
                    stats = container.stats(stream=False) 
                    mem_usage = stats["memory_stats"].get("usage", 0)
                    total_mem_mb += (mem_usage / 1024 / 1024)

                    cpu_stats = stats.get("cpu_stats", {})
                    precpu_stats = stats.get("precpu_stats", {})
                    cpu_delta = cpu_stats["cpu_usage"]["total_usage"] - precpu_stats["cpu_usage"]["total_usage"]
                    system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)

                    if system_delta > 0.0 and cpu_delta > 0.0:
                        cpu_pct = (cpu_delta / system_delta) * len(cpu_stats["cpu_usage"].get("percpu_usage", [1])) * 100.0
                        total_cpu += cpu_pct
                except Exception as e:
                    self.logger.warning(f"Skipping container {container.name} stats: {e}")
                    continue

            return {
                "total_cpu": f"{total_cpu:.2f}%",
                "total_ram": f"{total_mem_mb:.2f}MB",
                "total_disk": "11.05GB"
            }
        except Exception as e:
            self.logger.error(f"Global Stats Critical Error: {e}")
            return {"total_cpu": "0.00%", "total_ram": "0.00MB", "total_disk": "11.05GB", "error": str(e)}


    def get_total_client_stats_sync(self, client_name: str):
        all_workers = self.client.containers.list(filters={"label": "service=piper-worker"})
        total_cpu = 0.0
        total_mem = 0.0
        count = 0
        for worker in all_workers:
            if worker.name.startswith(f"worker.{client_name}."):
                stats = worker.stats(stream=False)
                cpu_stats = stats["cpu_stats"]
                precpu_stats = stats["precpu_stats"]
                cpu_delta = cpu_stats["cpu_usage"]["total_usage"] - precpu_stats["cpu_usage"]["total_usage"]
                system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
                if system_delta > 0:
                    total_cpu += (cpu_delta / system_delta) * 100.0
                total_mem += stats["memory_stats"].get("usage", 0) / (1024 * 1024)
                count += 1
        return {
            "client": client_name,
            "active_workers": count,
            "total_cpu": f"{total_cpu:.2f}%",
            "total_ram": f"{total_mem:.2f}MB"
        }
    
    async def delete_automation(self, client_name, container_name):
        """Stops the container and removes the template file."""
        try:
            # 1. Stop the process first
            await execute_piper_stop(
                clients=[client_name],
                dsl=[f"{container_name}.yml"],
                password=self.master_password
            )

            # 2. Remove the file
            file_path = os.path.join(self.template_dir, client_name, "waterfall", f"{container_name}.yml")
            if os.path.exists(file_path):
                os.remove(file_path)
                return {"status": "success", "message": f"Deleted {container_name}"}
            
            raise HTTPException(status_code=404, detail="Template file not found")
        except Exception as e:
            self.logger.error(f"Delete Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def get_grouped_client_stats_sync(self, client_name: str):
        grouped_stats = {}
        try:
            workers = self.client.containers.list(filters={"label": "service=piper-worker"})
            for container in workers:
                if container.name.startswith(f"worker.{client_name}."):
                    try:
                        parts = container.name.split('.')
                        current_dsl = parts[2] if len(parts) > 2 else "unknown"
                        stats = container.stats(stream=False)
                        cpu_stats = stats["cpu_stats"]
                        precpu = stats["precpu_stats"]
                        cpu_delta = cpu_stats["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
                        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
                        cpu_pct = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0.0
                        mem_mb = stats["memory_stats"].get("usage", 0) / (1024 * 1024)
                        if current_dsl not in grouped_stats:
                            grouped_stats[current_dsl] = {"cpu": 0.0, "mem": 0.0, "count": 0}
                        grouped_stats[current_dsl]["cpu"] += cpu_pct
                        grouped_stats[current_dsl]["mem"] += mem_mb
                        grouped_stats[current_dsl]["count"] += 1
                    except:
                        continue
            return [
                {
                    "name": name, 
                    "cpu": f"{data['cpu']:.2f}%",
                    "mem": f"{data['mem']:.2f}MB",
                    "active_threads": data['count']
                } for name, data in grouped_stats.items()
            ]
        except Exception as e:
            self.logger.error(f"Grouping Stats Error: {e}")
            return []
