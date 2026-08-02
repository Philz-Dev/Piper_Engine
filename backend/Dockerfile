# Dockerfile
FROM python:3.11-slim

WORKDIR /app/backend

# Copy requirements and install
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy your application code
COPY ./ ./

ENTRYPOINT [ "python", "main.py"]