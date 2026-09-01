FROM python:3.11-slim

WORKDIR /app
# Install common libraries users might want
RUN pip install requests pandas pydantic 

WORKDIR /app

COPY runner-python/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Bridge into the image
COPY runner-python/ ./runner-python/

# This makes the container stay alive and wait for the Orchestrator
ENTRYPOINT ["python", "/app/runner-python/worker_daemon.py"]