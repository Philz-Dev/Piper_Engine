FROM python:3.11-slim

# Install common libraries users might want
RUN pip install requests pandas pydantic 

WORKDIR /app

# Bake the Bridge into the image
COPY runner.py /app/runner.py

# This makes the container stay alive and wait for the Orchestrator
ENTRYPOINT ["python3", "runner.py"]