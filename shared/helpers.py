from typing import Any
import math
from datetime import datetime, timedelta

# shared/helpers.py

def int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

def bool(value):
    if isinstance(value, bool): return value
    return str(value).lower() in ("true", "1", "yes", "on")

def float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def upper(value: str) -> str:
    return str(value).upper()

def lower(value: str) -> str:
    return str(value).lower()

def capitalize(value: str) -> str:
    return str(value).capitalize()

def trim(value: str) -> str:
    return str(value).strip()

def length(value: Any) -> int:
    return len(value)

def split(value: str, map_to, delimiter: str = ",") -> list:
    return str(value).split(delimiter)

def replace(value: str, search: str, replacement: str) -> str:
    return str(value).replace(search, replacement)

def substring(value: str, start: int, end: int = None) -> str:
    return str(value)[start:end]

def contains(value: str, search: str) -> bool:
    return search in str(value)

def sum(*args) -> float:
    return sum([float(arg) for arg in args if arg is not None])

def round(value: float, precision: int = 0) -> float:
    return round(float(value), precision)

def ceil(value: float) -> int:
    return math.ceil(float(value))

def floor(value: float) -> int:
    return math.floor(float(value))

def toInt(value: Any) -> int:
    try:
        return int(float(value))
    except:
        return 0
    
def first(value: list) -> Any:
    return value[0] if value else None

def last(value: list) -> Any:
    return value[-1] if value else None

def join(value: list, separator: str = ", ") -> str:
    return separator.join([str(v) for v in value])

def flatten(value: list) -> list:
    result = []
    for item in value:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result

def now() -> str:
    return datetime.now().isoformat()

def formatDate(value: str, format_str: str) -> str:
    # Basic implementation: converts ISO string to custom format
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt.strftime(format_str)

def addDays(value: str, days: int) -> str:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (dt + timedelta(days=days)).isoformat()