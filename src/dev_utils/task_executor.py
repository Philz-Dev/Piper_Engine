from dev_utils.registry import ACTION_MAP
from dev_utils.trigger_service_manager import trigger_exe

async def func(_cont, password):
    order_of_ops = ["trigger", "Pipeline"]
    for k in order_of_ops:
        if not _cont.get(k):
            continue
        await ACTION_MAP[k](_cont=_cont, action=ACTION_MAP, password=password)
        break
        
        