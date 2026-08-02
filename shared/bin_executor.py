import httpx
import aiofiles
import logging
import os
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("BinManager")

class BinManager:
    def __init__(self, storage_root="/app/piper_storage"):
        self.storage_root = storage_root

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, IOError)),
        reraise=True
    )
    async def download_stream(self, url, client_name, task_id, filename="data.csv"):
        """Streams a file directly to disk without loading into RAM."""
        
        # 1. Setup path: piper_storage/{client}/{task_id}/data.csv
        target_dir = os.path.join(self.storage_root, client_name, task_id)
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, filename)

        logger.info(f"📥 Starting stream download to: {file_path}")

        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                
                # 2. Write to disk in 64KB chunks
                async with aiofiles.open(file_path, mode='wb') as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        await f.write(chunk)
        
        return file_path