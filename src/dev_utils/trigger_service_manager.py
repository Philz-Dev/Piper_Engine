import subprocess
import time
import os
import json
from dev_utils.universal_dispatcher.core import dispatcher
from dev_utils.encryption_manager import get_encryption_key

async def trigger_exe(_cont, password, action=None):
    _crypto_engine = get_encryption_key(password)
    trigger_cont = _cont["trigger"]["args"]
    trig_c = _cont["trigger"]
    services = {"webhook": start_webhook, "timer": start_timer}
    await services[_cont["trigger"]["_type"]](_cont=trigger_cont, _all_cont=_cont["Pipeline"], crypto_engine=_crypto_engine, trig_c=trig_c, password=password)

async def start_webhook(_cont, trig_c, _all_cont, crypto_engine, password):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    cont_to_json = json.dumps(_cont)
    _all_to_json = json.dumps(_all_cont)
    trig = json.dumps(trig_c)
    master_password = json.dumps(password)

    print("--- PHASE 2: Starting Webhook Listener & Tunnel ---")
    listener_path = os.path.join(BASE_DIR, "universal_webhook\core.py")
    proc = subprocess.Popen(["python", listener_path, _all_to_json, cont_to_json, trig, master_password])
    
    # Give the listener/ngrok a few seconds to initialize and generate a URL
    time.sleep(5)

    # PHASE 3: Registration
    # Now that ngrok is (hopefully) up, we tell the API where we are.
    print("--- PHASE 3: Registering URL with Provider ---")
    await dispatcher(_args=_cont, _crypto_engine=crypto_engine)

    print("\n--- System Fully Operational ---")
    # This keeps the main script alive while the background process runs
    proc.wait()

async def start_timer(_type: str=None, _action: str=None, _args: dict=None, password=None):
    pass