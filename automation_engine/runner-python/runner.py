import importlib.util
import json
import os
import sys

# Load configuration from environment
context_data = json.loads(os.getenv("PIPER_CONTEXT", "{}"))


def write_result(data):
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