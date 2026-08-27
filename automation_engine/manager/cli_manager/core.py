import click
import os
import json
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from shared.encryption_manager import get_encryption_key, load_vault, initialize_salt, verify_password, encrypt_value
from shared.interpreter import retrieve_file
from shared.unpacked_data import UnZip
import asyncio
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.theme import Theme
from rich.status import Status
from rich import box
from shared.database_manager import ContextDB
import subprocess
import requests
import re
import yaml
import textwrap 
from shared.tools import retrieve_file
from shared.redis_queuer import handover_password
from shared.database_manager import ContextDB
from shared.setup_build import execute_piper_start, execute_piper_stop
import docker

DB = ContextDB()

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "danger": "bold red",
    "success": "bold green",
    "key": "bold magenta",
    "path": "bold blue"
})

console = Console(theme=custom_theme)

## --- ENHANCED CONFIG DETECTION ---
# If /app exists, we are inside a container. Use the absolute path.

def is_container():
    # Check for the filesystem or the env var
    return os.path.exists('/.dockerenv') or os.environ.get('IS_PIPER_CONTAINER') == 'true'

# ✅ FIX: Remove the duplicate BASE_PATH = os.getcwd() below this
if is_container():
    BASE_PATH = "/app"
else:
    BASE_PATH = os.getcwd()

CONFIG_DIR = os.path.join(BASE_PATH, ".piper_config")
MASTER_SALT = os.path.join(CONFIG_DIR, ".master_salt")
CURRENT_VERSION = "v1"
REPO_URL = "https://api.github.com/repos/Philz-Dev/Piper_Engine/releases/latest"

def check_for_updates():
    """Silently check if a newer version exists on GitHub."""
    try:
        response = requests.get(REPO_URL, timeout=2)
        if response.status_code == 200:
            latest_release = response.json().get("tag_name", "v1")
            
            if latest_release != CURRENT_VERSION:
                click.secho(f"\n[notice] A new version of piper is available: {CURRENT_VERSION} -> {latest_release}", fg="yellow")
                click.secho(f"[notice] To update, run: piper update\n", fg="yellow")
                return latest_release
    except Exception:
        pass
    return None

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

@click.group()
@click.pass_context
def cli(ctx):
    """Piper CLI: Secure Pipeline Management."""
    check_for_updates()
    ensure_config_dir()
    
    full_command = sys.argv[1:]
    
    exempt_paths = [
        ['create', 'password'],
        ['dropall'],
        ['change', 'password'],
        ['run'] # Docker workers don't need to trigger the setup check
    ]

    is_exempt = any(full_command[:len(path)] == path for path in exempt_paths)
    
    if not ctx.invoked_subcommand:
        is_exempt = True

    if not is_exempt and not os.path.exists(MASTER_SALT):
        if click.confirm("No Master Password found. Would you like to set one now?", default=True):
            ctx.invoke(create_master_password)
        else:
            click.echo("Aborted. A Master Password is required to use this tool.")
            ctx.exit()

@cli.command()
@click.confirmation_option(
    prompt='🚨 DANGER ZONE 🚨\nAre you sure you want to permanently drop EVERY single schema table within the piper application database?'
)
@click.password_option(
    '--password', 
    envvar='PIPER_MASTER_PASSWORD', 
    help="Master Password required to execute full database purge", 
    prompt="Enter Master Password to authorize nuclear wipe"
)
def dropall(password):
    """🚨 Nuke Database: Permanently drops EVERY table in the system schema."""
    
    # 1. Identity Verification Security Check
    if not verify_password(password):
        console.print("[danger]❌ Access Denied:[/danger] Incorrect Master Password. Database purge aborted.")
        return

    # 2. Execute Atomic Database Drop Transaction
    with console.status("[danger]💥 Initiating complete system database purge...[/danger]", spinner="bouncingBar"):
        try:
            success = DB.danger_drop_all_tables()
            
            if success:
                console.print("\n[success]💥 System Purge Successful: All piper tables dropped. Database is completely empty.[/success]")
                console.print("[info]Tip: Run 'piper init' if you need to reconstruct empty default schema structures.[/info]")
            else:
                console.print("\n[danger]❌ Drop operation encountered an internal transactional error.[/danger]")
                
        except Exception as e:
            console.print(f"\n[danger]❌ Critical execution failure:[/danger] {e}")

# --- ENGINE COMMANDS (DOCKER SIDE) ---

@cli.command()
@click.confirmation_option(prompt='Are you sure you want to wipe Pipeline Storage?')
def reset():
    """Wipes and recreates the pipeline_storage table."""
    # Use your existing 'console' for that sweet Rich formatting
    with console.status("[info]Resetting Database...", spinner="dots"):
        try:
            # This now works because DB is an instance!
            DB.reset_pipeline_storage()
            console.print("[success]✅ Table recreated with UNIQUE(client_id) constraint.[/success]")
        except Exception as e:
            console.print(f"[danger]❌ Reset failed:[/danger] {e}")

@cli.group()
def secrets():
    """Manage pipeline secrets."""
    pass

@cli.command()
@click.argument('service_key')
@click.option('--client', '-c', 'client_name', required=True, help="The client name")
@click.password_option('--password', envvar='PIPER_MASTER_PASSWORD', help="Master Password to authorize removal", prompt=True)
def removeapi(service_key, client_name, password):
    """✂️ Surgically remove a service key from the vault (e.g., 'Typeform')."""
    
    # 1. Verify Identity
    if not verify_password(password):
        console.print("[danger]❌ Access Denied:[/danger] Incorrect Master Password.")
        return

    # 2. Execute via Database Manager
    with console.status(f"[info]Removing {service_key} from {client_name}'s vault...", spinner="dots"):
        # Calling the function you defined in your database manager
        success = DB.remove_service_from_vault(client_name=client_name, service_key=service_key)
        
        if success:
            console.print(f"[success]✅ Successfully removed [key]{service_key}[/key] from [info]{client_name}[/info].[/success]")
        else:
            console.print(f"[danger]❌ Operation failed.[/danger] Ensure the client exists in the vault.")

@cli.command()
@click.confirmation_option(prompt='Are you sure you want to wipe Pipeline Storage?')
def resetcontext():
    with console.status("[info]Resetting Database...", spinner="dots"):
        try:
            console.print("[success]✅ Table recreated with UNIQUE(client_id) constraint.[/success]")
            DB.danger_drop_context_table()
        except Exception as e:
                console.print(f"[danger]❌ Reset context failed:[/danger] {e}")

@cli.command()
@click.argument('clients', nargs=-1)
@click.option('--dsl', '-d', multiple=True, help="Specific DSL files to run")
@click.password_option('--password', envvar='PIPER_MASTER_PASSWORD')
def start(clients, dsl, password):
    """🚀 Start Piper: Deploy specific clients or the entire fleet."""
    import asyncio
    from shared.setup_build import execute_piper_start

    success, message = asyncio.run(
        execute_piper_start(clients=clients, dsl=dsl, password=password, logger=click.echo)
    )
    
    if not success:
        click.secho(f"❌ {message}", fg="red")

@cli.command()
def stats():
    """📊 View Global Engine Resource Usage."""
    import docker
    
    # Force connection to the local socket (standard for Windows/Linux)
    try:
        # On Windows/MINGW64, this usually maps correctly if Docker Desktop is running
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    except:
        # Fallback to default env discovery
        client = docker.from_env()

    total_cpu = 0.0
    total_mem_mb = 0.0
    
    try:
        containers = client.containers.list(filters={"status": "running"})
        
        if not containers:
            console.print("[yellow]📭 No containers are currently running.[/yellow]")
            return

        with console.status("[info]Calculating resource usage...", spinner="dots"):
            for container in containers:
                try:
                    stats = container.stats(stream=False)
                    
                    # CPU Calc
                    cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                                stats["precpu_stats"]["cpu_usage"]["total_usage"]
                    system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                                   stats["precpu_stats"]["system_cpu_usage"]
                    
                    if system_delta > 0.0:
                        # len(percpu_usage) gives number of cores
                        cores = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
                        cpu_pct = (cpu_delta / system_delta) * cores * 100.0
                        total_cpu += cpu_pct

                    # Memory Calc
                    mem_usage = stats["memory_stats"].get("usage", 0)
                    total_mem_mb += (mem_usage / 1024 / 1024)
                except (KeyError, TypeError):
                    continue

        # Display result in a nice Rich Panel
        console.print(Panel(
            f"[bold cyan]Total CPU Usage:[/bold cyan] [success]{total_cpu:.2f}%[/success]\n"
            f"[bold cyan]Total Memory usage:[/bold cyan] [success]{total_mem_mb:.2f} MB[/success]\n"
            f"[info]Active Containers:[/info] {len(containers)}",
            title="[bold magenta]🛰️ Global Engine Stats[/bold magenta]",
            border_style="blue"
        ))

    except Exception as e:
        console.print(f"[danger]❌ Docker Connection Error:[/danger] {e}")
        console.print("[info]Tip: Ensure Docker Desktop is running and 'Expose daemon on tcp://localhost:2375' is OFF if using unix socket.[/info]")

@cli.command()
@click.argument('clients', nargs=-1)
@click.option('--dsl', '-d', multiple=True, help="Specific tasks/DSLs to stop")
@click.password_option('--password', envvar='PIPER_MASTER_PASSWORD')
def stop(clients, dsl, password):
    """🛑 Stop Piper: Graceful shutdown for clients or the entire fleet."""
    import asyncio
    from shared.setup_build import execute_piper_stop

    with console.status("[danger]Initiating stop sequence...", spinner="earth"):
        success, message = asyncio.run(
            execute_piper_stop(clients=clients, dsl=dsl, password=password)
        )

    if success:
        console.print(f"[success]✅ {message}[/success]")
    else:
        console.print(f"[danger]❌ Stop Sequence Failed: {message}[/danger]")

@cli.command()
def status():
    """List all active Piper workers and their status."""
    import subprocess
    
    # We filter for containers that have 'engine' in the name
    cmd = ["docker", "ps", "--filter", "name=_engine", "--format", "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            click.secho("📭 No active workers found.", fg="yellow")
        else:
            click.secho("🛰️  Active Piper Workers:", fg="cyan", bold=True)
            click.echo(result.stdout)
    except subprocess.CalledProcessError as e:
        click.secho(f"💥 Error fetching status: {e}", fg="red")

@cli.command()
@click.option('-c', '--client', 'client_name', required=True)
def logs(client_name):
    """View real-time logs for a specific client worker."""
    container_name = f"{client_name}_engine"
    click.echo(f"📋 Fetching logs for {container_name}...")
    
    # -f follows the logs in real-time
    cmd = ["docker", "logs", "-f", "--tail", "20", container_name]
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        click.echo("\n👋 Exited log view.")
    except subprocess.CalledProcessError:
        click.secho(f"❌ Could not find logs for {client_name}.", fg="red")

@cli.command()
@click.option('-c', '--client', 'client_name', help='Specific client to update')
@click.option('--all', 'update_all', is_flag=True, help='Update every client in the system')
def update(client_name, update_all):
    """Fetch the NEWEST official version and upgrade clients."""
    click.echo("🔍 Checking GitHub for new releases...")
    latest_version = check_for_updates()
    
    target_tag = latest_version if latest_version else "latest"
    image_path = f"ghcr.io/philz-dev/piper-engine:{target_tag}"

    click.echo(f"🚚 Pulling {image_path}...")
    try:
        subprocess.run(["docker", "pull", image_path], check=True)
    except subprocess.CalledProcessError:
        click.secho("❌ Failed to pull image.", fg="red")
        return

    if client_name:
        client_path = os.path.join("templates", client_name, "docker-compose.yml")
        if not os.path.exists(client_path):
            click.secho(f"❌ Client '{client_name}' config not found.", fg="red")
            return
        
        upgrade_yaml_version(client_path, target_tag)
        click.echo(f"🔄 Restarting {client_name} on {target_tag}...")
        ctx = click.get_current_context()
        ctx.invoke(start, client_name=client_name)
        click.secho(f"✅ {client_name} is now running {target_tag}!", fg="green", bold=True)

    elif update_all:
        client_list = [d for d in os.listdir('templates') if os.path.isdir(os.path.join('templates', d))]
        with click.progressbar(client_list, label=f"Upgrading Fleet to {target_tag}") as bar:
            for c in bar:
                c_path = os.path.join("templates", c, "docker-compose.yml")
                upgrade_yaml_version(c_path, target_tag)
                ctx = click.get_current_context()
                ctx.invoke(start, client_name=c)
        click.secho(f"🚀 Entire fleet migrated to {target_tag}!", fg="green", bold=True)

def upgrade_yaml_version(file_path, new_tag):
    with open(file_path, 'r') as f:
        content = f.read()
    new_content = re.sub(r'(image: ghcr\.io/philz-dev/piper-engine:)([\w\.]+)', f'\\1{new_tag}', content)
    with open(file_path, 'w') as f:
        f.write(new_content)

# --- DEPLOYMENT & SECRETS ---

@cli.group()
def secrets():
    """Manage pipeline secrets."""
    pass

@secrets.command()
@click.argument('key_name')
@click.option('--client', '-c', required=True, help="The client name")
@click.password_option('--password', help="Master Password to encrypt this secret", prompt=True)
def set(key_name, client, password):
    if not verify_password(password):
        click.echo("❌ Error: Incorrect Master Password.")
        return
    vault_file = f"templates/{client}/.piper_vault"
    secret_value = click.prompt(f"Enter value for {key_name}", hide_input=True)
    
    try:
        fernet = get_encryption_key(password)
        encrypted_value = fernet.encrypt(secret_value.encode()).decode()
        vault = retrieve_file(file_path=vault_file)
        print(vault)
        vault[key_name] = encrypted_value
        os.makedirs(os.path.dirname(vault_file), exist_ok=True)
        with open(vault_file, "w") as f:
            json.dump(vault, f, indent=4)
        click.echo(f"✅ Secret '{key_name}' stored for {client}.")
    except Exception as e:
        click.echo(f"❌ Error: {e}")

@cli.group()
def create():
    pass

@create.command(name="password")
def create_master_password():
    ensure_config_dir()
    password = click.prompt("Set your Master Password", hide_input=True, confirmation_prompt=True)
    initialize_salt(password=password)
    click.echo("✅ Master Password set successfully!")

@cli.command()
@click.option('--client', '-c', required=True, help="The client name")
@click.option('--password', prompt="Master Password", hide_input=True)
@click.argument('task')
def inspect(client, password, task):
    """🔍 Inspect the state of a specific task (DB Mode)."""
    db = ContextDB()
    if not verify_password(password):
        console.print("[danger]❌ Access Denied:[/danger] Incorrect Master Password.")
        return

    with console.status(f"[info]Querying Database for [bold]{client}[/]...", spinner="bouncingBar"):
        try:
            context_data = db.get_context(client, "PIPELINE_ROOT") or {}
        except Exception as e:
            console.print(f"[danger]DB Error:[/danger] {e}")
            return
        
        if not context_data:
            console.print(Panel(f"No execution history found for: {client}", title="Data Missing", border_style="red"))
            return
        
        try:
            last_key = next(reversed(context_data))
            active_run = context_data.get(last_key)
            task_obj = active_run.get(task)
        except Exception:
            task_obj = None

    if not task_obj:
        console.print(f"[warning]Task '{task}' not found.[/]")
        return

    unzip = UnZip()
    unzip.unpack_bulk_data(content=task_obj)

    table = Table(title=f"Context: {task}", header_style="bold white on blue", box=box.DOUBLE_EDGE)
    table.add_column("VARIABLE TAG", style="path")
    table.add_column("VALUE", style="success")

    for key, val in unzip.key_path.items():
        table.add_row(f"{{{{{task}.{key}}}}}", str(val))

    console.print(table)

@cli.command()
@click.pass_context
def init(ctx):
    """🚀 Zero-Touch Setup: Configures Security, DB, and Folders."""
    console.print(Panel("[bold cyan]Starting Piper Engine Initialization...[/]", border_style="blue"))
    
    # ✅ STEP 1: Security Handshake
    ensure_config_dir()
    if not os.path.exists(MASTER_SALT):
        console.print("[warning]⚠️ No Master Password found. Initializing Security...[/]")
        # We invoke your existing create_master_password command
        ctx.invoke(create_master_password)
    else:
        console.print("[success]✅ Security Vault verified.[/]")

    # ✅ STEP 2: Database Setup
    try:
        db = ContextDB()
        db.initialize_tables()
        console.print("[success]✅ Database tables verified/created.[/]")
    except Exception as e:
        console.print(f"[danger]❌ Database error:[/danger] {e}")
        return

    # ✅ STEP 3: Folder Structure
    paths = ["logs", "templates", "temp_downloads"]
    for path in paths:
        if not os.path.exists(path):
            os.makedirs(path)
            console.print(f"[info]Created directory:[/info] [path]{path}[/path]")
            
    console.print(Panel("\n[bold green]Initialization Complete.[/bold green]", box=box.ROUNDED))

if __name__ == '__main__':
     cli()