"""
stretis.transpiler.cli
=======================

The command-line entry point tying converter.py + manifest.json +
batch_transpile_manifest.py + rebuild_index.py into one tool, per the
"local-bundled default, explicit opt-in refresh, never automatic" design
decided on earlier — see manifest resolution below for exactly what that
means in code, not just in principle.

Manifest resolution precedence (highest wins), resolved once per run and
ALWAYS printed, so it's never ambiguous which manifest a given run used:

  1. --manifest PATH        (explicit override — for testing, forks, CI)
  2. ~/.stretis/manifest.json  (written ONLY by `stretis manifest
                                update` — never anything else, never
                                automatically)
  3. the bundled copy shipped inside this package itself

The bundled copy is NEVER overwritten by anything in this tool. Updating
always writes to the user's own ~/.stretis/ directory, so re-installing
or upgrading stretis-transpiler can't silently wipe out a refresh someone
pulled, and a corrupt/bad manual update can always be undone by deleting
one file to fall back to the pinned, known-good bundled default.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from importlib import resources

from . import converter
from . import smoke_test
from .batch_transpile_manifest import run_manifest
from .rebuild_index import rebuild_index
from .diff_catalog import diff_catalogs, render_report

USER_MANIFEST_PATH = os.path.expanduser("~/.stretis/manifest.json")

# Mirrors USER_MANIFEST_PATH: patches are fetched ONLY by `stretis patches
# update`, never automatically, and never bundled inside the package itself
# (unlike manifest.json's bundled-default tier — patches are inherently a
# living, community-contributed thing with no "pinned known-good snapshot"
# to ship, so there's no bundled fallback tier for them the way there is
# for the manifest).
USER_PATCHES_DIR = os.path.expanduser("~/.stretis/patches")

# Placeholder — point this at wherever the project's own repo actually
# lives (patches live under connectors/ in the SAME repo as the code,
# not a separate patches-only repo — see fetch_patches_from_repo's
# docstring in converter.py for the connectors/<category>/<app>/
# {patches,community/patches} layout this fetches). Same reasoning as
# DEFAULT_MANIFEST_UPDATE_URL: hardcoded and reviewable, not auto-resolved.
DEFAULT_PATCHES_REPO = "stretis/universal-api-registry"

# Placeholder — point this at wherever you publish the canonical,
# community-maintained manifest.json once that repo exists. Deliberately
# NOT auto-resolved from PyPI metadata or anything dynamic: a hardcoded,
# reviewable URL is the whole point of "explicit, not automatic."
DEFAULT_MANIFEST_UPDATE_URL = (
    "https://raw.githubusercontent.com/stretis/universal-api-registry/main/transpiler/src/stretis/piper_transpiler/manifest.json"
)


def resolve_manifest_path(explicit_path: str | None) -> str:
    if explicit_path:
        print(f"📋 Using manifest: {explicit_path} (explicit --manifest)")
        return explicit_path

    if os.path.isfile(USER_MANIFEST_PATH):
        print(f"📋 Using manifest: {USER_MANIFEST_PATH} (fetched via `manifest update`)")
        return USER_MANIFEST_PATH

    print("📋 Using manifest: bundled default (run `stretis manifest update` to refresh)")
    # Bundled package data — resources.files() works whether this package
    # was installed as a real wheel or is being run from source (editable
    # install), unlike a hardcoded __file__-relative path that would break
    # depending on how the package ended up laid out on disk.
    bundled = resources.files("stretis.piper_transpiler").joinpath("manifest.json")
    # transpile_full etc. below all expect a plain path string, not an
    # importlib.resources Traversable — as_file() gives a real filesystem
    # path (extracting to a temp location if this ever ships from inside
    # a zipped wheel, though that's not how it's packaged today).
    with resources.as_file(bundled) as p:
        return str(p)


def run_smoke_tests_for_apps(schemas_root: str, apps: list[tuple[str, str]]) -> dict:
    """
    Runs smoke_test.run_smoke_test() against every GET-method endpoint
    schema for the given (category, app) pairs. Non-GET schemas are
    skipped by run_smoke_test() itself (SAFE_METHODS enforcement) — this
    function doesn't pre-filter, it relies on that enforcement rather
    than duplicating it, so there's exactly one place the safety rule lives.
    """
    findings = {}
    total = len(apps)
    for i, (category, app) in enumerate(apps, 1):
        app_dir = os.path.join(schemas_root, category, app)
        if not os.path.isdir(app_dir):
            continue
        endpoint_files = [
            f for f in sorted(os.listdir(app_dir))
            if f not in ("_meta.json", "_index.json") and f.endswith(".json")
        ]
        print(f"🔬 [{i}/{total}] Smoke testing {app} ({len(endpoint_files)} schema file(s))...")
        app_findings = []
        for j, fname in enumerate(endpoint_files, 1):
            with open(os.path.join(app_dir, fname), "r", encoding="utf-8") as f:
                schema = json.load(f)
            result = smoke_test.run_smoke_test(schema)
            if result.verdict == smoke_test.SKIPPED:
                continue
            app_findings.append((fname[:-len(".json")], result))
            # One line per endpoint that actually made a network call — this
            # loop is where the silent multi-minute stretch came from before
            # (each of possibly dozens of GET endpoints, each up to 3 retries
            # with real backoff sleeps, printing nothing until the whole app
            # finished). A dot-per-attempt would be noisier than useful once
            # retries are involved (see run_smoke_test's own progress prints
            # below), so this prints once per endpoint's FINAL verdict instead.
            icon = {"HEALTHY": "✅", "NEEDS_TUNING": "🟡", "BROKEN": "🔴", "INCONCLUSIVE": "⚪"}.get(result.verdict, "❔")
            print(f"   {icon} [{j}/{len(endpoint_files)}] {fname[:-len('.json')]}: {result.verdict}")
        if app_findings:
            findings[(category, app)] = app_findings
    return findings


def resolve_patches_root(patch_enabled: bool, explicit_dir: str | None) -> str | None:
    """
    Same "resolved once, always printed" shape as resolve_manifest_path,
    but two tiers instead of three (no bundled default — see
    USER_PATCHES_DIR's comment) and gated on --patch/--patches-dir being
    requested at all, since applying patches is opt-in, not automatic.

    --patches-dir alone implies patches are wanted, same as passing a
    concrete value to --manifest doesn't need a separate flag to "turn
    manifest resolution on" — if you handed us a directory, you want it
    used.
    """
    if not patch_enabled and not explicit_dir:
        return None

    if explicit_dir:
        print(f"🩹 Using patches: {explicit_dir} (explicit --patches-dir)")
        return explicit_dir

    if os.path.isdir(USER_PATCHES_DIR):
        print(f"🩹 Using patches: {USER_PATCHES_DIR} (fetched via `stretis patches update`)")
        return USER_PATCHES_DIR

    print(
        "🩹 --patch was set but no patches found — run `stretis patches update` first. "
        "Transpiling without patches for now."
    )
    return None


def cmd_transpile(args: argparse.Namespace) -> int:
    manifest_path = resolve_manifest_path(args.manifest)
    only_apps = args.apps or None
    patches_root = resolve_patches_root(args.patch, args.patches_dir)

    if args.check_drift and os.path.isdir(args.output_dir):
        # Transpile into a scratch directory first, diff against what's
        # already there, and only overwrite the real output if nothing
        # breaking turned up (or the user forced it) — this is
        # diff_catalog.py from earlier, wired in as an actual safety gate
        # instead of a report nobody's forced to look at.
        with tempfile.TemporaryDirectory() as scratch:
            manifest_results = run_manifest(manifest_path, base_output_dir=scratch, only_apps=only_apps, patches_root=patches_root)
            rebuild_index(scratch)

            # Which (category, app) pairs did THIS run actually touch?
            # Everything else in args.output_dir must stay completely out
            # of both the diff and the apply step below. Without this, a
            # scoped run (e.g. `stretis transpile asana`) diffs scratch
            # (containing ONLY asana) against the FULL existing catalog —
            # every OTHER previously-transpiled app looks wholesale
            # removed, since it's genuinely absent from scratch. Confirmed
            # in production: this reported hundreds of unrelated Microsoft
            # Graph files as "removed entirely" from an `asana`-only run.
            # Worse, the old apply step (rmtree + copytree of the WHOLE
            # output_dir) would have actually DELETED every app except
            # asana from the real catalog on --force. This is a data-loss
            # fix, not a cosmetic one.
            touched = {
                (summary.category, app_key)
                for app_key, summary in manifest_results.items()
                if summary.category and not summary.file_errors
            }

            per_app, removed_apps, added_apps = diff_catalogs(args.output_dir, scratch, scope=touched)
            report, any_breaking = render_report(per_app, removed_apps, added_apps, full_detail=args.full_detail)
            print("\n" + report)

            if args.smoke_test:
                # Smoke testing ONLY runs on apps the structural diff
                # already considers clean (no changes at all) — that's
                # deliberate, not a limitation to fix later. A structural
                # BREAKING/NOTABLE verdict is already actionable on its
                # own; what smoke testing adds is catching the case
                # structural diffing is fundamentally blind to: the spec
                # TEXT didn't change, but the live API no longer matches
                # what's already committed. Running it on apps that
                # already have a structural verdict would only risk a
                # false-green smoke result quietly undermining a real
                # BREAKING finding — see smoke_test.py's module docstring.
                #
                # 🛠️ FIX: was derived from per_app's own keys, which only
                # exist for apps diff_catalogs found SOME difference in
                # (even a cosmetic one) — an app with ZERO changes at all
                # never gets a per_app entry, so it would never have
                # qualified as "unchanged" and silently never got smoke
                # tested. Deriving from `touched` (this run's real scope)
                # minus anything with an actual change fixes both that and
                # keeps this correctly scoped to only what was run.
                unchanged_apps = sorted(
                    pair for pair in touched
                    if pair not in per_app or not per_app[pair]["changes"]
                )
                smoke_findings = run_smoke_tests_for_apps(scratch, unchanged_apps)
                actionable = []
                inconclusive_count = 0
                healthy_count = 0
                for (cat, app), findings in smoke_findings.items():
                    for schema_name, result in findings:
                        if result.verdict in (smoke_test.BROKEN, smoke_test.NEEDS_TUNING):
                            actionable.append((cat, app, schema_name, result))
                        elif result.verdict == smoke_test.INCONCLUSIVE:
                            inconclusive_count += 1
                        elif result.verdict == smoke_test.HEALTHY:
                            healthy_count += 1

                if actionable:
                    print("\n## 🔍 Live smoke-test findings (apps with no spec-text changes)")
                    for cat, app, schema_name, result in actionable:
                        any_breaking = any_breaking or result.verdict == smoke_test.BROKEN
                        icon = "🔴" if result.verdict == smoke_test.BROKEN else "🟡"
                        print(f"- {icon} {app}/{schema_name}: {result.verdict} — {result.reason}")
                if inconclusive_count:
                    print(f"\n(smoke test: {inconclusive_count} endpoint(s) inconclusive — "
                          f"network/rate-limit issues, not evidence of a break)")
                # 🛠️ FIX: this used to fire whenever there was nothing
                # actionable/inconclusive — INCLUDING when dozens of GET
                # endpoints were actually tested and came back HEALTHY,
                # which printed "nothing to check" directly underneath a
                # console full of ✅ HEALTHY lines proving the opposite.
                # healthy_count now distinguishes "genuinely tested nothing"
                # from "tested plenty, all clean."
                if not actionable and not inconclusive_count:
                    if healthy_count:
                        print(f"\n(smoke test: {healthy_count} GET endpoint(s) checked live against "
                              f"{', '.join(sorted({a for _, a in unchanged_apps}))} — all healthy)")
                    else:
                        print("\n(smoke test: nothing to check — every unchanged app was empty, or all endpoints were non-GET)")

            if any_breaking and not args.force:
                print(
                    "\n🔴 Breaking changes detected — NOT applying. "
                    "Review the report above, then re-run with --force to apply anyway."
                )
                return 1

            # 🛠️ FIX: was `shutil.rmtree(args.output_dir)` + wholesale
            # `shutil.copytree(scratch, args.output_dir)` — scratch only
            # ever contains the app(s) THIS run touched, so a scoped run
            # (e.g. `stretis transpile asana --check-drift --force`) would
            # have deleted every OTHER previously-transpiled app from the
            # real catalog, not just updated asana. Confirmed against the
            # production report that surfaced this: hundreds of unrelated
            # Microsoft Graph files showing as removed from an asana-only
            # run — those weren't false positives, --force would have
            # actually erased them. Now only the specific (category, app)
            # folders in `touched` are replaced; everything else in
            # args.output_dir is never touched, deleted, or read.
            for category, app in sorted(touched):
                dest = os.path.join(args.output_dir, category, app)
                src = os.path.join(scratch, category, app)
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                if os.path.isdir(src):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copytree(src, dest)
            # Rebuilt against the REAL merged output_dir, not scratch —
            # scratch's own index.json (from rebuild_index(scratch) above,
            # which only exists to drive the diff/smoke-test steps) only
            # knows about this run's scoped apps and must never be copied
            # over the master index for the whole catalog.
            rebuild_index(args.output_dir)
            print(f"\n✅ Applied {len(touched)} app(s) to {args.output_dir}: {', '.join(a for _, a in sorted(touched))}")
        return 0

    run_manifest(manifest_path, base_output_dir=args.output_dir, only_apps=only_apps, patches_root=patches_root)
    rebuild_index(args.output_dir)
    return 0


def cmd_manifest_show(args: argparse.Namespace) -> int:
    path = resolve_manifest_path(None)
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    print(f"\n{len(manifest)} app(s): {', '.join(sorted(manifest))}")
    return 0


def cmd_manifest_update(args: argparse.Namespace) -> int:
    url = args.url or DEFAULT_MANIFEST_UPDATE_URL
    print(f"⬇️  Fetching {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"❌ Fetch failed: {e}")
        return 1

    try:
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("manifest.json must be a JSON object keyed by app name")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"❌ Fetched content isn't a valid manifest — NOT overwriting your existing one: {e}")
        return 1

    os.makedirs(os.path.dirname(USER_MANIFEST_PATH), exist_ok=True)
    with open(USER_MANIFEST_PATH, "wb") as f:
        f.write(data)
    print(f"✅ Wrote {len(parsed)} app(s) to {USER_MANIFEST_PATH}")
    print("   (the bundled default this package ships with is untouched)")
    return 0


def cmd_manifest_reset(args: argparse.Namespace) -> int:
    """Deletes the user's fetched manifest, falling back to the bundled default again."""
    if os.path.isfile(USER_MANIFEST_PATH):
        os.remove(USER_MANIFEST_PATH)
        print(f"✅ Removed {USER_MANIFEST_PATH} — back to the bundled default manifest.")
    else:
        print("Nothing to reset — already using the bundled default manifest.")
    return 0


def cmd_patches_show(args: argparse.Namespace) -> int:
    """Lists every locally-fetched patch, grouped by app and tier, so you
    can see what would actually apply — and which one wins — before
    running `transpile --patch` for real."""
    if not os.path.isdir(USER_PATCHES_DIR):
        print(f"No patches directory at {USER_PATCHES_DIR} — run `stretis patches update` first.")
        return 0

    # Mirrors converter._load_patch()'s own resolution exactly: official
    # at <category>/<app>/patches/, community at
    # <category>/<app>/community/patches/. Listed separately per app (not
    # merged into one combined list) so it's visible at a glance which
    # entries are shadowed — a schema_name present in BOTH tiers still
    # only ever resolves to the official one at transpile time.
    by_app = {}
    for category in sorted(os.listdir(USER_PATCHES_DIR)):
        cat_dir = os.path.join(USER_PATCHES_DIR, category)
        if not os.path.isdir(cat_dir):
            continue
        for app in sorted(os.listdir(cat_dir)):
            app_dir = os.path.join(cat_dir, app)
            if not os.path.isdir(app_dir):
                continue

            official_dir = os.path.join(app_dir, "patches")
            official = sorted(
                f[:-len(".json")] for f in os.listdir(official_dir) if f.endswith(".json")
            ) if os.path.isdir(official_dir) else []

            community_dir = os.path.join(app_dir, "community", "patches")
            community = sorted(
                f[:-len(".json")] for f in os.listdir(community_dir) if f.endswith(".json")
            ) if os.path.isdir(community_dir) else []

            if official or community:
                by_app[f"{category}/{app}"] = (official, community)

    if not by_app:
        print(f"{USER_PATCHES_DIR} exists but has no patch files in it.")
        return 0

    total = sum(len(o) + len(c) for o, c in by_app.values())
    print(f"\n{total} patch(es) across {len(by_app)} app(s) in {USER_PATCHES_DIR}:")
    for app_path, (official, community) in sorted(by_app.items()):
        print(f"  {app_path}:")
        if official:
            print(f"    official:  {', '.join(official)}")
        if community:
            shadowed = set(community) & set(official)
            note = f"  (shadowed by official: {', '.join(sorted(shadowed))})" if shadowed else ""
            print(f"    community: {', '.join(community)}{note}")
    return 0


def cmd_patches_update(args: argparse.Namespace) -> int:
    repo = args.repo or DEFAULT_PATCHES_REPO
    print(
        f"⬇️  Fetching {repo}@{args.ref} — {USER_PATCHES_DIR} will be wiped "
        "and rebuilt to exactly mirror the repo. Keep any hand-authored "
        "patch of your own in a separate directory and pass it via "
        "--patches-dir instead — this directory is fetched content only."
    )
    try:
        result = converter.fetch_patches_from_repo(
            repo=repo, ref=args.ref, dest_dir=USER_PATCHES_DIR,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"❌ Fetch failed: {e}")
        return 1
    return 1 if result["failed"] else 0


def cmd_patches_reset(args: argparse.Namespace) -> int:
    """Deletes every locally-fetched patch, falling back to no patches at all."""
    if os.path.isdir(USER_PATCHES_DIR):
        shutil.rmtree(USER_PATCHES_DIR)
        print(f"✅ Removed {USER_PATCHES_DIR} — `--patch` will find nothing to apply until you run `stretis patches update` again.")
    else:
        print("Nothing to reset — no patches directory exists.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stretis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_transpile = sub.add_parser("transpile", help="Transpile apps from the manifest into schema files")
    p_transpile.add_argument("apps", nargs="*", help="Specific app keys to transpile (default: every app in the manifest)")
    p_transpile.add_argument("--output-dir", default="./schemas", help="Where to write the schema catalog")
    p_transpile.add_argument("--manifest", default=None, help="Explicit manifest.json path (overrides resolution precedence)")
    p_transpile.add_argument("--check-drift", action="store_true",
                              help="Transpile to a scratch dir first, diff against --output-dir, and refuse to apply breaking changes without --force")
    p_transpile.add_argument("--force", action="store_true", help="With --check-drift: apply even if breaking changes were found")
    p_transpile.add_argument("--smoke-test", action="store_true",
                              help="With --check-drift: fire live GET requests (fake credentials, GET-only) against apps with "
                                   "no spec-text changes, to catch live drift the structural diff can't see. Opt-in — never fires by default.")
    p_transpile.add_argument("--full-detail", action="store_true",
                              help="Itemize every changed line in the drift report even for apps with huge change counts "
                                   "(default: collapse anything over 20 lines per app into a summary)")
    p_transpile.add_argument("--patch", action="store_true",
                              help="Apply patches on top of the transpiled output for any endpoint that has one. "
                                   "Opt-in — never applied by default, same as --smoke-test. Patches come from "
                                   "--patches-dir, or ~/.stretis/patches if you've run `stretis patches update`.")
    p_transpile.add_argument("--patches-dir", default=None,
                              help="Explicit local patches directory (overrides ~/.stretis/patches). Implies --patch.")
    p_transpile.set_defaults(func=cmd_transpile)

    p_manifest = sub.add_parser("manifest", help="Inspect or refresh the manifest")
    manifest_sub = p_manifest.add_subparsers(dest="manifest_command", required=True)

    p_show = manifest_sub.add_parser("show", help="Print which manifest is currently active and what's in it")
    p_show.set_defaults(func=cmd_manifest_show)

    p_update = manifest_sub.add_parser("update", help="Fetch the latest manifest into ~/.stretis/manifest.json (explicit, never automatic)")
    p_update.add_argument("--url", default=None, help=f"Override the default source (default: {DEFAULT_MANIFEST_UPDATE_URL})")
    p_update.set_defaults(func=cmd_manifest_update)

    p_reset = manifest_sub.add_parser("reset", help="Discard your fetched manifest and fall back to the bundled default")
    p_reset.set_defaults(func=cmd_manifest_reset)

    p_patches = sub.add_parser("patches", help="Inspect or refresh community/local patches")
    patches_sub = p_patches.add_subparsers(dest="patches_command", required=True)

    p_patches_show = patches_sub.add_parser("show", help="List every locally-fetched patch, grouped by app")
    p_patches_show.set_defaults(func=cmd_patches_show)

    p_patches_update = patches_sub.add_parser("update", help="Fetch patches into ~/.stretis/patches (explicit, never automatic)")
    p_patches_update.add_argument("--repo", default=None, help=f"owner/name of the patches repo (default: {DEFAULT_PATCHES_REPO})")
    p_patches_update.add_argument("--ref", default="main", help="Branch/tag/commit to fetch from (default: main)")
    p_patches_update.set_defaults(func=cmd_patches_update)

    p_patches_reset = patches_sub.add_parser("reset", help="Delete every locally-fetched patch")
    p_patches_reset.set_defaults(func=cmd_patches_reset)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())