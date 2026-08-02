from enum import Enum

class ActionSignal(Enum):
    CONTINUE = 0
    BREAK = 1
    GOTO = 2
    STOP_ALL = 3
    CALL = 4
    EXECUTE = 5
    RETRY = 6
    STOP = "stop"  # 🛑 New stop signal
    SLEEP = 'sleep'

class PipelineGlobalExit(Exception):
    pass

import asyncio

async def goto(target: str):
    # We don't change idx here; we pass instructions to the executor
    return {"signal": ActionSignal.GOTO, "target": target}

async def retry(target: str):
    # We don't change idx here; we pass instructions to the executor
    return {"signal": ActionSignal.RETRY}
    
async def break_loop():
    return {"signal": ActionSignal.BREAK}

async def stop_all():
    # Raise exception to bubble up and kill execution
    raise PipelineGlobalExit("Pipeline explicitly stopped by stop_all action.")

async def sleep(seconds: int = 1):
    await asyncio.sleep(int(seconds))
    return {"signal": ActionSignal.CONTINUE}

async def log(message: str, level: str = "info"):
    print(f"[{level.upper()}]: {message}")
    return {"signal": ActionSignal.CONTINUE}

async def ignore():
    return {"signal": ActionSignal.CONTINUE}

async def retry(attempts: int = 1):
    # This implementation requires your executor to handle 'RETRY' signal
    return {"signal": ActionSignal.RETRY, "attempts": attempts}

async def call(target: str, type: str="block"):
    # Tells the executor to save location and jump
    return {"signal": ActionSignal.CALL, "target": target, "type":type}

async def execute():
    # Tells the executor to save location and jump
    return {"signal": ActionSignal.EXECUTE}

async def sleep(timeout: str):
    return {"signal": ActionSignal.SLEEP}

async def stop():
    return {"signal": ActionSignal.STOP}


