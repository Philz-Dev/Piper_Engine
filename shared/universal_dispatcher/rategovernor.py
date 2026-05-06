import asyncio

# Use this one
class RateGovernor:
    _instance = None
    _locks = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RateGovernor, cls).__new__(cls)
        return cls._instance

    async def yield_control(self, app_name, limit_per_sec):
        # Extract base name (e.g., 'Hubspot') so all Hubspot tasks share the same limit
        base_app = app_name.split('.')[0]
        
        if base_app not in self._locks:
            self._locks[base_app] = asyncio.Lock()
        
        async with self._locks[base_app]:
            interval = 1.0 / limit_per_sec
            await asyncio.sleep(interval)