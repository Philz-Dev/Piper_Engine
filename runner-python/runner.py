import importlib.util
import json
import os
import sys
import redis

# Load configuration from environment
context_data = json.loads(os.getenv("PIPER_CONTEXT", "{}"))
result_key = os.getenv("PIPER_RESULT_KEY")
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis-broker"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)


response_channel = os.getenv("PIPER_RESPONSE_CHANNEL")


def write_result(data):
  if response_channel:
    try:
      r.publish(response_channel, json.dumps(data))
    except Exception as e:
      print(json.dumps({"error": f"Redis Publish Error: {str(e)}"}))
  else:
    # Fallback if no channel specified
    print("PIPER_RESULT_START")
    print(json.dumps(data))
    print("PIPER_RESULT_END")

def main():
  if len(sys.argv) < 2:
    write_result({"error": "No user script provided as argument"})
    sys.exit(1)

  user_script_path = sys.argv[1]
  module_name = "user_code"

  try:
    spec = importlib.util.spec_from_file_location(
        module_name, user_script_path
    )
    user_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(user_module)

    if not hasattr(user_module, "handler"):
      raise AttributeError(
          "The script must contain a 'handler(context)' function."
      )

    handler = user_module.handler
  except Exception as e:
    write_result({"error": f"Load Error: {str(e)}"})
    sys.exit(1)

  try:
    output = handler(context_data)
    write_result(output or {})
  except Exception as e:
    write_result({"error": str(e)})
    sys.exit(1)


if __name__ == "__main__":
  main()