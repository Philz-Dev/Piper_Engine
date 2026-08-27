"""
batch_transpile_manifest.py
============================

Drives converter.py against manifest.json, correctly handling BOTH
single-spec apps (Stripe, GitHub, OpenAI) and multi-spec apps whose
endpoints are scattered across several files (Twilio, PayPal — and,
with more caution, HubSpot).

This replaces an earlier sketch of a "master orchestrator loop" that
looked plausible but had three real bugs, confirmed against converter.py
itself and against the actual vendor repos:

  1. `json.load(f.read())` — passes a STRING into json.load(), which
     requires a file object. Raises AttributeError immediately; never ran.

  2. Reusing one ctx (from get_app_context() on the FIRST file) for every
     subsequent file in a multi-file app. ctx['base_url'] is exactly what
     transpile_endpoints() stamps onto every operation's URL — and
     Twilio's own docs confirm each of its ~30 spec files targets a
     DIFFERENT subdomain (api.twilio.com, accounts.twilio.com,
     flex-api.twilio.com, ...). Reusing file #1's ctx would have silently
     sent every other file's endpoints to the wrong host.

  3. App identity (app_name/category/target_dir) comes from
     get_app_context(), which derives it from x-providerName/info.title
     INSIDE each spec file — not from the manifest key. Nothing
     guarantees every sub-file of one vendor shares identical title
     metadata; if they don't, each file would silently land in a
     different app folder instead of accumulating into one.

Fixes here: identity is pinned once from the MANIFEST KEY and reused;
base_url is re-extracted fresh from every individual file; metadata is
extracted once from a designated primary file; every per-file failure is
caught and reported without aborting the whole app's run.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import converter
from .google_discovery_adapter import discovery_doc_to_openapi_shape

DEFAULT_BRANCH = "main"


# ---------------------------------------------------------------------------
# Manifest entry shapes
# ---------------------------------------------------------------------------
#
# manifest.json as currently written has THREE distinct shapes buried in
# one flat structure, distinguished only by a human-readable "note" field:
#
#   a) a raw single-file URL                          -> single spec
#   b) a github.com repo root URL, no further info     -> needs discovery
#   c) same, but the repo's internal layout is risky   -> needs a curated
#      "files" list instead of blind discovery (see HUBSPOT_FILES below)
#
# Rather than guess (b) vs (c) at runtime, each multi-file app gets an
# explicit MultiFileSpec below saying exactly how to resolve it. This is
# more maintenance than "crawl everything automatically", but blind
# recursive crawling of HubSpot's repo would silently ingest duplicate
# specs from its numbered Rollouts/ staging folders (confirmed present at
# PublicApiSpecs/CRM/Products/Rollouts/424/v3/products.json) — a curated
# list is the honest fix, not a generic "walk and grab every .json".

@dataclass
class DiscoverConfig:
    """Auto-discover every spec file under one flat GitHub directory."""
    owner: str
    repo: str
    path: str  # e.g. "spec/json" — must be a FLAT directory (see HubSpot note)
    branch: str = DEFAULT_BRANCH
    extensions: tuple = (".json",)


@dataclass
class MultiFileSpec:
    owner: str
    repo: str
    branch: str = DEFAULT_BRANCH
    discover: Optional[DiscoverConfig] = None
    files: Optional[List[str]] = None  # explicit relative paths, curated by hand
    metadata_source: Optional[str] = None  # which file's info.* becomes _meta.json

    def raw_url(self, relative_path: str) -> str:
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{self.branch}/{relative_path}"


@dataclass
class IndexApiSpec:
    """
    A vendor-published JSON INDEX describing many separate spec files —
    structurally the same "many files -> one app folder" problem
    MultiFileSpec solves, but the file list isn't a fixed set of GitHub
    paths; it has to be fetched and interpreted first, and each entry
    needs its own best-version selection rather than every file being
    used unconditionally. Confirmed shape (HubSpot's
    https://api.hubspot.com/public/api/spec/v1/specs, per manifest.json's
    own "note" field from a real fetch): {"results": [{"name", "group",
    "versions": [{"stage", "openApi"}]}]} — one resource group per
    entry, each with its own version history and its own spec URL per
    version, not one spec per group.

    Field names are read generically from manifest.json's "index_api"
    block rather than hardcoded to HubSpot's exact JSON keys, so a future
    vendor with the same "index describing many spec files" shape but
    different field names can reuse this without a code change — only a
    new manifest.json entry.
    """
    index_url: str
    results_path: str
    name_field: str
    group_field: str
    versions_field: str
    version_stage_field: str
    version_spec_url_field: str
    version_select_priority: List[str] = field(default_factory=list)
    version_select_fallback: str = "first_available"
    resource_group_count: Optional[int] = None  # sanity-check only, see run_index_api_app


# Verified against the vendors' own repos before being written into
# manifest.json (see the research notes in that file's per-app "note"
# fields) — this class just interprets whatever's under an app's
# "multi_file" key there. manifest.json is the single source of truth;
# nothing here is hardcoded per-app.


# ---------------------------------------------------------------------------
# GitHub directory discovery
# ---------------------------------------------------------------------------

def discover_files(cfg: DiscoverConfig) -> List[str]:
    """
    Lists a flat GitHub directory via the contents API and returns the
    relative repo paths of every matching file. Only safe for directories
    confirmed flat (no subfolders you'd need to reason about) — see the
    HubSpot note above for why this ISN'T used unconditionally everywhere.

    Unauthenticated GitHub API calls are rate-limited to 60/hour per IP.
    Set a GITHUB_TOKEN env var and this sends it as a Bearer token to get
    5000/hour instead — worth doing before running this against every
    multi-file app in one CI job.
    """
    api_url = f"https://api.github.com/repos/{cfg.owner}/{cfg.repo}/contents/{cfg.path}?ref={cfg.branch}"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        entries = json.loads(resp.read().decode("utf-8"))

    return sorted(
        f"{cfg.path}/{e['name']}"
        for e in entries
        if e.get("type") == "file" and e["name"].lower().endswith(cfg.extensions)
    )


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def _download(url: str, dest_path: str, timeout: int = 15) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(data)


def _fetch_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class AppRunSummary:
    app_name: str
    category: str = ""
    target_dir: str = ""
    files_processed: int = 0
    files_failed: int = 0
    endpoint_schema_names: List[str] = field(default_factory=list)
    auth_schema_name: Optional[str] = None
    metadata_written: bool = False
    file_errors: Dict[str, str] = field(default_factory=dict)


def _resource_hint_from_relative_path(rel_path: str) -> Optional[str]:
    """
    Best-effort product-name hint from a curated multi-file entry's own
    relative path.

    Filename stem is tried FIRST now, ahead of parent-directory: both
    currently-configured multi_file apps (Twilio, PayPal — see their
    manifest.json notes) use a FLAT layout, one file per product, e.g.
    'spec/json/twilio_accounts_v1.json' / 'openapi/checkout_orders_v2.json'.
    For a flat layout the parent directory is just the shared bucket
    folder ('json', 'openapi') — identical for every file in the repo,
    disambiguating nothing. The filename is where the actual resource
    identity lives for that layout, since that's the whole reason the
    vendor named it 'twilio_accounts_v1.json' instead of 'spec.json' in
    the first place.

    'Rollouts' is still checked first when present — HubSpot's own repo
    convention ('PublicApiSpecs/CRM/Deals/Rollouts/424/v3/deals.json' ->
    'Deals') nests by resource with a generic filename, the opposite
    shape from Twilio/PayPal, so parent-directory beats filename there.
    HubSpot itself is on the index_api path now, not multi_file, so this
    branch is currently unused by the manifest — kept for any future
    vendor with the same nested-by-resource layout.

    Falls back to the parent directory only if the filename itself
    couldn't be extracted (rel_path with no segments at all). Returns
    None rather than guessing wrong if nothing produces something
    usable.
    """
    parts = [p for p in rel_path.split("/") if p]
    if "Rollouts" in parts:
        idx = parts.index("Rollouts")
        if idx > 0:
            return parts[idx - 1]
    if parts:
        stem = parts[-1]
        for ext in (".json", ".yaml", ".yml"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        if stem:
            return stem
    if len(parts) >= 2:
        return parts[-2]
    return None


def _process_one_file(
    spec_path: str,
    identity_ctx: Optional[Dict[str, Any]],
    base_output_dir: str,
    app_key: str,
    category: Optional[str] = None,
    icon_url: Optional[str] = None,
    color: Optional[str] = None,
    resource_hint: Optional[str] = None,
    source_override: Optional[str] = None,
    display_name: Optional[str] = None,
    patches_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Runs get_app_context() fresh on THIS file (so its own base_url/info
    are used — the fix for bug #2 above), then overrides identity fields
    with the pinned app-level ones once we have them (the fix for bug #3),
    so every file's endpoints land in the same folder while each keeps
    its own correct base_url.

    🛠️ FIX: category/icon_url/color/app_key are now passed straight into
    get_app_context() as overrides on the FIRST file too - previously
    identity_ctx["category"]/["icon_url"]/["color"] were whatever
    get_app_context() heuristically derived from that first file's OWN
    spec content, which manifest.json's values never got a chance to
    override. app_key is also passed as app_name_override so the folder
    name matches the clean manifest key (e.g. "stripe") instead of
    whatever info.title/x-providerName happens to sanitize to.

    🛠️ FIX: display_name is now passed straight into get_app_context()
    too, for the same reason app_key is — otherwise ctx["display_name"]
    (see get_app_context's docstring) would fall back to THIS file's own
    info.title, which is exactly the "some app names aren't precise"
    symptom: a multi-file app's later files could carry a different or
    more cryptic title than the one users should see.
    """
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)  # NOT json.load(f.read()) — that never worked

    ctx = converter.get_app_context(
        spec, base_output_dir,
        category_override=category, icon_url_override=icon_url,
        color_override=color, app_name_override=app_key,
        source_override=source_override, display_name_override=display_name,
    )

    if identity_ctx is not None:
        # Pin identity to the FIRST file's resolved context, so a later
        # file with a differently-worded info.title can't split this
        # app's endpoints into a second folder. base_url stays this
        # file's own — that's the one field that's legitimately allowed
        # to differ per file. source is pinned too, for the same reason
        # as category/icon_url/color: one app's trust tier shouldn't be
        # able to drift file-to-file within the same multi-file app.
        ctx["app_name"] = identity_ctx["app_name"]
        ctx["display_name"] = identity_ctx["display_name"]
        ctx["category"] = identity_ctx["category"]
        ctx["target_dir"] = identity_ctx["target_dir"]
        ctx["icon_url"] = identity_ctx["icon_url"]
        ctx["color"] = identity_ctx["color"]
        ctx["source"] = identity_ctx["source"]
        ctx["last_updated"] = identity_ctx["last_updated"]

    schema_names = converter.transpile_endpoints(spec, ctx, resource_hint=resource_hint, patches_root=patches_root)
    return {"ctx": ctx, "spec": spec, "schema_names": schema_names}


def run_multi_file_app(app_key: str, mf: MultiFileSpec, base_output_dir: str,
                        category: Optional[str] = None, icon_url: Optional[str] = None,
                        color: Optional[str] = None, source_trust: Optional[str] = None,
                        display_name: Optional[str] = None,
                        patches_root: Optional[str] = None) -> AppRunSummary:
    summary = AppRunSummary(app_name=app_key)
    source_override = "transpiled_community" if source_trust == "community" else None

    if mf.files:
        relative_paths = mf.files
    elif mf.discover:
        try:
            relative_paths = discover_files(mf.discover)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            summary.file_errors["<discovery>"] = str(e)
            return summary
    else:
        summary.file_errors["<config>"] = "MultiFileSpec has neither files= nor discover="
        return summary

    if not relative_paths:
        summary.file_errors["<discovery>"] = "discovery returned zero files — check path/branch"
        return summary

    identity_ctx: Optional[Dict[str, Any]] = None
    metadata_target = mf.metadata_source or relative_paths[0]

    with tempfile.TemporaryDirectory() as tmp_dir:
        for rel_path in relative_paths:
            local_path = os.path.join(tmp_dir, rel_path.replace("/", "_"))
            url = mf.raw_url(rel_path)
            try:
                _download(url, local_path)
                result = _process_one_file(local_path, identity_ctx, base_output_dir, app_key,
                                            category=category, icon_url=icon_url, color=color,
                                            resource_hint=_resource_hint_from_relative_path(rel_path),
                                            source_override=source_override, display_name=display_name,
                                            patches_root=patches_root)
            except Exception as e:  # noqa: BLE001 — one bad file must not sink the whole app
                summary.files_failed += 1
                summary.file_errors[rel_path] = str(e)
                continue

            if identity_ctx is None:
                identity_ctx = result["ctx"]
                summary.category = identity_ctx["category"]
                summary.target_dir = identity_ctx["target_dir"]

            summary.files_processed += 1
            # Catch schema_name collisions across files LOUDLY rather than
            # letting a later file's json.dump() silently overwrite an
            # earlier file's output at the same path with no trace. With
            # _identity_for_operation() now folding resource_hint into
            # identity, this should only ever fire if resource_hint itself
            # was None/empty for this file (e.g. _resource_hint_from_
            # relative_path() couldn't derive anything from a vendor's
            # layout) or two files coincidentally produced the same hint —
            # either way, whichever schema wrote second below is the one
            # that's now missing from the app's real name.
            new_names = result["schema_names"]
            dupes = set(new_names) & set(summary.endpoint_schema_names)
            if dupes:
                print(f"⚠️  schema_name collision(s) in {app_key} from {rel_path}: "
                      f"{', '.join(sorted(dupes))} — earlier file's output was overwritten")
            summary.endpoint_schema_names.extend(new_names)

            if rel_path == metadata_target:
                try:
                    converter.extract_app_metadata(result["spec"], identity_ctx, fetch_favicon=True, patches_root=patches_root)
                    summary.metadata_written = True
                except Exception as e:  # noqa: BLE001
                    summary.file_errors[f"{rel_path} (metadata)"] = str(e)

                try:
                    summary.auth_schema_name = converter.extract_oauth_config(result["spec"], identity_ctx, patches_root=patches_root)
                except Exception as e:  # noqa: BLE001
                    summary.file_errors[f"{rel_path} (oauth)"] = str(e)

    if identity_ctx:
        summary.endpoint_schema_names = converter.apply_nodes(
            patches_root, identity_ctx["category"], identity_ctx["app_name"],
            identity_ctx["target_dir"], summary.endpoint_schema_names,
        )

    if identity_ctx and (summary.endpoint_schema_names or summary.auth_schema_name):
        converter.write_schema_index(identity_ctx, summary.endpoint_schema_names, summary.auth_schema_name, patches_root=patches_root)

    return summary


def _select_version(versions: List[Dict[str, Any]], idx: IndexApiSpec) -> Optional[Dict[str, Any]]:
    """
    Picks one version dict per resource group, trying version_select_priority
    stages in order (e.g. 'LATEST' then 'STABLE'), falling back to the
    first available version if none of those stages are present.

    The fallback isn't optional polish — manifest.json's own note on the
    HubSpot entry confirms 6 of its 116 resource groups (e.g. 'Forms',
    'Commerce Subscriptions') have ONLY a DEVELOPER_PREVIEW version as of
    the fetch that note is based on. LATEST/STABLE-only selection would
    silently drop those groups' endpoints entirely rather than surfacing
    an error — worse than a preview-quality file, since nothing would
    indicate anything was missing at all.
    """
    if not versions:
        return None
    by_stage: Dict[Any, Dict[str, Any]] = {}
    for v in versions:
        stage = v.get(idx.version_stage_field)
        by_stage.setdefault(stage, v)  # first match per stage wins if duplicates exist
    for stage in idx.version_select_priority:
        if stage in by_stage:
            return by_stage[stage]
    if idx.version_select_fallback == "first_available":
        return versions[0]
    return None


def run_index_api_app(app_key: str, idx: IndexApiSpec, base_output_dir: str,
                       category: Optional[str] = None, icon_url: Optional[str] = None,
                       color: Optional[str] = None, delay: float = 0.3,
                       source_trust: Optional[str] = None,
                       display_name: Optional[str] = None,
                       patches_root: Optional[str] = None) -> AppRunSummary:
    """
    Handles the 'index_api' manifest shape (confirmed on HubSpot — see
    IndexApiSpec's docstring): fetch one JSON index, select a version per
    resource group, download each group's chosen spec, and transpile all
    of them into ONE app folder — the same "many files, one app" pattern
    run_multi_file_app implements for GitHub-hosted specs, just with a
    different (vendor-specific, JSON-index-driven) file discovery step
    instead of a fixed file list or a GitHub directory listing.

    Unlike run_multi_file_app, there's no explicit metadata_source in
    this shape — manifest.json's index_api block doesn't designate one
    resource group's spec as "the" source for _meta.json/OAuth, since
    HubSpot's own index doesn't single one out either. So this tries
    metadata/OAuth extraction on each successfully-downloaded group in
    turn until one actually produces something, rather than assuming
    the first group's spec necessarily carries the info block or
    securityScheme — a real risk with 116 independently-versioned specs
    where nothing guarantees uniform content across all of them.

    delay: politeness pause between each group's download — 116 requests
    back-to-back with none at all risks tripping rate limits the same
    way batch-runner.py's own --delay exists to avoid for APIs.guru.
    """
    summary = AppRunSummary(app_name=app_key)
    source_override = "transpiled_community" if source_trust == "community" else None

    try:
        index_data = _fetch_json(idx.index_url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        summary.file_errors["<index>"] = str(e)
        return summary

    results = index_data.get(idx.results_path, [])
    if not results:
        summary.file_errors["<index>"] = f"index response had no '{idx.results_path}' entries"
        return summary

    if idx.resource_group_count is not None and len(results) != idx.resource_group_count:
        print(
            f"⚠️  {app_key}: index returned {len(results)} resource groups, "
            f"manifest.json recorded {idx.resource_group_count} at research time — "
            f"the vendor's index shape or contents may have changed since then."
        )

    identity_ctx: Optional[Dict[str, Any]] = None
    metadata_written = False

    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, group in enumerate(results):
            group_name = group.get(idx.name_field) or group.get(idx.group_field) or f"group_{i}"
            versions = group.get(idx.versions_field, [])
            version = _select_version(versions, idx)
            if version is None:
                summary.file_errors[group_name] = "no usable version found for this resource group"
                continue

            spec_url = version.get(idx.version_spec_url_field)
            if not spec_url:
                summary.file_errors[group_name] = f"selected version has no '{idx.version_spec_url_field}' URL"
                continue

            safe_name = "".join(c if c.isalnum() else "_" for c in group_name)
            local_path = os.path.join(tmp_dir, f"{safe_name}_{i}.json")
            try:
                _download(spec_url, local_path)
                result = _process_one_file(local_path, identity_ctx, base_output_dir, app_key,
                                            category=category, icon_url=icon_url, color=color,
                                            resource_hint=group_name,
                                            source_override=source_override, display_name=display_name,
                                            patches_root=patches_root)
            except Exception as e:  # noqa: BLE001 — one bad resource group must not sink the other 115
                summary.files_failed += 1
                summary.file_errors[group_name] = str(e)
                continue
            finally:
                time.sleep(delay)

            if identity_ctx is None:
                identity_ctx = result["ctx"]
                summary.category = identity_ctx["category"]
                summary.target_dir = identity_ctx["target_dir"]

            summary.files_processed += 1
            new_names = result["schema_names"]
            dupes = set(new_names) & set(summary.endpoint_schema_names)
            if dupes:
                print(f"⚠️  schema_name collision(s) in {app_key} from group '{group_name}': "
                      f"{', '.join(sorted(dupes))} — earlier group's output was overwritten")
            summary.endpoint_schema_names.extend(new_names)

            if not metadata_written:
                try:
                    converter.extract_app_metadata(result["spec"], identity_ctx, fetch_favicon=True, patches_root=patches_root)
                    metadata_written = True
                except Exception as e:  # noqa: BLE001 — try the next group's spec instead of giving up on metadata entirely
                    summary.file_errors[f"{group_name} (metadata)"] = str(e)

            if summary.auth_schema_name is None:
                try:
                    auth_name = converter.extract_oauth_config(result["spec"], identity_ctx, patches_root=patches_root)
                    if auth_name:
                        summary.auth_schema_name = auth_name
                except Exception as e:  # noqa: BLE001
                    summary.file_errors[f"{group_name} (oauth)"] = str(e)

    summary.metadata_written = metadata_written

    if identity_ctx:
        summary.endpoint_schema_names = converter.apply_nodes(
            patches_root, identity_ctx["category"], identity_ctx["app_name"],
            identity_ctx["target_dir"], summary.endpoint_schema_names,
        )

    if identity_ctx and (summary.endpoint_schema_names or summary.auth_schema_name):
        converter.write_schema_index(identity_ctx, summary.endpoint_schema_names, summary.auth_schema_name, patches_root=patches_root)

    return summary


def run_single_file_app(app_key: str, url: str, base_output_dir: str,
                         category: Optional[str] = None, icon_url: Optional[str] = None,
                         color: Optional[str] = None, source_trust: Optional[str] = None,
                         display_name: Optional[str] = None,
                         patches_root: Optional[str] = None) -> AppRunSummary:
    summary = AppRunSummary(app_name=app_key)
    # Preserve the source's real extension — converter.py's _load_spec_file()
    # picks JSON vs YAML parsing by looking at THIS file's extension, not
    # the URL's. Naming every download "spec.json" regardless of source
    # (the previous behavior) would make a real .yaml spec get handed to
    # the JSON parser and fail with a confusing JSONDecodeError.
    ext = os.path.splitext(url.split("?")[0])[1] or ".json"
    # manifest.json's "source_trust": "community" (a Tier-2 pointer — a
    # third-party repo reconstruction rather than the vendor's own) maps
    # to metadata.source="transpiled_community" in every schema this app
    # produces, so a catalog consumer can filter by trust level without
    # cross-referencing the manifest. Anything else (unset, or explicitly
    # "official") leaves source_override as None, which converter.py
    # defaults to "transpiled_official".
    source_override = "transpiled_community" if source_trust == "community" else None
    with tempfile.TemporaryDirectory() as tmp_dir:
        local_path = os.path.join(tmp_dir, f"spec{ext}")
        try:
            _download(url, local_path)
            # 🛠️ FIX: was `converter.transpile_full(local_path, base_output_dir=base_output_dir)`
            # with no override args at all - manifest.json's hand-curated
            # category/icon_url/color (and app_key itself, for a clean
            # folder name) never reached converter.py, so every app fell
            # back to get_app_context()'s spec-heuristic derivation, which
            # is always empty for a raw vendor spec (see get_app_context's
            # docstring). Passing them through here is what actually lets
            # manifest.json's values win.
            # ⚠️ NOT VERIFIED: converter.transpile_full does not appear anywhere
            # in the converter.py shared in this conversation — only
            # transpile_endpoints() (called via _process_one_file, used by the
            # multi_file/index_api paths above) is defined there. This call
            # was already here before this patches_root change and presumably
            # relies on a transpile_full() that lives in a version of
            # converter.py not yet shared. patches_root is threaded through
            # here on the assumption that whatever transpile_full() actually
            # looks like accepts it and forwards it into its own
            # transpile_endpoints() call the same way _process_one_file does
            # — that assumption can't be confirmed without seeing it. If
            # transpile_full doesn't exist at all, single-file apps
            # (Slack, Atlassian/Jira per the manifest) fail with
            # AttributeError independent of anything patches-related.
            result = converter.transpile_full(
                local_path, base_output_dir=base_output_dir,
                category_override=category, icon_url_override=icon_url,
                color_override=color, app_name_override=app_key,
                source_override=source_override, display_name_override=display_name,
                patches_root=patches_root,
            )
        except Exception as e:  # noqa: BLE001
            summary.files_failed = 1
            summary.file_errors[url] = str(e)
            return summary

    summary.files_processed = 1
    summary.category = result["category"]
    summary.target_dir = result["target_dir"]
    summary.endpoint_schema_names = result["schema_names"]
    summary.auth_schema_name = result.get("auth_schema_name")
    summary.metadata_written = True
    return summary


def run_google_discovery_app(app_key: str, url: str, base_output_dir: str,
                              category: Optional[str] = None, icon_url: Optional[str] = None,
                              color: Optional[str] = None, source_trust: Optional[str] = None,
                              display_name: Optional[str] = None,
                              patches_root: Optional[str] = None) -> AppRunSummary:
    """
    For manifest entries with "source_type": "google_discovery" — Google's
    APIs (Gmail, Sheets, Docs, Forms, YouTube, the GA4 Data API, ...)
    aren't OpenAPI; they publish a Google Discovery Document instead
    (resources/methods, not paths; bare-string $refs, not JSON pointers
    — see google_discovery_adapter.py's docstring for the full mapping,
    grounded against a real fetch of Gmail's own document rather than
    the format guide alone).

    This mirrors run_single_file_app almost exactly — same download/
    error-handling shape, same eventual call into transpile_full() — with
    exactly one difference: the fetched document is adapted into
    transpile_full()'s expected OpenAPI-3 shape and written back out to
    a temp file BEFORE handing it off, so every downstream stage
    (get_app_context, transpile_endpoints, patches, resource_hint/
    collision handling) runs completely unmodified. url here must be
    the per-API document (e.g. ".../discovery/v1/apis/gmail/v1/rest" or
    "https://gmail.googleapis.com/$discovery/rest?version=v1"), NOT the
    bare directory-listing endpoint (".../discovery/v1/apis" with no
    per-API path) — that one returns a list of every Google API, not a
    spec, and won't have a "resources" key at all (see manifest.json's
    former config for these 6 apps, which pointed at the directory by
    mistake and got silently... actually loudly... skipped by the
    url-extension check in run_manifest(), since the directory URL has
    no .json/.yaml/.yml extension).
    """
    summary = AppRunSummary(app_name=app_key)
    source_override = "transpiled_community" if source_trust == "community" else None
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_path = os.path.join(tmp_dir, "discovery.json")
        adapted_path = os.path.join(tmp_dir, "spec.json")
        try:
            _download(url, raw_path)
            with open(raw_path, "r", encoding="utf-8") as f:
                discovery_doc = json.load(f)
            if not discovery_doc.get("resources"):
                # Loud, specific failure instead of transpile_endpoints()
                # silently returning zero paths later — most likely cause
                # is url pointing at the bare directory listing (items[])
                # rather than one API's own document (resources{}).
                raise ValueError(
                    f"fetched document has no 'resources' key — is {url!r} "
                    f"the directory listing (.../discovery/v1/apis) rather "
                    f"than one API's own discovery document?"
                )
            adapted_spec = discovery_doc_to_openapi_shape(discovery_doc)
            with open(adapted_path, "w", encoding="utf-8") as f:
                json.dump(adapted_spec, f)
            result = converter.transpile_full(
                adapted_path, base_output_dir=base_output_dir,
                category_override=category, icon_url_override=icon_url,
                color_override=color, app_name_override=app_key,
                source_override=source_override, display_name_override=display_name,
                patches_root=patches_root,
            )
        except Exception as e:  # noqa: BLE001
            summary.files_failed = 1
            summary.file_errors[url] = str(e)
            return summary

    summary.files_processed = 1
    summary.category = result["category"]
    summary.target_dir = result["target_dir"]
    summary.endpoint_schema_names = result["schema_names"]
    summary.auth_schema_name = result.get("auth_schema_name")
    summary.metadata_written = True
    return summary


def run_nodes_only_app(app_key: str, base_output_dir: str,
                        category: Optional[str] = None, icon_url: Optional[str] = None,
                        color: Optional[str] = None, display_name: Optional[str] = None,
                        patches_root: Optional[str] = None) -> AppRunSummary:
    """
    The actual entry point for an app with NO spec source at all —
    exists entirely through connectors/<category>/<app_key>/{nodes,
    community/nodes}/. Every other run_*_app function above requires a
    real spec to bootstrap ctx (download it, parse it, hand it to
    get_app_context()); this is the one path that doesn't, and until it
    existed, a spec-less app could never actually reach apply_nodes() at
    all — run_manifest() had no branch for "no url, no multi_file, no
    official_api_index", so nothing would ever call get_app_context() for
    it in the first place, regardless of how many node files existed on
    disk for it.

    ctx is built from an empty spec ({}) — get_app_context(),
    extract_oauth_config(), extract_app_metadata(), and write_schema_index()
    all tolerate that gracefully already (every field they'd normally
    pull from spec['info']/spec['components']/etc. just defaults to empty/
    blank), and the "_auth"/"_meta"/"_index" native node checks added to
    the latter three (see converter.py) mean a hand-authored node for any
    of those three ALSO works here, exactly like it does for a spec-
    having app — the exact same functions, just fed an empty spec instead
    of a real one.

    source_override is hardcoded to "community_authored" — unlike every
    other app type, there's no vendor spec this could have been
    transpiled FROM at all, so "transpiled_official"/"transpiled_community"
    (which imply SOME machine-readable source existed) would misrepresent
    where this app's content actually comes from. This is the metadata.source
    value the README's own contribution guide already specifies for
    hand-authored content.
    """
    summary = AppRunSummary(app_name=app_key)

    ctx = converter.get_app_context(
        {}, base_output_dir, category_override=category, icon_url_override=icon_url,
        color_override=color, app_name_override=app_key, display_name_override=display_name,
        source_override="community_authored",
    )
    summary.category = ctx["category"]
    summary.target_dir = ctx["target_dir"]

    summary.endpoint_schema_names = converter.apply_nodes(
        patches_root, ctx["category"], ctx["app_name"], ctx["target_dir"], [],
    )

    try:
        summary.auth_schema_name = converter.extract_oauth_config({}, ctx, patches_root=patches_root)
    except Exception as e:  # noqa: BLE001
        summary.file_errors["_auth"] = str(e)

    if not patches_root or (not summary.endpoint_schema_names and not summary.auth_schema_name):
        summary.file_errors["<nodes>"] = (
            "no --patch/--patches-dir given" if not patches_root
            else f"no node files found under connectors/{ctx['category']}/{app_key}/{{nodes,community/nodes}}/"
        )

    try:
        converter.extract_app_metadata({}, ctx, fetch_favicon=True, patches_root=patches_root)
        summary.metadata_written = True
    except Exception as e:  # noqa: BLE001
        summary.file_errors["_meta"] = str(e)

    try:
        converter.write_schema_index(ctx, summary.endpoint_schema_names, summary.auth_schema_name, patches_root=patches_root)
    except Exception as e:  # noqa: BLE001
        summary.file_errors["_index"] = str(e)

    return summary


# ---------------------------------------------------------------------------
# Manifest-driven entry point
# ---------------------------------------------------------------------------

def _multi_file_spec_from_manifest_entry(app_key: str, entry: Dict[str, Any]) -> Optional[MultiFileSpec]:
    """
    Builds a MultiFileSpec from an app's "multi_file" block in
    manifest.json, or returns None if the app doesn't have one (=
    single-file app) or has one explicitly marked not-ready
    ("status": "needs_curated_file_list" — see the HubSpot entry).
    """
    mf = entry.get("multi_file")
    if not mf:
        return None
    if mf.get("status") == "needs_curated_file_list":
        print(f"⏭️  {app_key}: multi_file config not ready — {mf.get('reason', 'no reason given')}")
        return None

    discover_cfg = None
    if "discover" in mf:
        discover_cfg = DiscoverConfig(
            owner=mf["owner"], repo=mf["repo"], path=mf["discover"]["path"],
            branch=mf.get("branch", DEFAULT_BRANCH),
            extensions=tuple(mf["discover"].get("extensions", (".json",))),
        )

    return MultiFileSpec(
        owner=mf["owner"], repo=mf["repo"], branch=mf.get("branch", DEFAULT_BRANCH),
        discover=discover_cfg, files=mf.get("files"),
        metadata_source=mf.get("metadata_source"),
    )


def _index_api_spec_from_manifest_entry(entry: Dict[str, Any]) -> Optional[IndexApiSpec]:
    """Builds an IndexApiSpec from an app's 'index_api' block in
    manifest.json, or returns None if the app doesn't have one."""
    cfg = entry.get("index_api")
    if not cfg:
        return None
    return IndexApiSpec(
        index_url=cfg["index_url"],
        results_path=cfg["results_path"],
        name_field=cfg["name_field"],
        group_field=cfg["group_field"],
        versions_field=cfg["versions_field"],
        version_stage_field=cfg["version_stage_field"],
        version_spec_url_field=cfg["version_spec_url_field"],
        version_select_priority=cfg.get("version_select_priority", []),
        version_select_fallback=cfg.get("version_select_fallback", "first_available"),
        resource_group_count=cfg.get("resource_group_count"),
    )


def run_manifest(manifest_path: str, base_output_dir: str = "../schemas",
                  only_apps: Optional[List[str]] = None,
                  patches_root: Optional[str] = None) -> Dict[str, AppRunSummary]:
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    if only_apps:
        unknown = [a for a in only_apps if a not in manifest]
        if unknown:
            print(f"⚠️  Not in manifest, skipping: {', '.join(unknown)}")
        manifest = {k: v for k, v in manifest.items() if k in only_apps}
        if not manifest:
            print("⚠️  Nothing to do — none of the requested apps are in the manifest.")
            return {}

    results: Dict[str, AppRunSummary] = {}

    total = len(manifest)
    for i, (app_key, entry) in enumerate(manifest.items(), 1):
        print(f"\n🚀 [{i}/{total}] {app_key}")
        # 🛠️ FIX: category/icon_url/color were sitting unused in every
        # manifest.json entry - extracted here now and threaded through
        # both code paths below, so they actually override converter.py's
        # spec-heuristic derivation (see get_app_context's docstring for
        # why that heuristic is always empty for a raw vendor spec).
        manifest_category = entry.get("category")
        manifest_icon_url = entry.get("icon_url")
        manifest_color = entry.get("color")
        # "source_trust": "community" on a manifest entry means this
        # points at a third-party repo reconstruction (Tier 2) rather
        # than the vendor's own spec (Tier 1, the default) — threaded
        # through so every schema this app produces carries
        # metadata.source="transpiled_community" instead of the default
        # "transpiled_official", visible to any catalog consumer without
        # cross-referencing the manifest.
        manifest_source_trust = entry.get("source_trust")
        # 🛠️ FIX: manifest.json's "display_name" (when an app curates one)
        # was never read at all — every app's UI label fell back to
        # whatever the spec file's own info.title said (see
        # get_app_context's docstring), which is inconsistent across
        # vendors and, for multi-file apps, could even vary file-to-file.
        # When an app doesn't set this, display_name defaults to app_key
        # itself, verbatim (get_app_context's own fallback) — so this
        # override is only needed if you want the UI to show something
        # other than the raw manifest key.
        manifest_display_name = entry.get("display_name")

        mf = _multi_file_spec_from_manifest_entry(app_key, entry)
        idx = _index_api_spec_from_manifest_entry(entry)

        if idx is not None:
            summary = run_index_api_app(app_key, idx, base_output_dir,
                                         category=manifest_category, icon_url=manifest_icon_url,
                                         color=manifest_color, source_trust=manifest_source_trust,
                                         display_name=manifest_display_name,
                                         patches_root=patches_root)
        elif mf is not None:
            summary = run_multi_file_app(app_key, mf, base_output_dir,
                                          category=manifest_category, icon_url=manifest_icon_url,
                                          color=manifest_color, source_trust=manifest_source_trust,
                                          display_name=manifest_display_name,
                                          patches_root=patches_root)
        elif entry.get("multi_file", {}).get("status") == "needs_curated_file_list":
            results[app_key] = AppRunSummary(
                app_name=app_key,
                file_errors={"<manifest>": entry["multi_file"].get("reason", "multi_file config not ready")},
            )
            continue
        elif entry.get("nodes_only") is True:
            # An app that exists ONLY through connectors/.../{nodes,
            # community/nodes}/ — no url, no multi_file, no
            # official_api_index block needed or expected. Checked
            # ahead of the url-required fallback below specifically so
            # this doesn't fall into "unrecognized url shape" and get
            # skipped.
            summary = run_nodes_only_app(app_key, base_output_dir,
                                          category=manifest_category, icon_url=manifest_icon_url,
                                          color=manifest_color, display_name=manifest_display_name,
                                          patches_root=patches_root)
        elif entry.get("source_type") == "google_discovery":
            # Google's Discovery Document format, not OpenAPI — see
            # run_google_discovery_app's docstring. Checked ahead of the
            # url-extension fallback below on purpose: a discovery URL
            # (".../gmail/v1/rest", ".../$discovery/rest?version=v1")
            # doesn't end in .json/.yaml/.yml even though it returns
            # JSON, so it would otherwise hit that branch's "unrecognized
            # url shape" skip.
            url = entry.get("url")
            if not url:
                results[app_key] = AppRunSummary(app_name=app_key, file_errors={"<manifest>": "google_discovery entry has no url"})
                continue
            summary = run_google_discovery_app(app_key, url, base_output_dir,
                                                category=manifest_category, icon_url=manifest_icon_url,
                                                color=manifest_color, source_trust=manifest_source_trust,
                                                display_name=manifest_display_name,
                                                patches_root=patches_root)
        else:
            url = entry.get("url")
            if not url or not (url.endswith(".json") or url.endswith(".yaml") or url.endswith(".yml")):
                print(
                    f"⚠️  Skipping {app_key}: url doesn't look like a raw spec file "
                    f"({url!r}) and it has no \"multi_file\" block in manifest.json. "
                    f"If this app's endpoints are actually scattered across multiple "
                    f"files, add a \"multi_file\" block for it instead of letting this "
                    f"fall through to single-file handling."
                )
                results[app_key] = AppRunSummary(app_name=app_key, file_errors={"<manifest>": "unrecognized url shape"})
                continue
            summary = run_single_file_app(app_key, url, base_output_dir,
                                           category=manifest_category, icon_url=manifest_icon_url,
                                           color=manifest_color, source_trust=manifest_source_trust,
                                           display_name=manifest_display_name,
                                           patches_root=patches_root)

        results[app_key] = summary
        status = "✅" if not summary.file_errors else "⚠️ partial"
        print(
            f"{status} {app_key}: {len(summary.endpoint_schema_names)} endpoints across "
            f"{summary.files_processed} file(s), {summary.files_failed} failed, "
            f"oauth={summary.auth_schema_name is not None}, meta={summary.metadata_written}"
        )
        for src, err in summary.file_errors.items():
            print(f"   - {src}: {err}")

    return results


if __name__ == "__main__":
    import sys
    manifest_arg = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    output_arg = sys.argv[2] if len(sys.argv) > 2 else "../schemas"
    run_manifest(manifest_arg, output_arg)