FROM python:3.11-slim

WORKDIR /app

# 2. Install Docker CLI & Docker Compose (Back to your original working version)
# We ONLY need libpq-dev if your DatabaseManager uses psycopg2
# Otherwise, we don't need any system tools at all!
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Python dependencies
COPY controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the Engine source code 
COPY controller/ ./controller/
COPY .piper_config ./.piper_config/

# 5. Set Environment
ENV PYTHONPATH="/app"
ENV PATH="/usr/local/bin:/usr/bin:/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

RUN groupadd -g 999 docker && usermod -aG docker root

# 6. The Entrypoint
ENTRYPOINT ["python", "controller/watcher.py"]