import click
import os
import json
import sys
from dev_utils.setup_build import init_build, test_build
from dev_utils.encryption_manager import get_encryption_key, load_vault, initialize_salt, verify_password, encrypt_value
from dev_utils.task_managers import retrieve_file
from dev_utils.unpacked_data import UnZip
import asyncio
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.theme import Theme
from rich.status import Status
from rich import box
from dev_utils.database_manager import ContextDB

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "danger": "bold red",
    "success": "bold green",
    "key": "bold magenta",
    "path": "bold blue"
})

console = Console(theme=custom_theme)

# Define a path for the master configuration
CONFIG_DIR = ".piper_config"
MASTER_SALT = os.path.join(CONFIG_DIR, ".master_salt")

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

@click.group()
@click.pass_context
def cli(ctx):
    """Piper CLI: Secure Pipeline Management."""
    ensure_config_dir()
    
    # 1. Get the actual tokens used in the command line
    # sys.argv[1:] gives us ['create', 'password']
    full_command = sys.argv[1:]
    
    # 2. Define exempt paths as lists of strings
    exempt_paths = [
        ['create', 'password'],
        ['drop'],
        ['change', 'password']
    ]

    # 3. Check if the current command starts with any exempt path
    # This covers 'piper create password' and 'piper drop'
    is_exempt = any(full_command[:len(path)] == path for path in exempt_paths)
    
    # Also exempt if no command is provided (just running 'piper')
    if not ctx.invoked_subcommand:
        is_exempt = True

    if not is_exempt and not os.path.exists(MASTER_SALT):
        if click.confirm("No Master Password found. Would you like to set one now?", default=True):
            # We use invoke to jump straight to the password creation logic
            ctx.invoke(create_master_password)
        else:
            click.echo("Aborted. A Master Password is required to use this tool.")
            ctx.exit()

@cli.command()
@click.argument('client_files', nargs=-1, required=False)
@click.password_option('--password', envvar='PIPER_MASTER_PASSWORD', help="Master Password to decrypt secrets", prompt=True, hide_input=True,)
def deploy(client_files, password):
    # --- NEW VALIDATION STEP ---
    if not verify_password(password):
        click.echo("❌ Error: Incorrect Master Password. Access Denied.")
        return
    # ---------------------------
    fernet = get_encryption_key(password)

    # Use asyncio.run to kick off the async logic from here
    async def run_deploy():
        if client_files:
            for f in client_files:
                click.echo(f"Processing {f}...")
                await init_build(file_name=f, crypto_engine=fernet)
        else:
            click.echo(f'Initiating piper all client files')
            await init_build(crypto_engine=fernet, password=password)

    asyncio.run(run_deploy())

@cli.group()
def secrets():
    """Manage pipeline secrets."""
    pass

@secrets.command()
@click.argument('key_name')
@click.option('--client', '-c', required=True, help="The client name")
# We use a password prompt here to ensure they have it for THIS session
@click.password_option('--password', help="Master Password to encrypt this secret", prompt=True)
def set(key_name, client, password):
    # --- NEW VALIDATION STEP ---
    if not verify_password(password, MASTER_SALT):
        click.echo("❌ Error: Incorrect Master Password. Access Denied.")
        return
    # ---------------------------
    vault_file = f"templates/{client}/.piper_vault"
    secret_value = click.prompt(f"Enter value for {key_name}", hide_input=True)
    
    # 1. Verify master password/Generate key
    try:
        fernet = get_encryption_key(password, salt_file_path=MASTER_SALT)
        encrypted_value = fernet.encrypt(secret_value.encode()).decode()
        vault = load_vault(vault_file_path=vault_file)
        vault[key_name] = encrypted_value
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(vault_file), exist_ok=True)
        
        with open(vault_file, "w") as f:
            json.dump(vault, f, indent=4)
        
        click.echo(f"✅ Secret '{key_name}' stored for {client}.")
    except Exception as e:
        click.echo(f"❌ Error: {e}")

@secrets.command()
@click.option('--client', '-c', required=True, help="The client name")
@click.password_option('--password', help="Master Password to decrypt secrets", prompt=True)
def list(password, client):
    # --- NEW VALIDATION STEP ---
    if not verify_password(password, MASTER_SALT):
        click.echo("❌ Error: Incorrect Master Password. Access Denied.")
        return
    # ---------------------------
    vault_file = f"templates/{client}/.piper_vault"
    vault = load_vault(vault_file_path=vault_file)
    
    if not vault:
        click.echo("Vault is empty.")
        return

    try:
        # Use the master salt to verify the password
        fernet = get_encryption_key(password, salt_file_path=MASTER_SALT)
        
        click.echo(f"\n{'SECRET NAME':<20} | {'VALUE'}")
        click.echo("-" * 40)
        for k, v in vault.items():
            decrypted = fernet.decrypt(v.encode()).decode()
            click.echo(f"{k:<20} | {decrypted}")
    except Exception:
        click.echo("❌ Error: Incorrect Master Password.")

@cli.group()
def create():
    pass

@secrets.command(name="load")
@click.option('--client', '-c', required=True, help="The client name")
@click.password_option('--password', help="Master Password to encrypt these secrets", prompt=True)
def load_from_file(client, password):
    """Read a file of secrets, encrypt them, and wipe the source file."""
    
    # 1. Verify Master Password
    if not verify_password(password, MASTER_SALT):
        click.echo("❌ Error: Incorrect Master Password. Access Denied.")
        return
    
    file = f"templates/{client}/.config"

    vault_file = f"templates/{client}/.piper_vault"
    new_secrets_count = 0

    try:
        # 2. Get the encryption key
        fernet = get_encryption_key(password, salt_file_path=MASTER_SALT)
        vault = load_vault(vault_file_path=vault_file)

        # 3. Read and Process the file
        with open(file, 'r') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Encrypt and add to vault
                encrypted_value = encrypt_value(value=value, fernet=fernet)
                vault[key] = encrypted_value
                new_secrets_count += 1

        # 4. Save the updated vault
        os.makedirs(os.path.dirname(vault_file), exist_ok=True)
        with open(vault_file, "w") as f:
            json.dump(vault, f, indent=4)

        # 5. SECURITY: Wipe the plain-text file
        with open(file, 'w') as f:
            f.write("# Secrets migrated to Piper Vault\n")
            f.write(f"# Use 'piper secrets list -c {client}' to view these values.\n")
        
        click.echo(f"✅ Successfully loaded {new_secrets_count} secrets into {client} vault.")
        click.echo(f"⚠️  Source file '{file}' has been cleared for security.")

    except Exception as e:
        click.echo(f"❌ Error during load: {e}")

@create.command(name="password")
def create_master_password():
    ensure_config_dir()
    password = click.prompt("Set your Master Password", hide_input=True, confirmation_prompt=True)
    # This initializes the salt file via your utility
    initialize_salt(password=password, salt_file_path=MASTER_SALT)
    click.echo("✅ Master Password set successfully!")

@cli.group()
def change():
    pass

@change.command(name="password")
@click.password_option('--old-password', help="Current Master Password", prompt=True)
@click.password_option('--new-password', help="New Master Password", prompt=True, confirmation_prompt=True)
def change_master_password(old_password, new_password):
    """Update the Master Password and re-encrypt all vaults."""
    
    # 1. Verify Old Password
    if not verify_password(old_password, MASTER_SALT):
        click.echo("❌ Error: Current Master Password incorrect.")
        return

    try:
        old_fernet = get_encryption_key(old_password, salt_file_path=MASTER_SALT)
        new_fernet = get_encryption_key(new_password, salt_file_path=MASTER_SALT)

        # 2. Iterate through all client vaults to re-encrypt
        # Assuming vaults are in templates/{client}/.piper_vault
        base_dir = "templates"
        if os.path.exists(base_dir):
            for client in os.listdir(base_dir):
                vault_path = os.path.join(base_dir, client, ".piper_vault")
                if os.path.exists(vault_path):
                    click.echo(f"🔄 Re-encrypting vault for: {client}...")
                    
                    # Load and Decrypt
                    vault = retrieve_file(vault_path)
                    decrypted_vault = {}
                    for k, v in vault.items():
                        decrypted_val = old_fernet.decrypt(v.encode()).decode()
                        # Re-encrypt with NEW key
                        decrypted_vault[k] = new_fernet.encrypt(decrypted_val.encode()).decode()
                        
                    # Save back to file
                    with open(vault_path, "w") as f:
                        json.dump(decrypted_vault, f, indent=4)

        # 3. Update the Master Salt/Hash file with the NEW password
        # Note: Your initialize_salt function should ideally overwrite the existing salt
        initialize_salt(password=new_password, salt_file_path=MASTER_SALT)
        
        click.echo("✅ Master Password updated and all secrets re-encrypted successfully!")

    except Exception as e:
        click.echo(f"❌ Critical Error during migration: {e}")
        click.echo("⚠️  Your vaults might be in an inconsistent state.")

@cli.command()
@click.argument('task', required=True)
@click.option('--client', '-c', required=True, help="The client name")
@click.password_option('--password', help="Master Password to encrypt this secret", prompt=True)
def test(task, client, password):
    # --- NEW VALIDATION STEP ---
    if not verify_password(password, MASTER_SALT):
        click.echo("❌ Error: Incorrect Master Password. Access Denied.")
        return
    # ---------------------------
    fernet = get_encryption_key(password, salt_file_path=MASTER_SALT)
    path = f"templates/{client}/waterfall.yml"

    test_build(crypto_engine=fernet, file_path=path, name=client, task=task)

@cli.command()
@click.option('--client', '-c', required=True, help="The client name")
@click.option('--password', prompt="Master Password", hide_input=True)
@click.argument('task')
def inspect(client, password, task):
    """
    🔍 Inspect the state of a specific task from the latest pipeline run.
    """
    # 1. Validation Logic
    if not verify_password(password):
        console.print("[danger]❌ Access Denied:[/danger] Incorrect Master Password.")
        return

    path = f"templates/{client}/.context_manager"

    # 2. Safe Retrieval with Status Spinner
    with console.status(f"[info]Loading history for [bold]{client}[/]...", spinner="bouncingBar"):
        try:
            context_data = retrieve_file(file_path=path) or {}
        except Exception:
            context_data = {}
        
        if not isinstance(context_data, dict) or not context_data:
            console.print(Panel(
                f"[danger]Error:[/danger] Context file is empty or missing at:\n[white]{path}[/]",
                title="File Error", border_style="red"
            ))
            return
        
        try:
            lask_key = next(reversed(context_data))
            active_run = context_data.get(lask_key)
            task_obj = active_run.get(task)
        except (IndexError, AttributeError, TypeError, StopIteration):
            active_run = {}
            task_obj = None

    # 3. Smart Fallback
    if not task_obj:
        available = ", ".join([f"[key]{k}[/]" for k in active_run.keys()]) or "[dim]No tasks found[/]"
        console.print(Panel(
            f"[warning]Task [bold yellow]'{task}'[/] was not found in the latest run.[/]\n\n"
            f"[info]Available tasks in this session:[/]\n{available}",
            title="[danger]Missing Task[/]",
            border_style="red"
        ))
        return

    # 4. Unpacking Logic
    unzip = UnZip()
    unzip.unpack_bulk_data(content=task_obj)

    # 5. The "Fancy" Header
    console.print(
        Panel(
            f"Inspecting: [bold cyan]{task}[/]\n"
            f"Client   : [bold white]{client}[/]\n"
            f"Keys     : [bold green]{len(unzip.key_path)} items found[/]",
            expand=False,
            border_style="blue",
            title="[bold magenta] 🔍 Piper Context Inspector [/]",
            title_align="left",
            subtitle=f"[dim]Source: {path}[/dim]",
            subtitle_align="right"
        )
    )

    # 6. Creating the High-Contrast Table
    table = Table(
        show_header=True, 
        header_style="bold white on blue", 
        box=box.DOUBLE_EDGE, 
        row_styles=["none", "dim"], 
        expand=True,
        # ADDED: This creates horizontal lines between every row for better separation
        show_lines=True 
    )

    # Added no_wrap=False and overflow="fold" to ensure long tags wrap to the next line
    table.add_column("VARIABLE TAG (Copy/Paste)", style="path", no_wrap=False, overflow="fold")
    table.add_column("VALUE / DATA", style="success", no_wrap=False, overflow="fold")

    for key, val in unzip.key_path.items():
        variable_tag = f"{{{{{task}.{key}}}}}"
        
        # Removed the truncation logic entirely so values can span multiple lines
        display_val = str(val)

        table.add_row(variable_tag, display_val)

    # 7. Final Output
    console.print(table)
    console.print(f"\n[dim italic]Finished inspecting {task}. Total keys: {len(unzip.key_path)}[/dim italic]\n")

@cli.command()
def drop():
    click.echo('Dropped the database')

@click.command()
@click.option('--db-url', envvar='DATABASE_URL', help="Connection string for the database.")
@click.command()
def init():
    """🚀 Zero-Touch Setup: Configures DB, Folders, and Environment."""
    click.echo("Starting Piper Engine Initialization...")

    # 1. Database Setup
    try:
        db = ContextDB()
        db.initialize_tables()
        click.echo("✅ Database tables verified/created.")
    except Exception as e:
        click.echo(f"❌ Database error: {e}")
        return

    # 2. Linux/System Setup (Folders needed for logs or templates)
    paths = ["logs", "templates", "temp_downloads"]
    for path in paths:
        if not os.path.exists(path):
            os.makedirs(path)
            click.echo(f"✅ Created system directory: {path}")

    # 3. Future Step: Check for updates or verify Master Password
    # You can add more 'silent' steps here as your engine grows.

    click.echo(click.style("\nInitialization Complete. Ready for 'piper deploy'.", fg="green", bold=True))

if __name__ == '__main__':
    cli()