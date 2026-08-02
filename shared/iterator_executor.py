import csv
import json
import logging
import os
from shared.database_manager import ContextDB
import uuid
import json
from datetime import datetime
import redis

logger = logging.getLogger("IteratorManager")
db = ContextDB()
r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)

class IteratorManager:
    def __init__(self, storage_root="/app/piper_storage"):
        self.storage_root = storage_root
    
    def get_file_path(self, client_name, task_id, filename="data.csv"):
        return f"{self.storage_root}/{client_name}/{task_id}/{filename}"

    def iterate(self, client_name, task_id, filename="data.csv"):
        """Reads a CSV file line by line and yields rows as JSON."""
        file_path = self.get_file_path(client_name, task_id, filename)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No file found at {file_path}")

        with open(file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield row

