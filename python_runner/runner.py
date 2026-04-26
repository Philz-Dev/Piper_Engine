import sys
import json
import importlib.util
import os

def main():
    # 1. Get the filename from args (e.g., python bootstrap.py custom_script_123.py)
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No user script provided as argument"}))
        sys.exit(1)

    user_script_path = sys.argv[1] # e.g., "custom_script_123.py"
    module_name = "user_code" # Logical name for the import

    # 2. Dynamic Import Logic
    try:
        spec = importlib.util.spec_from_file_location(module_name, user_script_path)
        user_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(user_module)
        
        if not hasattr(user_module, 'handler'):
            raise AttributeError("The script must contain a 'handler(context)' function.")
            
        handler = user_module.handler
    except Exception as e:
        print(json.dumps({"error": f"Load Error: {str(e)}"}))
        sys.exit(1)

    # 3. Receive Context from Stdin
    try:
        input_data = sys.stdin.read()
        context = json.loads(input_data) if input_data else {}
    except Exception as e:
        context = {}

    # 4. Execute and Return
    try:
        output = handler(context)
        
        # Using the Marker Strategy
        print("PIPER_RESULT_START")
        print(json.dumps(output))
        print("PIPER_RESULT_END")
        
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()