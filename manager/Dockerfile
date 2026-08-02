# 1. Use a lightweight Python base
FROM python:3.11-slim

# 2. Set environment variables to optimize Python inside Docker
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Set the working directory
WORKDIR /app

# 4. Install System Dependencies
# This is where your 'apt' flags come in
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*


# 5. Install Python dependencies
# Copy only requirements first to leverage Docker caching
COPY manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy the rest of your application code
COPY manager/ ./manager/
COPY shared/ ./shared/
COPY .piper_config/ ./.piper_config/


RUN pip install -e ./shared

# 3. Install 'manager' 
RUN pip install -e ./manager
# Make sure it is executable
#RUN chmod +x /app/manager/entrypoint.sh


ENV PYTHONPATH="/app:/app/manager:/app/shared"

ENTRYPOINT ["python", "/app/manager/cli_manager/core.py"]
#ENTRYPOINT ["/app/manager/entrypoint.sh"]
