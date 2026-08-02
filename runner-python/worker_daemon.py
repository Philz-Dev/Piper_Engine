import json
import os
import subprocess
import sys
import time
import redis

r = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis-broker"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)
WORKER_STREAM = "piper_python_stream"
GROUP_NAME = "python_workers"
CONSUMER_NAME = os.getenv("SANDBOX_WORKER_NAME", "python-worker-1")

# Ensure the consumer group exists
try:
  r.xgroup_create(WORKER_STREAM, GROUP_NAME, id="0", mkstream=True)
except redis.exceptions.ResponseError:
  pass  # Group already exists


def process_stream_task(task_data: dict):
  file_path = task_data.get("file_path")
  context = task_data.get("context", {})
  response_channel = task_data.get("response_channel")

  # Configure environment variables for the single-shot bootstrap.py execution
  env = os.environ.copy()
  env["PIPER_CONTEXT"] = json.dumps(context)
  if response_channel:
    env["PIPER_RESPONSE_CHANNEL"] = response_channel
  env["PYTHONUNBUFFERED"] = "1"

  # Invoke your single-shot bootstrap.py safely via subprocess
  cmd = ["python3", "/app/runner-python/runner.py", file_path]
  try:
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
  except Exception as e:
    if response_channel:
      r.publish(
          response_channel,
          json.dumps({"error": f"Subprocess launch crash: {str(e)}"}),
      )


def main():
  print(f"Python Stream Worker {CONSUMER_NAME} is listening to {WORKER_STREAM}...")
  while True:
    try:
      streams = r.xreadgroup(
          GROUP_NAME, CONSUMER_NAME, {WORKER_STREAM: ">"}, count=1, block=2000
      )
      if streams:
        for stream, messages in streams:
          for message_id, data in messages:
            task_payload = json.loads(data.get("payload", "{}"))
            process_stream_task(task_payload)
            r.xack(WORKER_STREAM, GROUP_NAME, message_id)
    except Exception as e:
      print(f"Worker Error: {e}", file=sys.stderr)
      time.sleep(1)


if __name__ == "__main__":
  main()