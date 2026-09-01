from simpleeval import SimpleEval
from typing import Dict

class ExpressionEngine:
    def __init__(self, context_env: Dict):
        self.evaluator = SimpleEval()
        # Bind the context variables so expressions like 'country == "US"' work
        self.evaluator.names = context_env
        self.evaluator.disallow_operators = [] 

    def evaluate(self, expression: str):
        try:
            return self.evaluator.eval(expression)
        except Exception as e:
            print(f"❌ Evaluation error in [{expression}]: {e}")
            return None