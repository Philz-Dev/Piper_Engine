"""
diff_catalog.py
----------------
Compares two schema catalog snapshots (e.g. the currently-committed
schemas/ tree vs. a freshly re-transpiled one) and classifies every
difference as BREAKING, NOTABLE, or COSMETIC — rather than a raw git
diff, which is noisy at the JSON level (key reordering, a timestamp
bump) and gives zero signal about whether anything a real workflow
depends on actually changed.

Why diff OUTPUT instead of every upstream source individually: a raw
OpenAPI spec, a multi-file GitHub repo (Twilio/PayPal-style), and
HubSpot's custom discovery-index format all change in completely
different ways, at completely different byte layouts. Every one of them
already gets normalized into the SAME schema shape by converter.py —
so this only needs to understand ONE shape, not four.

Usage:
    python diff_catalog.py --old ./schemas_before --new ./schemas_after --out report.md

Exit code is 1 if any BREAKING change was found (for CI: fail the
build / block auto-merge / require human review), 0 otherwise.
"""

import argparse
import json
import os
import sys
from collections import defaultdict

BREAKING = "BREAKING"
NOTABLE = "NOTABLE"
COSMETIC = "COSMETIC"

# Keys whose changes never affect what a built request looks like —
# reported in a rollup count only, never itemized, so they don't bury
# real signal under noise.
COSMETIC_METADATA_KEYS = {
    "display_name", "description", "icon_url", "color",
    "last_updated", "node_type_confidence",
}

# Above this many changed lines for ONE app, stop itemizing every line and
# collapse to a summary instead. Written for a real case: Microsoft Graph's
# operationIds aren't byte-stable across separate publishes of the same
# spec version (Microsoft's own generator re-derives disambiguation
# suffixes like _a89e for type-cast overloads), so a huge multi-thousand-
# endpoint app can show hundreds of individually-real "removed"/"added"
# lines for what's functionally the same set of endpoints under slightly
# different names. Each line is technically accurate (the diff mechanism
# itself isn't wrong) but a wall of hundreds of bullets for one app is
# unreadable and buries any OTHER app's genuine breaking change in the
# same report. This does NOT change severity classification or the exit
# code — only how much detail prints inline by default.
ITEMIZE_LIMIT_PER_APP = 20


def _walk_catalog(root, scope=None):
    """
    Returns {(category, app, schema_filename): full_path} for every
    endpoint/auth schema file under root — deliberately EXCLUDES
    _meta.json and _index.json, which are catalog bookkeeping, not
    request-shape data; a favicon re-fetch shouldn't register as drift.

    scope: optional set of (category, app) pairs to restrict to. Without
    this, comparing a SCOPED run's output (e.g. only "asana" was
    transpiled into a scratch dir) against the FULL existing catalog
    makes every OTHER app look wholesale removed, since they're
    genuinely absent from the scratch side — a real bug found in
    production use (`stretis transpile asana --check-drift` reporting
    hundreds of unrelated Microsoft Graph files as "removed entirely").
    Passing the same scope on both the old and new walk is what makes a
    single-app run's diff only ever concern that app.
    """
    out = {}
    if not os.path.isdir(root):
        return out
    for category in os.listdir(root):
        cat_dir = os.path.join(root, category)
        if not os.path.isdir(cat_dir):
            continue
        for app in os.listdir(cat_dir):
            if scope is not None and (category, app) not in scope:
                continue
            app_dir = os.path.join(cat_dir, app)
            if not os.path.isdir(app_dir):
                continue
            for fname in os.listdir(app_dir):
                if fname in ("_meta.json", "_index.json") or not fname.endswith(".json"):
                    continue
                out[(category, app, fname)] = os.path.join(app_dir, fname)
    return out


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _diff_field_map(old_fields, new_fields, old_meta_fields, new_meta_fields, section_label, changes):
    """Compares one flat {field_name: '{{DataType=..}}'} map (class or body's
    top-level placeholder values, NOT the metadata.fields description
    block) — the actual request shape, which is what breaks a stored
    workflow if it changes. old_meta_fields/new_meta_fields (metadata.
    fields.<class|body>) are passed in so a newly-added field's severity
    can be decided correctly in ONE place — a field that's new AND
    required is BREAKING, not "NOTABLE, plus a separate BREAKING line
    from somewhere else" (that duplicate was an actual bug caught by
    testing against real drift, not a hypothetical)."""
    old_keys, new_keys = set(old_fields or {}), set(new_fields or {})
    new_meta_fields = new_meta_fields or {}

    for removed in sorted(old_keys - new_keys):
        changes.append((BREAKING, f"{section_label}.{removed}", "field removed"))

    for added in sorted(new_keys - old_keys):
        is_required = (new_meta_fields.get(added) or {}).get("required", False)
        if is_required:
            changes.append((BREAKING, f"{section_label}.{added}",
                             "field added AND required — existing calls will now fail validation"))
        else:
            changes.append((NOTABLE, f"{section_label}.{added}", "field added"))

    for common in sorted(old_keys & new_keys):
        old_val, new_val = old_fields[common], new_fields[common]
        if old_val == new_val:
            continue
        old_type = _extract_datatype(old_val)
        new_type = _extract_datatype(new_val)
        if old_type and new_type and old_type != new_type:
            changes.append((BREAKING, f"{section_label}.{common}",
                             f"type changed: {old_type} -> {new_type}"))
        else:
            changes.append((NOTABLE, f"{section_label}.{common}",
                             f"value changed: {old_val!r} -> {new_val!r}"))


def _extract_datatype(placeholder):
    if not isinstance(placeholder, str) or not placeholder.startswith("{{"):
        return None
    inner = placeholder.strip("{}")
    for part in inner.split(","):
        if "=" in part and part.strip().split("=")[0].strip().lower() == "datatype":
            return part.strip().split("=", 1)[1].strip()
    return None


def _diff_required_flags(old_meta_fields, new_meta_fields, section_label, changes):
    """Only for fields present in BOTH versions — an existing field
    flipping optional<->required. A newly-added field's required-ness
    is decided inside _diff_field_map instead (see its docstring for
    why splitting this across two places produced a duplicate line)."""
    old_meta_fields = old_meta_fields or {}
    new_meta_fields = new_meta_fields or {}
    for key in sorted(set(old_meta_fields) & set(new_meta_fields)):
        old_req = (old_meta_fields.get(key) or {}).get("required", False)
        new_req = (new_meta_fields.get(key) or {}).get("required", False)
        if old_req != new_req:
            sev = BREAKING if new_req else NOTABLE
            changes.append((sev, f"{section_label}.{key}",
                             f"required flag: {old_req} -> {new_req}"))


def _diff_schema_file(old, new):
    changes = []

    if old.get("method") != new.get("method"):
        changes.append((BREAKING, "method", f"{old.get('method')} -> {new.get('method')}"))
    if old.get("url") != new.get("url"):
        changes.append((BREAKING, "url", f"{old.get('url')} -> {new.get('url')}"))

    old_meta, new_meta = old.get("metadata", {}), new.get("metadata", {})
    old_class_meta = (old_meta.get("fields") or {}).get("class")
    new_class_meta = (new_meta.get("fields") or {}).get("class")
    old_body_meta = (old_meta.get("fields") or {}).get("body")
    new_body_meta = (new_meta.get("fields") or {}).get("body")

    _diff_field_map(old.get("class"), new.get("class"), old_class_meta, new_class_meta, "class", changes)
    _diff_field_map(old.get("body", {}), new.get("body", {}), old_body_meta, new_body_meta, "body", changes)
    _diff_required_flags(old_class_meta, new_class_meta, "class", changes)
    _diff_required_flags(old_body_meta, new_body_meta, "body", changes)

    if old_meta.get("node_type") != new_meta.get("node_type"):
        changes.append((NOTABLE, "metadata.node_type",
                         f"{old_meta.get('node_type')} -> {new_meta.get('node_type')}"))

    cosmetic_count = sum(
        1 for k in COSMETIC_METADATA_KEYS
        if old_meta.get(k) != new_meta.get(k)
    )
    if old.get("headers") != new.get("headers"):
        # Header KEY changes (not just their placeholder values, already
        # caught by url/class diffs when auth-scheme-driven) matter —
        # e.g. an apiKey header name changing, or Authorization disappearing.
        old_h, new_h = set((old.get("headers") or {}).keys()), set((new.get("headers") or {}).keys())
        for removed in sorted(old_h - new_h):
            changes.append((BREAKING, f"headers.{removed}", "header removed"))
        for added in sorted(new_h - old_h):
            changes.append((NOTABLE, f"headers.{added}", "header added"))

    return changes, cosmetic_count


def diff_catalogs(old_root, new_root, scope=None):
    old_files = _walk_catalog(old_root, scope=scope)
    new_files = _walk_catalog(new_root, scope=scope)

    old_keys, new_keys = set(old_files), set(new_files)
    per_app = defaultdict(lambda: {"changes": [], "cosmetic_count": 0})

    for (category, app, fname) in sorted(old_keys - new_keys):
        per_app[(category, app)]["changes"].append(
            (BREAKING, fname, "endpoint/auth schema removed entirely")
        )

    for (category, app, fname) in sorted(new_keys - old_keys):
        per_app[(category, app)]["changes"].append(
            (NOTABLE, fname, "new endpoint/auth schema added")
        )

    for key in sorted(old_keys & new_keys):
        category, app, fname = key
        old = _load(old_files[key])
        new = _load(new_files[key])
        if old == new:
            continue
        changes, cosmetic_count = _diff_schema_file(old, new)
        bucket = per_app[(category, app)]
        bucket["cosmetic_count"] += cosmetic_count
        for sev, path, desc in changes:
            bucket["changes"].append((sev, f"{fname}:{path}", desc))

    # Apps that vanished/appeared entirely (not just one endpoint) — worth
    # its own top-level callout, since "HubSpot disappeared from the
    # catalog" is a very different event than "one HubSpot endpoint changed".
    old_apps = {(c, a) for (c, a, _) in old_keys}
    new_apps = {(c, a) for (c, a, _) in new_keys}
    removed_apps = sorted(old_apps - new_apps)
    added_apps = sorted(new_apps - old_apps)

    return per_app, removed_apps, added_apps


def render_report(per_app, removed_apps, added_apps, full_detail=False):
    lines = ["# Catalog drift report", ""]
    any_breaking = False

    if removed_apps:
        any_breaking = True
        lines.append("## 🔴 Apps removed entirely")
        for cat, app in removed_apps:
            lines.append(f"- **{app}** ({cat})")
        lines.append("")

    if added_apps:
        lines.append("## 🟢 Apps added entirely")
        for cat, app in added_apps:
            lines.append(f"- **{app}** ({cat})")
        lines.append("")

    apps_with_changes = {k: v for k, v in per_app.items() if v["changes"] or v["cosmetic_count"]}
    if not apps_with_changes and not removed_apps and not added_apps:
        lines.append("No drift detected.")
        return "\n".join(lines), False

    for (category, app), bucket in sorted(apps_with_changes.items()):
        breaking = [c for c in bucket["changes"] if c[0] == BREAKING]
        notable = [c for c in bucket["changes"] if c[0] == NOTABLE]
        if breaking:
            any_breaking = True

        if not breaking and not notable:
            continue  # pure cosmetic — only shows in the summary line

        header = f"## {'🔴' if breaking else '🟡'} {app} ({category})"
        lines.append(header)

        all_lines = breaking + notable
        if len(all_lines) > ITEMIZE_LIMIT_PER_APP and not full_detail:
            # Collapsed summary instead of a wall of bullets — counts by
            # (severity, description) so e.g. "312 endpoints removed" and
            # "298 endpoints added" show as two lines, not one blob, and a
            # genuinely mixed set of reasons still shows each reason's count.
            counts = defaultdict(int)
            for sev, _path, desc in all_lines:
                counts[(sev, desc)] += 1
            lines.append(
                f"- ⚠️ {len(all_lines)} changes ({len(breaking)} breaking, {len(notable)} notable) — "
                f"itemizing every line would be unreadable at this volume. Top reasons:"
            )
            for (sev, desc), count in sorted(counts.items(), key=lambda kv: -kv[1])[:5]:
                icon = "🔴" if sev == BREAKING else "🟡"
                lines.append(f"  - {icon} {desc}: {count}×")
            if len(counts) > 5:
                lines.append(f"  - ...and {len(counts) - 5} other reason(s)")
            lines.append(
                "  (run with --full-detail to itemize every line for this app, or check "
                "whether this many endpoints legitimately changed upstream at once — e.g. "
                "an auto-generated spec whose disambiguation suffixes aren't stable across "
                "publishes, not necessarily a real break)"
            )
        else:
            for sev, path, desc in all_lines:
                icon = "🔴" if sev == BREAKING else "🟡"
                lines.append(f"- {icon} `{path}`: {desc}")

        if bucket["cosmetic_count"]:
            lines.append(f"- ⚪ +{bucket['cosmetic_count']} cosmetic-only change(s) (display text, timestamps)")
        lines.append("")

    total_cosmetic_only = sum(
        1 for v in per_app.values()
        if not any(c[0] in (BREAKING, NOTABLE) for c in v["changes"]) and v["cosmetic_count"]
    )
    if total_cosmetic_only:
        lines.append(f"_{total_cosmetic_only} additional app(s) had cosmetic-only changes, not itemized above._")

    return "\n".join(lines), any_breaking


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, help="Path to the OLD schemas/ root (e.g. currently-committed)")
    parser.add_argument("--new", required=True, help="Path to the NEW schemas/ root (freshly re-transpiled)")
    parser.add_argument("--out", default=None, help="Write the Markdown report here (default: stdout)")
    parser.add_argument("--full-detail", action="store_true",
                         help="Itemize every changed line even for apps with huge change counts "
                              "(default: collapse anything over 20 lines per app into a summary)")
    args = parser.parse_args()

    per_app, removed_apps, added_apps = diff_catalogs(args.old, args.new)
    report, any_breaking = render_report(per_app, removed_apps, added_apps, full_detail=args.full_detail)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {args.out}")
    else:
        print(report)

    sys.exit(1 if any_breaking else 0)


if __name__ == "__main__":
    main()