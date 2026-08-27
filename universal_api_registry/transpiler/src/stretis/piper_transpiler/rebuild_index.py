"""
rebuild_index.py
-----------------
Walks base_output_dir/<category>/<app>/_index.json (written by
write_schema_index() in converter.py for every app, regardless of which
script produced it — batch-runner.py, apis_io_fetch.py, or a schema you
wrote by hand) and regenerates the master index.json batch-runner.py
normally writes at the end of a full run.

Use this after adding schemas from a source OTHER than a full
batch-runner.py run, so the master catalog reflects everything on disk
without re-fetching the ~2,300 APIs.guru providers you already have.
"""

import os
import json
import argparse

from .converter import _now_iso


def rebuild_index(base_output_dir):
    apps = []

    if not os.path.isdir(base_output_dir):
        raise FileNotFoundError(f"{base_output_dir} does not exist")

    for category in sorted(os.listdir(base_output_dir)):
        cat_dir = os.path.join(base_output_dir, category)
        if not os.path.isdir(cat_dir):
            continue

        for app_name in sorted(os.listdir(cat_dir)):
            app_dir = os.path.join(cat_dir, app_name)
            index_path = os.path.join(app_dir, "_index.json")
            meta_path = os.path.join(app_dir, "_meta.json")

            if not os.path.isfile(index_path):
                continue  # not a transpiled app folder (or an incomplete/corrupt one) — skip

            with open(index_path, "r", encoding="utf-8") as f:
                app_index = json.load(f)

            meta = {}
            if os.path.isfile(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

            all_names = app_index.get("schemas", [])
            auth_name = next((s for s in all_names if s == f"{app_name}_auth"), None)
            endpoint_names = [s for s in all_names if s != auth_name]

            apps.append(
                {
                    "app_name": app_name,
                    "category": category,
                    "target_dir": app_dir,
                    "endpoints": len(endpoint_names),
                    "schemas": endpoint_names,
                    "has_oauth": auth_name is not None,
                    "auth_schema_name": auth_name,
                    "has_favicon": bool(meta.get("favicon_local_path")),
                    "stage_errors": {},  # not recoverable after the fact — only known at transpile time
                    "last_updated": app_index.get("generated_at") or meta.get("last_updated"),
                }
            )

    index = {
        "generated_at": _now_iso(),
        "total_apps": len(apps),
        "total_errors": 0,  # rebuilt from disk state, not a live run — errors aren't visible here
        "apps": apps,
        "partial_apps": 0,
        "all_schemas": sorted(
            f"{a['app_name']}/{name}"
            for a in apps
            for name in (a["schemas"] + ([a["auth_schema_name"]] if a["auth_schema_name"] else []))
        ),
    }

    out_path = os.path.join(base_output_dir, "index.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=4)

    print(f"🗂️  Rebuilt index: {len(apps)} apps -> {out_path}")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="../schemas")
    args = parser.parse_args()
    rebuild_index(args.output_dir)