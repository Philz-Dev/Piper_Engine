"""
shared/tools.py — public subset

This is a trimmed copy of the engine's internal shared/tools.py, containing
only what piper_sdk.py (build_schema / get_input_form) and validate_schema.py
actually import: the placeholder crawler, the required/missing diff, a small
multi-format file loader, and the placeholder-replacement function.

Left out on purpose: the internal-engine-only pieces (subregistry builders,
schema-registry version loader, service-key resolver, YAML-with-line-numbers
loader, etc.) that have nothing to do with filling in a schema and would
otherwise pull unrelated internal machinery into anyone's `pip install`.
"""

import json
import os
import re
from typing import Any, Dict, Union

import yaml

from .unpacked_data import UnZip

PLACEHOLDER_PATTERN = r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}"


def missing_field(required: Union[list, dict], content_to_check: Union[list, dict]):
    """
    Returns the set of keys present in `required` but absent from
    `content_to_check`. Both sides accept either a dict (its keys are used)
    or a plain iterable of keys.
    """
    content = required.keys() if isinstance(required, dict) else required
    cont_to_check = content_to_check.keys() if isinstance(content_to_check, dict) else content_to_check
    return set(content) - set(cont_to_check)


def crawler(content_to_crawl: dict, patterns: Union[list, str], is_regex: bool = True):
    """
    Walks content_to_crawl (typically a whole schema dict, including
    nested 'class'/'body'/'headers' sections) and returns every leaf
    value matching any of `patterns`, keyed two ways:

      - matched_items: short key -> matched value. If the same leaf key
        name occurs more than once anywhere in the tree (e.g. a path
        param and an unrelated body field both named "id"), only the
        LAST occurrence found survives here.
      - key_value: full dotted path -> matched value. Path-unique, so
        replace_place_value_v3 can target one specific occurrence.

    KNOWN COLLISION: replace_place_value_v3 matches by the final path
    segment (the short key), not the full path — so a fill keyed "id"
    will overwrite every "id"-named leaf in the tree, not just the one
    matched_items happened to keep. Give class/body fields distinct
    names if this matters for a given schema.

    Uses re.search rather than re.fullmatch, so a pattern can match
    inside a larger string (e.g. a marker embedded in
    "Bearer {{ ... }}") rather than requiring the whole value to match.
    """
    matched_field: Dict[str, Any] = {}
    matched_key_value: Dict[str, Any] = {}
    unzip_app_schema = UnZip()
    unzip_app_schema.unpack_bulk_data(content_to_crawl)

    if isinstance(patterns, str):
        patterns = [patterns]

    for p in patterns:
        search_pattern = p if is_regex else re.escape(p)

        for key, value in unzip_app_schema.unpacked_key_value.items():
            if value is None:
                continue
            if re.search(search_pattern, str(value)):
                matched_key_value[key] = value

        for path, value in unzip_app_schema.key_path.items():
            if value is None:
                continue
            if re.search(search_pattern, str(value)):
                matched_field[path] = value

    package = {
        "matched_items": matched_key_value,
        "key_path": unzip_app_schema.key_path,
        "key_value": matched_field,
    }
    return package if matched_field else None


def retrieve_file(file_path, file_type: str = None, base_dir: bool = False):
    """
    Reads a schema/config file, auto-parsing by extension (.json/.yml/.yaml).
    Anything else is returned as raw text. Returns None if the path is empty
    or the file doesn't exist.
    """
    if not file_path:
        return None

    try:
        path_str = str(file_path)
        detected_type = path_str.split(".")[-1].lower()
    except (AttributeError, IndexError):
        return None

    services = {
        "yml": yaml.safe_load,
        "yaml": yaml.safe_load,
        "json": json.load,
    }

    if base_dir and not os.path.isabs(path_str):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, file_path)

    file_path = os.path.normpath(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            if detected_type in services:
                return services[detected_type](f)
            return f.read()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"❌ [System] Error reading {file_path}: {e}")
        return None


def replace_place_value_v3(key_path, value, key, content_to_modify=None, is_metadata_replacement=False):
    """
    Overwrites every leaf in content_to_modify whose full dotted path (a key
    in key_path) ends in `key`, with `value`. See the collision note on
    crawler() above — this is where that collision actually happens, since
    matching is by final path segment only.
    """
    for k in key_path:
        split_key = k.split(".")

        if split_key[-1] == key:
            temp = content_to_modify
            for ky in split_key[:-1]:
                if ky.isdigit():
                    ky = int(ky)
                temp = temp[ky]

            final_key = split_key[-1]
            current_val = temp[final_key]

            if is_metadata_replacement and isinstance(current_val, str) and "{{" in current_val:
                if isinstance(value, str) and "{{" in value:
                    clean_val = str(value).replace("{{", "").replace("}}", "").strip()
                    pattern = r"\{\{.*?\}\}"
                    replacement = f"{{{{{clean_val}}}}}"
                    temp[final_key] = re.sub(pattern, replacement, current_val, flags=re.DOTALL)
                else:
                    temp[final_key] = value
            else:
                temp[final_key] = value

    return content_to_modify