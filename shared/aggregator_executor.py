import json
import logging
from shared.database_manager import ContextDB
import os

logger = logging.getLogger("AggregatorManager")
db = ContextDB()

class AggregatorManager:
    def __init__(self, storage_root="/app/piper_storage"):
        self.storage_root = storage_root

    def append_data(self, client_name, task_id, data_row, filename="aggregated_result.json"):
        """Appends a new result to a persistent JSON file (or CSV)."""
        target_dir = f"{self.storage_root}/{client_name}/{task_id}"
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, filename)

        # Using JSON Lines format (efficient for appending)
        with open(file_path, mode='a', encoding='utf-8') as f:
            f.write(json.dumps(data_row) + "\n")
        
        return file_path