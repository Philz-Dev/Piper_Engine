FROM python:3.11-slim

WORKDIR /app

# 1. Install system dependencies (Original + unzip)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    procps \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Python dependencies
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the Engine source code 
COPY worker/ ./worker/
COPY shared/ ./shared/

RUN pip install -e ./shared

# 5. Set Environment
ENV PYTHONPATH="/app"
ENV PYTHONPATH="/app:/app/worker:/app/shared"

RUN groupadd -g 999 docker && usermod -aG docker root

# 6. The Entrypoint
ENTRYPOINT ["python", "/app/worker/main.py"]