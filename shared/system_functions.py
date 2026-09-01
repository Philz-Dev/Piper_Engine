from enum import Enum

class ActionSignal(Enum):
    CONTINUE = 0
    BREAK = 1
    GOTO = 2
    STOP_ALL = 3
    CALL = 4
    RETRY = 6
    STOP = 7  # 🛑 New stop signal
    SLEEP = 8
    LOG = 9
    IGNORE = 10
    EXIT = 11

class PipelineGlobalExit(Exception):
    pass

import asyncio

async def goto(target: str):
    # We don't change idx here; we pass instructions to the executor
    return {"signal": ActionSignal.GOTO, "target": target}
    
async def sleep(seconds: int = 1):
    await asyncio.sleep(int(seconds))
    return {"signal": ActionSignal.SLEEP}

async def log(message: str, level: str = "info"):
    print(f"[{level.upper()}]: {message}")
    return {"signal": ActionSignal.LOG}

async def ignore():
    return {"signal": ActionSignal.IGNORE}

async def retry(attempts: int = 1):
    # This implementation requires your executor to handle 'RETRY' signal
    return {"signal": ActionSignal.RETRY, "attempts": attempts}

async def call(target: str, type: str="block"):
    # Tells the executor to save location and jump
    return {"signal": ActionSignal.CALL, "target": target, "type":type}

async def stop():
    return {"signal": ActionSignal.STOP}

async def exit():
    return {"signal": ActionSignal.EXIT}

async def skip():
    return {"signal": ActionSignal.CONTINUE}

async def to_break():
    return {"signal": ActionSignal.BREAK}


