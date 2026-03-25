FROM python:3.11-slim

WORKDIR /app

# 1. Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy the Engine source code (Removed the dot before src)
COPY src/ ./src/
COPY .piper_config ./.piper_config

# 4. Set PYTHONPATH (Fixed the variable definition)
ENV PYTHONPATH="/app:/app/src:/app/src/dev_utils"

# 5. The Entrypoint
ENTRYPOINT ["python", "src/dev_utils/cli_manager/core.py"]
CMD ["deploy"]