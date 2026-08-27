import os
import re
import json
import pathlib
import shutil
import time
import http.client
import urllib.request
import urllib.error
from datetime import datetime, timezone


def _now_iso():
    """UTC timestamp, e.g. '2026-08-11T14:32:07Z' — used to stamp every
    schema generated in a given transpile run so freshness is verifiable
    per-file, not just claimed in a README."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------
# Real-world OpenAPI specs almost always define request bodies and
# parameters via '$ref' pointers into components.schemas/parameters rather
# than inlining fields directly — inline was only ever the toy-example
# case. Without resolving these, transpile_endpoints silently sees an
# empty schema and produces a technically-valid but functionally-empty
# file (no params, no body) — worse than an error, since nothing flags it.

def _resolve_ref(spec, ref):
    """Resolves a local JSON pointer like '#/components/schemas/X' against
    the full spec document. Returns None for anything this can't handle
    (external file refs, a pointer that doesn't exist) rather than raising —
    callers fall back to treating the node as ref-less."""
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _deref(spec, node, seen=None):
    """
    Resolves a single '$ref' at the top of `node`, merging any sibling
    keys over the resolved target (OpenAPI 3.0 disallows siblings next to
    $ref, but merging is harmless and correct for 3.1's dialect where they
    are allowed). Cycle-protected: a schema that references itself,
    directly or indirectly (e.g. a 'parent' field of the same type,
    common in tree-shaped resources), stops resolving that branch instead
    of recursing forever — the $ref string is left as-is for that branch,
    which downstream code treats as an empty/unknown field rather than
    crashing.
    """
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    seen = seen or set()
    ref = node["$ref"]
    if ref in seen:
        return {k: v for k, v in node.items() if k != "$ref"}
    resolved = _resolve_ref(spec, ref)
    if resolved is None:
        return {k: v for k, v in node.items() if k != "$ref"}
    merged = {**resolved, **{k: v for k, v in node.items() if k != "$ref"}}
    return _deref(spec, merged, seen | {ref})


def _deref_schema_tree(spec, schema, seen=None):
    """Like _deref, but also recurses into 'properties' so a nested field
    that is itself a $ref (e.g. 'address': {'$ref': '#/components/schemas/Address'})
    comes back fully resolved too — not just the outermost schema.
    Cycle protection has to be threaded through this recursion explicitly:
    _deref's own internal 'seen' update is local to that one call and
    doesn't reach sibling calls made here for each property, so a
    self-referential schema (e.g. a 'parent' field of the same type)
    would otherwise recurse through 'properties' forever even though
    _deref() alone is cycle-safe in isolation.
    """
    seen = seen or set()
    original_ref = schema.get("$ref") if isinstance(schema, dict) else None
    resolved = _deref(spec, schema, seen)
    if not isinstance(resolved, dict):
        return resolved
    seen_here = seen | ({original_ref} if original_ref else set())
    if isinstance(resolved.get("properties"), dict):
        resolved = {
            **resolved,
            "properties": {
                k: _deref_schema_tree(spec, v, seen_here)
                for k, v in resolved["properties"].items()
            },
        }
    return resolved


# Keywords that, combined with a state-changing method, suggest an endpoint
# is registering a way to *receive* events rather than performing a normal
# action. Intentionally narrow — false negatives (missing a real trigger)
# are far less damaging than false positives (mislabeling a normal action
# as a trigger), so this only fires on fairly unambiguous vocabulary.
_TRIGGER_KEYWORDS = ("webhook", "subscribe", "subscription", "callback")


def _infer_node_type(path, method, operation_id, summary, description):
    """
    Heuristic only — OpenAPI has no field that says 'this is a trigger'.
    Fires on 'trigger' only when BOTH hold: (a) trigger-ish vocabulary
    appears in the path/operationId/summary/description, AND (b) the
    method is POST or PUT — i.e. *registering* a subscription, not
    listing/reading/deleting one. A GET on '/webhooks' (list existing
    webhooks) or a DELETE on '/webhooks/{id}' stays 'action' on purpose:
    those manage a trigger, they aren't the trigger itself.
    Always returns a (node_type, confidence) pair rather than a bare
    string, so callers can flag heuristic guesses for manual review
    instead of presenting them as verified fact.
    """
    haystack = " ".join([path or "", operation_id or "", summary or "", description or ""]).lower()
    is_trigger_shaped = any(kw in haystack for kw in _TRIGGER_KEYWORDS)
    if is_trigger_shaped and method.lower() in ("post", "put"):
        return "trigger", "heuristic"
    return "action", "heuristic"


# ---------------------------------------------------------------------------
# Action label generation - "Create Contact" / "Update Contact" / "List
# Webhooks" style labels for rendering nodes in a Zapier/Make/n8n-style
# workflow-builder UI. Three-tier fallback, most-trustworthy source first:
#   1. `summary` - human-authored documentation text. Trusted almost as-is.
#   2. `operationId` - machine-authored, usually verb_resource shaped
#      ("create_contact"), but SOMETIMES just a path template baked into a
#      string (HubSpot: "get-/crm/v3/objects/0-3_getPage") - detected and
#      rejected rather than blindly humanized into garbage.
#   3. HTTP method + path segments - always available, lowest quality,
#      since a path segment can itself be a cryptic internal ID (the same
#      HubSpot "0-3" case) with no semantic content a generic algorithm
#      can recover without external context.
# ---------------------------------------------------------------------------

_VERB_LABELS = {
    "get": "Get", "read": "Get", "retrieve": "Get", "fetch": "Get", "find": "Get",
    "show": "Get", "view": "Get",
    "list": "List", "search": "Search", "query": "Search", "filter": "Search",
    "create": "Create", "add": "Create", "new": "Create", "insert": "Create",
    "post": "Create", "register": "Create", "make": "Create",
    "update": "Update", "edit": "Update", "modify": "Update", "patch": "Update",
    "replace": "Update", "put": "Update", "set": "Update",
    "delete": "Delete", "remove": "Delete", "destroy": "Delete", "drop": "Delete",
    "archive": "Archive", "unarchive": "Unarchive", "restore": "Restore",
    "upsert": "Upsert", "merge": "Merge", "clone": "Clone", "duplicate": "Duplicate",
    "cancel": "Cancel", "void": "Void", "capture": "Capture", "refund": "Refund",
    "send": "Send", "subscribe": "Subscribe", "unsubscribe": "Unsubscribe",
    "batch": "Batch", "bulk": "Bulk", "sync": "Sync", "import": "Import",
    "export": "Export", "download": "Download", "upload": "Upload",
}

# Tokens that are clearly structural (versioning, generic REST vocabulary)
# rather than a real resource/verb, so they get skipped when picking which
# operationId/path token is the actual resource name.
_NOISE_TOKENS = {"api", "v1", "v2", "v3", "v4", "get", "post", "put", "patch",
                  "delete", "crm", "objects", "public"}

_HTTP_METHOD_VERB = {
    "post": "Create", "put": "Update", "patch": "Update", "delete": "Delete",
}


def _split_tokens(s):
    """snake_case / kebab-case / camelCase / a raw URL path -> lowercase
    word tokens. A '/' is treated as a separator too, so an operationId
    that's secretly a path template splits the same way a real path would."""
    s = s.replace("/", " ").replace("_", " ").replace("-", " ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    return [t.lower() for t in s.split() if t]


def _looks_cryptic(token):
    """True for tokens with no semantic content a generic algorithm can
    recover: pure numbers ('3', '0'), OpenAPI path params ('{id}'), or
    short alphanumeric ids that are neither a real word nor a known verb
    (HubSpot's '0-3' object-type id splits into '0' and '3' - both caught
    here)."""
    if not token or token.startswith("{"):
        return True
    if token.isdigit():
        return True
    if len(token) <= 2 and not token.isalpha():
        return True
    return False


def _singularize(word):
    """Minimal, deliberately conservative English singularizer - covers
    the common plural shapes seen in REST resource names without an
    inflection-library dependency. Left alone (not stripped) whenever the
    result would be ambiguous, since a wrong singular ('Statu' from
    'Status') is worse than an unsingularized plural."""
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if lower.endswith(("ses", "xes", "ches", "shes")) and len(word) > 4:
        return word[:-2]
    if lower.endswith("us") or lower.endswith("ss"):
        return word  # "status", "address" - stripping trailing 's' would mangle these
    if lower.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _clean_summary(summary):
    """'Create a contact.' -> 'Create Contact'. Strips articles ANYWHERE
    in the text (not just a leading one - 'Create a contact' has 'a'
    after the verb, not at position 0) and trailing punctuation, then
    title-cases - summary text is otherwise usually already close to
    UI-label-ready."""
    s = summary.strip().rstrip(".!")
    s = re.sub(r"\b(a|an|the)\b\s*", "", s, flags=re.IGNORECASE)
    words = s.split()
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


def _label_from_operation_id(operation_id, path=None, method=None):
    """Returns a (label, is_trustworthy) pair. is_trustworthy=False means
    the caller should fall through to the path-heuristic tier instead of
    using this - fires when the operationId contains a raw path separator
    (a dead giveaway it's "{method}-{path}" baked into a string, like
    HubSpot's "get-/crm/v3/objects/0-3_getPage") or when every non-verb
    token in it is cryptic (numeric/param-shaped) with nothing readable
    left to build a label from.

    `path`/`method` (optional): used to disambiguate a bare 'get' verb
    into 'List' (collection-level) vs 'Get' (item-level) the same way the
    path-heuristic tier already does, and to decide when to singularize
    the resource - an operationId alone can't tell "GetCustomers" (list
    all) apart from "GetCustomer" (one record) if it always just says
    "Get" + plural resource, which several real specs do.
    """
    if "/" in operation_id or "{" in operation_id:
        return None, False

    tokens = _split_tokens(operation_id)
    if not tokens:
        return None, False

    verb_token = None
    verb_label = None
    resource_tokens = []
    for t in tokens:
        if t in _VERB_LABELS and verb_label is None:
            verb_token, verb_label = t, _VERB_LABELS[t]
        elif t not in _NOISE_TOKENS:
            resource_tokens.append(t)

    if not resource_tokens or all(_looks_cryptic(t) for t in resource_tokens):
        return None, False

    is_item_level = bool(path) and path.rstrip("/").split("/")[-1].startswith("{")
    if verb_token == "get" and path is not None:
        verb_label = "Get" if is_item_level else "List"

    resource_words = [w for w in resource_tokens if not _looks_cryptic(w)]
    if verb_label in ("Create", "Update", "Delete", "Get", "Archive") and (is_item_level or verb_label != "List"):
        # Singularize for anything acting on ONE record - matches the
        # path-heuristic tier's own rule. Skipped for "List" specifically
        # (a bare collection GET should stay plural: "List Customers").
        if resource_words:
            resource_words = resource_words[:-1] + [_singularize(resource_words[-1])]

    resource = " ".join(w.capitalize() for w in resource_words)
    if not resource:
        return None, False

    label = f"{verb_label} {resource}" if verb_label else resource
    return label, True


def _label_from_path(path, method):
    """Last-resort tier - always produces SOMETHING, but quality depends
    entirely on whether the path's own segments are semantic (usually
    yes: '/v1/contacts') or an opaque internal id (sometimes: HubSpot's
    '/crm/v3/objects/0-3') - a generic algorithm cannot recover a real
    name from the latter without external context (e.g. the curated
    product name from a manifest.json multi_file entry)."""
    method_l = method.lower()
    raw_segments = [seg for seg in path.split("/") if seg]
    is_item_level = bool(raw_segments) and raw_segments[-1].startswith("{")

    # A trailing verb-shaped segment (POST .../batch/archive,
    # .../{id}/void, .../{id}/merge) IS the actual action - not a resource
    # name to combine with the HTTP-method-derived verb. Detected first so
    # the resource scan below starts from BEFORE this segment instead of
    # mistaking "archive"/"void"/"merge" for the resource itself.
    explicit_verb = None
    scan_from = raw_segments
    last_non_param = next((s for s in reversed(raw_segments) if not s.startswith("{")), None)
    if last_non_param:
        last_tokens = [t for t in _split_tokens(last_non_param) if t not in _NOISE_TOKENS]
        verb_tokens = [t for t in last_tokens if t in _VERB_LABELS]
        if verb_tokens and last_non_param.lower() not in ("s",):
            explicit_verb = _VERB_LABELS[verb_tokens[-1]]
            cut = raw_segments.index(last_non_param)
            scan_from = raw_segments[:cut]

    resource = None
    for seg in reversed(scan_from):
        if seg.startswith("{"):
            continue
        tokens = [t for t in _split_tokens(seg) if t not in _NOISE_TOKENS]
        # Exclude verb-shaped tokens too ('batch', 'bulk', 'archive', ...) -
        # a generic REST-vocabulary segment like '.../batch/archive' would
        # otherwise let 'batch' get mistaken for the resource once
        # 'archive' is already claimed as the verb above.
        readable = [t for t in tokens if not _looks_cryptic(t) and t not in _VERB_LABELS]
        if readable:
            resource = " ".join(w.capitalize() for w in readable)
            break

    if resource is None:
        resource = "Item"
    elif explicit_verb or is_item_level or method_l != "get":
        # Singularize whenever we're naming a SPECIFIC item being acted on
        # (an explicit sub-action, an item-level path, or any non-GET) -
        # a bare collection-level GET is the one case that should stay
        # plural ('List Webhooks', not 'List Webhook').
        resource = _singularize(resource)

    if explicit_verb:
        verb = explicit_verb
    elif method_l == "get":
        verb = "Get" if is_item_level else "List"
    else:
        verb = _HTTP_METHOD_VERB.get(method_l, "Run")

    return f"{verb} {resource}"


def _apply_resource_hint(label, resource_hint):
    """
    Appends resource_hint to `label` as a disambiguating suffix — e.g.
    "Update Default" + hint "Deals" -> "Update Default (Deals)" — UNLESS
    the hint (or its singular form) is already present in the label, in
    which case it's left untouched.

    Why this exists: _generate_action_label's tier 1 (a usable multi-word
    `summary` straight from the vendor's spec) used to return immediately,
    before resource_hint was ever consulted at all — resource_hint was
    only wired into tier 3 (the path-heuristic last resort), on the
    assumption that a real spec-provided summary is trustworthy enough
    on its own. That assumption breaks for a vendor whose spec reuses
    the SAME generic templated summary across many structurally similar
    operations on different resources — confirmed live on HubSpot: ~115
    endpoints (one "update the default X" action per CRM object type)
    all carry an identical, resource-less summary, so every one of them
    produced the identical display_name even after schema_name identity
    was already fixed to be distinct per object. Filenames were unique;
    the UI picker showing them was not.

    Applied at every return point in _generate_action_label now, not
    just the old cryptic/"Item" path-heuristic branch, so a vendor's
    generic summary or operationId gets the same protection a cryptic
    path already had.
    """
    if not resource_hint:
        return label
    hint_l = resource_hint.lower()
    singular_hint_l = _singularize(resource_hint).lower()
    label_l = label.lower()
    if hint_l in label_l or singular_hint_l in label_l:
        return label
    return f"{label} ({resource_hint})"


def _generate_action_label(path, method, operation_id, summary, resource_hint=None):
    """
    Three-tier fallback producing a Zapier/Make/n8n-style action label
    ("Create Contact", "List Webhooks", "Delete Deal"), plus a source tag
    so a consuming UI/reviewer can tell how much to trust it - mirrors
    _infer_node_type's own (value, confidence) convention rather than
    returning a bare string a caller might mistake for verified fact.

    `resource_hint` (optional): a caller-supplied resource name - e.g.
    the curated product folder name from a manifest.json multi_file entry
    ("Deals") - substituted in when the auto-detected resource looks
    cryptic. This is the one case a generic algorithm genuinely cannot
    solve alone: HubSpot's own operationId AND path both only ever say
    "0-3", never "Deals" - only external curation context has that.

    A summary that's just a bare verb with no resource at all ("List",
    "Create" - genuinely present as-is on two real HubSpot Deals
    endpoints) is NOT trusted on its own: it's used as the preferred verb,
    combined with a resource pulled from a lower tier, rather than either
    emitted bare or discarded outright.
    """
    sparse_verb = None
    if summary:
        cleaned = _clean_summary(summary)
        words = cleaned.split()
        if len(words) > 1:
            return _apply_resource_hint(cleaned, resource_hint), "summary"
        if words and words[0] in _VERB_LABELS.values():
            sparse_verb = words[0]
        # else: empty after cleaning, or a single non-verb word - genuinely
        # nothing usable here, fall through to the next tier untouched.

    def _strip_leading_verb(label):
        parts = label.split()
        if parts and parts[0] in _VERB_LABELS.values():
            return " ".join(parts[1:])
        return label

    if operation_id:
        label, trustworthy = _label_from_operation_id(operation_id, path=path, method=method)
        if trustworthy:
            if sparse_verb:
                return _apply_resource_hint(f"{sparse_verb} {_strip_leading_verb(label)}", resource_hint), "summary+operation_id"
            return _apply_resource_hint(label, resource_hint), "operation_id"

    path_label = _label_from_path(path, method)
    if resource_hint and ("Item" in path_label.split() or _looks_cryptic(path_label.split()[-1].lower())):
        verb = sparse_verb or path_label.split()[0]
        hint = resource_hint if verb == "List" else _singularize(resource_hint)
        source = "summary+path_heuristic+hint" if sparse_verb else "path_heuristic+hint"
        return f"{verb} {hint}", source

    if sparse_verb:
        return _apply_resource_hint(f"{sparse_verb} {_strip_leading_verb(path_label)}", resource_hint), "summary+path_heuristic"

    return _apply_resource_hint(path_label, resource_hint), "path_heuristic"



def _resolve_first_created(out_file, current_timestamp, nested_under_metadata=True):
    """
    'first_created' must survive regeneration — every re-run overwrites the
    file wholesale, so without this every file's history would reset to
    'now' on every batch pass, making the field meaningless. If the file
    already exists on disk, read its own first_created back out (wherever
    it currently lives) and keep it; only a brand-new file gets stamped
    with the current run's timestamp.
    A missing, unreadable, or corrupt existing file is treated as brand
    new rather than failing the whole transpile over one bad prior file.
    """
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_value = (
                existing.get("metadata", {}).get("first_created")
                if nested_under_metadata
                else existing.get("first_created")
            )
            if existing_value:
                return existing_value
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return current_timestamp

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def map_openapi_type(prop_type):
    """Maps OpenAPI data types to your universal engine DSL types."""
    type_map = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list",
        "object": "dict"
    }
    return type_map.get(prop_type, "str")


def get_app_context(spec, base_output_dir="../schemas", category_override=None,
                     icon_url_override=None, color_override=None, app_name_override=None,
                     source_override=None, display_name_override=None):
    """
    🛠️ FIX: added category_override/icon_url_override/color_override/
    app_name_override. Without them this function ONLY ever finds a
    category/icon via `x-apisguru-categories`/`x-logo` on the spec's own
    `info` block - but those are APIs.guru-specific ENRICHMENT fields,
    added when APIs.guru aggregates a spec into their own catalog. A
    vendor's own spec (Stripe's own repo, Slack's own site - anything
    manifest.json points at directly) never carries them, so this always
    silently fell back to category="general" and icon_url="" for every
    manifest-driven app, even though manifest.json's hand-curated
    category/icon_url/color were sitting right there, unused, in the
    caller. When an override is given here, it wins outright - it's a
    deliberately curated value, not a fallback to reconcile with the
    spec's own (usually absent) metadata.

    source_override: provenance tag written into every schema's
    metadata.source (see _build_node_metadata / extract_oauth_config /
    extract_app_metadata). Defaults to "transpiled_official" - this
    function is the transpiler's own entry point, so anything running
    through it came from SOME machine-readable spec, not a human typing
    JSON by hand. Hand-authored schemas (a contributor reading docs and
    writing the file directly, per the community contribution model)
    never call get_app_context at all, so they're unaffected by this
    default - they simply write "community_authored" themselves.

    🛠️ FIX: added display_name_override, and ctx now always carries a
    "display_name". Previously extract_app_metadata() derived display_name
    ONLY from the spec's own info.title, completely independent of
    app_name_override — so two specs for the same manifest app could show
    different names in the UI (a rename in the vendor's spec, a
    differently-cased title on a mirror repo, HubSpot's per-product-file
    titles, etc.), and some titles are just verbose/inaccurate for a UI
    label ("HubSpot CRM API" instead of "HubSpot"). Precedence is now:
    explicit display_name_override wins outright; otherwise, if the app
    identity came from the manifest (app_name_override given), display_name
    IS that manifest key verbatim (the same value stored as app_name) —
    not a humanized/title-cased rewrite of it — so _meta.json's
    display_name always matches the manifest's own key exactly. Only a
    spec with no manifest-driven identity at all falls back to info.title.
    """
    info = spec.get("info", {})

    if category_override:
        primary_category = category_override
    else:
        categories = info.get("x-apisguru-categories", ["general"])
        primary_category = categories[0] if categories else "general"

    if app_name_override:
        app_name = app_name_override.lower()
    else:
        app_name = spec.get("x-providerName", info.get("title", "unknown_app")).lower()
    app_name = "".join([c if c.isalnum() else "_" for c in app_name])

    target_dir = os.path.join(base_output_dir, primary_category, app_name)
    
    servers = spec.get("servers") or [{}]
    base_url = servers[0].get("url", "")
    if not base_url:
        host = spec.get("host", "")
        base_path = spec.get("basePath", "")
        schemes = spec.get("schemes") or ["https"]
        if host:
            base_url = f"{schemes[0]}://{host}{base_path}"

    x_logo = info.get("x-logo", {})

    if display_name_override:
        display_name = display_name_override
    elif app_name_override:
        # 🛠️ FIX: was `display_name = app_name` — but app_name is the
        # lowercased + sanitized identifier used for the folder path/URL
        # segment (`app_name_override.lower()`, alnum-only, above), NOT
        # the manifest key as written. That made _meta.json's display_name
        # always lowercase even when manifest.json wrote the key in
        # Title/UPPER case. Using app_name_override directly here keeps
        # the identifier (app_name) URL-safe while display_name preserves
        # the manifest key's actual casing verbatim.
        display_name = app_name_override
    else:
        display_name = info.get("title", app_name)

    return {
        "info": info,
        "category": primary_category,
        "app_name": app_name,
        "display_name": display_name,
        "target_dir": target_dir,
        "base_url": base_url,
        "icon_url": icon_url_override or x_logo.get("url", ""),
        "color": color_override or x_logo.get("backgroundColor", ""),
        "source": source_override or "transpiled_official",
        "last_updated": _now_iso(),
    }


# ---------------------------------------------------------------------------
# UI metadata (for node rendering in a workflow-builder frontend)
# ---------------------------------------------------------------------------

# DSL DataType -> suggested form-input widget. Frontends are free to ignore
# this and pick their own widget per input_type; it's a sane default only.
INPUT_TYPE_MAP = {
    "str": "text",
    "int": "number",
    "float": "number",
    "bool": "checkbox",
    "list": "tags",
    "dict": "group",
}


def _humanize(name):
    """
    Handles snake_case, kebab-case, and camelCase alike, since OpenAPI specs
    mix all three: 'get_crm_v3_contacts' -> 'Get Crm V3 Contacts',
    'filterGroups' -> 'Filter Groups', 'hs_lead_status' -> 'Hs Lead Status'.
    """
    spaced = name.replace("_", " ").replace("-", " ")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return " ".join(word.capitalize() for word in spaced.split())


def _field_metadata(field_name, dsl_type, description="", required=False):
    return {
        "label": _humanize(field_name),
        "input_type": INPUT_TYPE_MAP.get(dsl_type, "text"),
        "description": description,
        "required": required,
    }


def _build_class_fields_metadata(parameters):
    """
    UI fields for path/query params — maps 1:1 onto the schema's top-level
    'class' object. Skips '_authorization': that name is reserved for the
    system-injected token (see the matching skip in transpile_endpoints'
    class_params loop) and must never surface as something a person fills in.

    🛠️ FIX: the reserved slot used to be plain "authorization" — a name
    real vendor APIs also use for their OWN path/query parameters (Stripe's
    Issuing Authorizations API has an "authorization" path param identifying
    which authorization to act on). That collided with the reserved system
    slot on every such endpoint, and the collision-handling code chose to
    protect the reserved slot — silently DROPPING the real API parameter
    rather than just failing to describe it in the UI. Renamed to the
    underscore-prefixed "_authorization" (a shape essentially no real OpenAPI
    spec uses for an actual parameter name) so a genuine vendor parameter
    named "authorization" is treated like any other normal field from here
    on — no collision, no silent drop.
    """
    fields = {}
    for param in parameters:
        param_name = param.get("name")
        param_in = param.get("in")
        if param_in not in ("path", "query") or param_name is None:
            continue
        if param_name.lower() == "_authorization":
            continue
        param_schema = param.get("schema", param)
        dsl_type = map_openapi_type(param_schema.get("type", "string"))
        fields[param_name] = _field_metadata(
            param_name,
            dsl_type,
            description=param.get("description", ""),
            required=bool(param.get("required", param_in == "path")),
        )
    return fields


def _build_body_fields_metadata(body_properties, required_fields=None):
    """UI fields for the request body — maps 1:1 onto the schema's top-level
    'body' object, recursing into nested objects the same way
    _build_body_payload() does.

    🛠️ FIX: `required_fields` now actually gets consulted instead of every
    field defaulting to False - previously this function had no way to
    know which properties were required at all, since transpile_endpoints
    only ever extracted `json_schema.get("properties", {})` and discarded
    the sibling `json_schema.get("required", [])` array before it reached
    here. OpenAPI scopes 'required' PER schema level, not globally - a
    nested object has its own independent required list - so this takes
    a fresh required_fields set for the CURRENT level only, and the
    recursive call for a nested object explicitly reads THAT nested
    object's own 'required' key rather than reusing the parent's.
    """
    required_fields = required_fields or set()
    fields = {}
    for prop_name, prop_details in body_properties.items():
        raw_type = prop_details.get("type", "string")
        items = prop_details.get("items")
        if raw_type == "object" and prop_details.get("properties"):
            fields[prop_name] = {
                "label": _humanize(prop_name),
                "input_type": "group",
                "description": prop_details.get("description", ""),
                "required": prop_name in required_fields,
                "fields": _build_body_fields_metadata(
                    prop_details["properties"],
                    set(prop_details.get("required", []) or []),
                ),
            }
        elif raw_type == "array" and isinstance(items, dict) and items.get("type") == "object" and items.get("properties"):
            # 🛠️ FIX: an array whose items are objects (e.g. HubSpot
            # search's 'filterGroups': [{filters: [{propertyName,
            # operator, value}]}]) used to fall through to the generic
            # scalar branch below and collapse into one opaque 'tags'
            # leaf with no visibility into propertyName/operator/value at
            # all — exactly what forced hand-written per-endpoint patch
            # files to exist for HubSpot-style search bodies instead of
            # the transpiler producing this automatically. 'array_group'
            # (distinct from plain 'group', a single nested object) tells
            # a UI this is a REPEATABLE nested section — render an "add
            # another" affordance over one instance of 'fields', not a
            # single fixed group.
            fields[prop_name] = {
                "label": _humanize(prop_name),
                "input_type": "array_group",
                "description": prop_details.get("description", ""),
                "required": prop_name in required_fields,
                "fields": _build_body_fields_metadata(
                    items["properties"],
                    set(items.get("required", []) or []),
                ),
            }
        else:
            dsl_type = map_openapi_type(raw_type)
            fields[prop_name] = _field_metadata(
                prop_name, dsl_type,
                description=prop_details.get("description", ""),
                required=prop_name in required_fields,
            )
    return fields

def _get_short_description(raw_desc):
    if not raw_desc:
        return ""
    
    # Take the first paragraph or first sentence
    first_sentence = raw_desc.split(". ")[0].strip()
    if not first_sentence.endswith("."):
        first_sentence += "."
        
    # If the first sentence is reasonably short, use it entirely
    if len(first_sentence) <= 140:
        return first_sentence
        
    # Otherwise, truncate cleanly at the last space before 137 chars + "..."
    truncated = first_sentence[:137].rsplit(" ", 1)[0]
    return truncated + "..."


def _load_patch(patches_root, category, app_name, schema_name):
    """
    Resolves against the same layout the source repo itself uses:
        connectors/<category>/<app_name>/patches/<schema_name>.json            (official)
        connectors/<category>/<app_name>/community/patches/<schema_name>.json  (community)

    Official wins OUTRIGHT when present — this is precedence, not a
    merge. A community patch is only ever consulted as a fallback for an
    endpoint the official patch set doesn't cover yet; it never layers on
    top of or modifies an official one. Matches this project's existing
    trust-tier language elsewhere (transpiled_official vs
    transpiled_community vs community_authored) rather than inventing a
    separate rule just for patches.

    Returns (patch_dict, tier) where tier is "official" or "community",
    or (None, None) if neither exists — the tier is threaded back to the
    caller so a patched schema can record WHICH trust level actually
    produced the correction it shipped with, the same way every other
    schema already records its own source.
    """
    if not patches_root:
        return None, None

    official_path = os.path.join(patches_root, category, app_name, "patches", f"{schema_name}.json")
    if os.path.isfile(official_path):
        with open(official_path, "r", encoding="utf-8") as f:
            return _expand_patch_shorthand(json.load(f)), "official"

    community_path = os.path.join(patches_root, category, app_name, "community", "patches", f"{schema_name}.json")
    if os.path.isfile(community_path):
        with open(community_path, "r", encoding="utf-8") as f:
            return _expand_patch_shorthand(json.load(f)), "community"

    return None, None


def _expand_patch_shorthand(patch):
    """
    Lets a patch's own "merge"/"override" class/body content be written
    in the SAME author-friendly shorthand hand-authored nodes already
    use (see _shorthand_to_placeholder's docstring) — a leaf shaped like
        {"type": "str", "default": "EQ", "required": true, "description": "..."}
    instead of the platform's raw
        "{{DataType=str, Default=EQ, Required=True}}"
    placeholder string PLUS a separate, identically-nested
    "metadata.fields.body...." tree just to attach that same field's
    description a second time. Both forms are accepted — including
    mixed within one patch, field by field — this is purely a
    normalization pass run once, here in _load_patch(), so every call
    site downstream keeps seeing exactly the same "real" placeholder-
    string shape it always has. A patch written entirely in the OLD
    form is untouched: _shorthand_to_placeholder only ever converts a
    dict with a string "type" key, and passes any plain string (an
    existing "{{...}}" placeholder, or a literal constant) straight
    through unchanged. A no-op for "_meta"/"_index" patches too, since
    those have no "class"/"body" keys to find.

    Descriptions pulled out of a shorthand leaf are seeded into
    patch["merge"]["metadata"]["fields"]["class"/"body"] via setdefault
    at every key, matching _complete_node_schema's own "explicit always
    wins" rule — a patch author who ALSO wrote an explicit
    metadata.fields entry for the same key (the old, verbose form) has
    that entry preserved untouched; the shorthand-extracted stub only
    ever fills a gap the author didn't already address by hand.

    Runs across BOTH "merge" and "override" — an override is still a
    wholesale replacement of the real class/body VALUE (see
    _shallow_override_into), but the shape its leaves are WRITTEN in is
    an orthogonal, independent choice; an override's fields still need
    the same normalization before apply_patch() sees them, and its
    extracted stubs still seed metadata.fields the exact same way. The
    override-triggered fields REBUILD itself (see extract_oauth_config/
    transpile_endpoints) separately consults these same seeded stubs
    instead of discarding them — see the "seed" handling at each of
    those call sites.

    Mutates and returns 'patch' in place — every caller already treats
    _load_patch()'s return value as disposable per-run data, never
    written back to disk, so there's no reason to allocate a fresh dict.
    """
    if not isinstance(patch, dict):
        return patch

    stubs = {"class": {}, "body": {}}
    for section_name in ("merge", "override"):
        section = patch.get(section_name)
        if not isinstance(section, dict):
            continue
        for block_name in ("class", "body"):
            block = section.get(block_name)
            if not isinstance(block, dict):
                continue
            for key, stub in _extract_shorthand_descriptions(block).items():
                stubs[block_name].setdefault(key, stub)
            section[block_name] = _shorthand_to_placeholder(block)

    if stubs["class"] or stubs["body"]:
        fields_section = patch.setdefault("merge", {}).setdefault("metadata", {}).setdefault("fields", {})
        for block_name in ("class", "body"):
            if not stubs[block_name]:
                continue
            existing = fields_section.setdefault(block_name, {})
            _deep_setdefault_merge(existing, stubs[block_name])

    return patch


def _deep_merge_into(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge_into(dst[key], value)
        else:
            # 🛠️ FIX: was a bare `dst[key] = value` — a patch value that's
            # a PARTIAL placeholder tag (e.g. "{{Required=False}}", no
            # DataType=/Default=) used to wholesale-replace whatever was
            # at dst[key], destroying the DataType=/Default= pieces an
            # existing placeholder there was carrying, even though the
            # patch author only meant to change one piece. See
            # _complete_partial_placeholder's own docstring.
            dst[key] = _complete_partial_placeholder(dst.get(key), value)
    return dst


def _shallow_override_into(dst, src):
    for key, value in src.items():
        dst[key] = value
    return dst


def _delete_keys(target, delete_patch):
    """
    Handles a patch's top-level "delete" key — a LIST of dotted key
    paths, e.g.:
        {"delete": ["body.map", "body.map.key", "class.someKey"]}
    Each path is walked segment by segment into target; every segment
    EXCEPT THE LAST just navigates deeper (target["body"]["map"], ...),
    and the FINAL segment is the key actually removed from whatever dict
    sits at that point. A bare single-segment path like "body" (no dot
    at all) walks zero segments and removes "body" straight off target
    itself — deleting the whole block. "body.map" walks into
    target["body"] and removes "map" from it. "body.map.key" walks into
    target["body"]["map"] and removes "key" from it, and so on to
    whatever depth the path names.

    Deliberately mirrors this file's existing "lists are wholesale,
    dicts are addressing" convention (see merge's own docstring):
    'delete' only ever removes DICT keys by name — it has no notion of a
    list index in the path, so it can't reach into a list-typed value
    (like filterGroups) to drop one element. If you want to shrink an
    actual LIST value itself, that's still 'merge' with a shorter
    replacement list.

    Path convention — write the REAL schema path, never
    "metadata.fields.*": target "class.someKey"/"body.someKey" (or a
    bare top-level key like "body") to delete a field, and this same
    delete list is automatically re-applied against
    metadata["fields"]["class"/"body"] too (see the call site in
    transpile_endpoints) — one entry keeps both the real request-
    building schema AND the UI form's field list in sync, with nothing
    extra to write or think about. "metadata.fields.body.someKey" is
    NOT a shortcut for that and won't work as its own path: at the point
    'delete' first runs, metadata["fields"] doesn't exist yet (it's
    built afterward by build_node_fields, from parameters/body_properties
    directly, oblivious to any patch), so that segment just silently
    no-ops. A top-level "metadata.<key>" path (e.g. "metadata.description")
    DOES work, since metadata's own base fields (display_name,
    description, icon_url, ...) already exist on the schema by the time
    'delete' runs — it's specifically the "fields" sub-tree that's
    special-cased and shouldn't be addressed directly.

    Fails gracefully at every step, on purpose: a segment that doesn't
    exist in target, doesn't lead to a dict, or a final key not actually
    present, is silently skipped for THAT path rather than raising —
    other paths in the same delete list are unaffected, and a delete
    patch should never break a transpile run just because the field it
    wanted gone was already gone.
    """
    for dotted_path in delete_patch:
        if not isinstance(dotted_path, str) or not dotted_path:
            continue  # malformed entry — ignored

        segments = dotted_path.split(".")
        container = target
        reached = True
        for segment in segments[:-1]:
            if not isinstance(container, dict) or segment not in container:
                reached = False
                break
            container = container[segment]

        if reached and isinstance(container, dict):
            container.pop(segments[-1], None)  # pop w/ default: no KeyError if already gone
    return target


def apply_patch(target: dict, patch: dict) -> dict:
    if "merge" in patch:
        _deep_merge_into(target, patch["merge"])
    if "delete" in patch:
        _delete_keys(target, patch["delete"])
    if "override" in patch:
        _shallow_override_into(target, patch["override"])
    return target


def _build_node_metadata(path, method, details, ctx, parameters, body_properties, required_fields=None, resource_hint=None):
    """
    UI-rendering metadata for one node (one endpoint schema). Kept as a
    single 'metadata' key so a consuming frontend can read display copy,
    icon/color, and the input form shape without touching 'class'/'body' —
    those stay pure request-construction data for the execution engine.

    'fields' is namespaced into 'class' and 'body' sub-objects, mirroring
    the schema's own top-level structure, rather than one flat dict. A
    path/query param and a body property can legitimately share the same
    literal name while holding two independent values (e.g. a URL 'id'
    identifying which record to update, and a body 'id' that's an
    unrelated external reference field on that record) — 'class' and
    'body' are already separate namespaces in the request itself, so the
    UI form mirrors that instead of silently collapsing them into one
    input and losing the second value's own description/type/required flag.
    """
    raw_desc = details.get("description", "")
    
    # Extract a concise short description (e.g., first paragraph or safe length truncation)
    short_desc = _get_short_description(raw_desc)

    display_name, display_name_source = _generate_action_label(
        path, method, details.get("operationId", ""), details.get("summary", ""),
        resource_hint=resource_hint,
    )

    node_type, node_type_confidence = _infer_node_type(
        path, method, details.get("operationId", ""),
        details.get("summary", ""), details.get("description", "")
    )

    return {
        "display_name": display_name,
        # 'summary' means OpenAPI's own human-authored text - trust as-is.
        # 'operation_id' means parsed from a verb_resource-shaped id.
        # 'path_heuristic'/'path_heuristic+hint' mean neither of those was
        # usable and this was derived from the URL alone (+hint: a caller-
        # supplied resource name filled in for a cryptic path segment) -
        # lowest confidence, worth a manual pass same as node_type_confidence.
        "display_name_source": display_name_source,
        "description": short_desc,                                      
        "learn_more": raw_desc if raw_desc != short_desc else None,
        # Preserved purely as a display/debugging hint now that schema_name
        # itself no longer derives from this — see _identity_for_operation's
        # docstring. The vendor's own operationId is still genuinely useful
        # for a human matching this file back to the vendor's own docs; it
        # just no longer has any bearing on the file's actual identity.
        # None (not "") when the vendor's spec didn't provide one at all.
        "operation_id": details.get("operationId") or None,
        "icon_url": ctx["icon_url"],
        "color": ctx["color"],
        "category": ctx["category"],
        "node_type": node_type,
        # 'heuristic' means guessed from path/method keywords — treat as a
        # starting point, not verified fact; a manual pass that confirms
        # or corrects it should overwrite this to 'verified' (see README/
        # CONTRIBUTING for the review workflow) so verified and unverified
        # nodes are distinguishable across the catalog rather than looking
        # equally authoritative.
        "node_type_confidence": node_type_confidence,
        # "transpiled_official" (default) | "transpiled_community" |
        # "community_authored" — trust-level tag distinct from
        # node_type_confidence: that field is about whether the ACTION
        # TYPE was guessed correctly, this one is about WHERE the schema's
        # content came from at all. Set via manifest.json's per-app
        # source_override (see batch_transpile_manifest.py) for anything
        # sourced from a community-maintained repo rather than the
        # vendor's own; hand-authored files never reach this function at
        # all, so a human writes "community_authored" directly instead.
        "source": ctx["source"],
        "last_updated": ctx["last_updated"],
    }

# Fix the _build_node_netadata function had the fields keys block populated and created after all patches is completeted

def build_node_fields(metadata: dict, parameters, body_properties, required_fields):
    
    metadata["fields"] = {
        "class": _build_class_fields_metadata(parameters),
        "body": _build_body_fields_metadata(body_properties, required_fields),
    }


_PLACEHOLDER_RE = re.compile(r"^\{\{(.+)\}\}$")


def _parse_placeholder_tag(value):
    """
    Parses this DSL's own '{{DataType=X, Default=Y, Required=Z}}' syntax
    back out of a string — the inverse of _build_param_placeholder's own
    string-building. Returns None for anything that isn't a placeholder
    (a patch may set a field to a literal, non-templated value directly,
    e.g. "company": "Acme Inc") — callers treat that as a pre-filled
    constant, not something needing a DataType/Required breakdown.
    """
    if not isinstance(value, str):
        return None
    match = _PLACEHOLDER_RE.match(value.strip())
    if not match:
        return None
    tag = {}
    for part in match.group(1).split(","):
        if "=" not in part:
            continue
        key, _, val = part.strip().partition("=")
        tag[key.strip()] = val.strip()
    return tag


def _complete_partial_placeholder(existing_value, patched_value):
    """
    Gap-fills a PARTIAL placeholder patch value against whatever
    placeholder already lived at that key, so a patch meant to change
    only ONE piece (typically "{{Required=False}}") doesn't wholesale-
    destroy the OTHER pieces (DataType=/Default=) an existing placeholder
    there was carrying — exactly the failure mode called out in
    _reconcile_fields_with_patched_values' own history: it correctly
    updates metadata.fields' displayed input_type/required from a partial
    tag, while the REAL executable value used to be a flat string
    replacement with no such gap-filling — so metadata and the actual
    request-builder could tell two different stories about the same
    field. Called from _deep_merge_into's leaf-assignment branch only —
    'override' is a wholesale block replacement by design (see
    _shallow_override_into), so there's no meaningful "existing value" a
    single override leaf could be borrowing missing pieces from.

    Only ever fills GAPS: any DataType=/Default=/Required= the patch DOES
    specify always wins over what existing_value had — this never
    overrides a part of the patch actually asked to change, only
    supplies parts it left unmentioned.

    Returns patched_value completely UNCHANGED (no gap-filling at all)
    whenever:
      - patched_value isn't a placeholder tag at all — a literal
        constant patch value (e.g. "company": "Acme Inc") is a
        deliberate, intentional wholesale replacement, not a partial
        edit, and is left alone.
      - existing_value isn't itself a usable placeholder to borrow
        pieces from (a brand-new patch-introduced field, or one that was
        already a literal constant) — nothing to fill gaps FROM, so the
        patch's own (possibly partial) tag is used as-is, same as before
        this fix.

    One known limitation, inherent to using presence/absence in a
    string to mean "unspecified": there's no way to tell "the patch
    didn't mention Default=" apart from "the patch wants to CLEAR an
    existing Default=". Omitting Default= in a partial patch always
    means "leave whatever was already there" — to actually remove a
    previously-set default, write out the full placeholder explicitly.
    """
    patched_tag = _parse_placeholder_tag(patched_value)
    if patched_tag is None:
        return patched_value  # not a placeholder-shaped patch — leave as-is

    existing_tag = _parse_placeholder_tag(existing_value)
    if existing_tag is None:
        return patched_value  # nothing to borrow missing pieces from

    merged_tag = dict(existing_tag)
    merged_tag.update(patched_tag)  # anything the patch DOES specify wins

    parts = []
    for tag_key in ("DataType", "Default", "Required"):  # canonical order
        if tag_key in merged_tag:
            parts.append(f"{tag_key}={merged_tag[tag_key]}")
    for tag_key, tag_val in merged_tag.items():  # any non-standard tag keys, preserved too
        if tag_key not in ("DataType", "Default", "Required"):
            parts.append(f"{tag_key}={tag_val}")

    return "{{" + ", ".join(parts) + "}}"


def _infer_field_from_value(key, value):
    """
    Best-effort field descriptor for a key that exists in a PATCHED
    class/body dict but has no corresponding entry from the original
    OpenAPI parameters/properties — a patch-introduced field (HubSpot's
    filterGroups is the motivating case: a real, accepted request field
    that no per-endpoint OpenAPI schema documents). Not as complete as a
    hand-authored one (no human description, no author-supplied
    rationale) — but the DataType/Required a placeholder tag carries IS
    real signal, so this surfaces the field rather than leaving it
    invisible in metadata.fields entirely. A patch's own
    "metadata.fields.*" (metadata is itself patchable — see apply_patch's
    call site in transpile_endpoints) is still how to give a
    patch-introduced field a proper human description if one's needed;
    this only guarantees the field EXISTS in the form shape at all.
    """
    tag = _parse_placeholder_tag(value)
    if tag is not None:
        dsl_type = tag.get("DataType", "str")
        required = tag.get("Required", "").lower() == "true"
        return _field_metadata(key, dsl_type, description="", required=required)

    if isinstance(value, dict):
        return {
            "label": _humanize(key), "input_type": "group",
            "description": "", "required": False,
            "fields": _reconcile_fields_with_patched_values({}, value),
        }
    if isinstance(value, list):
        # 🛠️ FIX: this used to collapse EVERY list into one opaque "list"
        # leaf, with no nested "fields" at all — meaning a field nested
        # inside an array-of-objects (HubSpot filterGroups'
        # propertyName/operator/value) had NO metadata.fields destination
        # whatsoever: no label, no description, nothing, at any depth
        # below the array itself. Brought up to parity with what the
        # TRANSPILER's own _build_body_fields_metadata already does for a
        # real OpenAPI array-of-objects: "array_group" (distinct from
        # plain "group" — tells a UI this is a REPEATABLE nested section,
        # render an "add another" affordance over one instance of
        # "fields", not a single fixed group), with "fields" inferred
        # from the array's first element. Every element in this DSL's
        # arrays is expected to share one shape — the same "one-element
        # template array" convention _build_body_payload itself already
        # documents — so the first element is representative of all of
        # them; there's deliberately no attempt to merge shapes across
        # multiple, possibly-differently-shaped elements.
        if value and isinstance(value[0], dict):
            return {
                "label": _humanize(key), "input_type": "array_group",
                "description": "", "required": False,
                "fields": _reconcile_fields_with_patched_values({}, value[0]),
            }
        return _field_metadata(key, "list", description="", required=False)

    # A literal, pre-filled constant (not a placeholder) — still worth a
    # field entry so the UI shows what the patch actually set, even
    # though there's nothing left to fill in.
    return _field_metadata(key, "str", description="", required=False)


def _backfill_field_descriptor(existing_entry, key, value):
    """
    Fills in whichever of label/input_type/description/required
    'existing_entry' is missing, using a fresh _infer_field_from_value()
    derivation as the source — and touches NOTHING existing_entry
    already has. Lets a patch author write metadata.fields.<key> with
    just the one piece they actually care about (almost always just
    "description") instead of having to restate the whole descriptor
    (label/input_type/required/fields) purely to avoid losing it: those
    get auto-derived the same way an un-patched field already would be,
    exactly as if the author had written them out by hand.

    Deliberately mutates existing_entry in place rather than returning a
    new dict — every call site here is about to keep using
    fields_dict[key] (recursing into its "fields", or syncing
    input_type/required from a tag next), so the object identity has to
    survive this call.
    """
    if not isinstance(existing_entry, dict):
        return
    derived = _infer_field_from_value(key, value)
    for meta_key in ("label", "input_type", "description", "required"):
        existing_entry.setdefault(meta_key, derived[meta_key])


def _deep_setdefault_merge(dst, src):
    """
    Recursively fills in whichever keys 'src' has that 'dst' doesn't, at
    EVERY level of nesting — never overwrites a key 'dst' already
    defines, no matter how deep. Used by _expand_patch_shorthand() to
    merge shorthand-extracted description stubs into whatever explicit
    metadata.fields content a patch author already wrote by hand.

    A plain top-level setdefault() isn't enough here: if the author
    already wrote SOME explicit content for a key (say,
    metadata.fields.body.filterGroups, to describe filterGroups itself
    or one specific field nested inside it), a shallow setdefault sees
    that key as "already present" and skips it entirely — silently
    dropping every SIBLING description the shorthand extraction found
    nested deeper inside that same key (e.g. a different field, several
    levels down, that the author described inline via shorthand instead
    of by hand) purely because they share a common ancestor key. This
    recurses through matching dict keys instead, so only genuinely
    already-authored leaves are left untouched — everything the author
    didn't mention, at any depth, still gets filled in.
    """
    for key, value in src.items():
        if key not in dst:
            dst[key] = value
        elif isinstance(dst[key], dict) and isinstance(value, dict):
            _deep_setdefault_merge(dst[key], value)
    return dst


def _merge_patch_field_stubs(fields_dict, stub_dict):
    """
    Restores metadata.fields entries a patch's own "merge" step already
    deposited into metadata.fields moments earlier (an author-written
    entry, or one _expand_patch_shorthand() extracted from an inline
    shorthand description) AFTER build_node_fields() has unconditionally
    rebuilt metadata["fields"] from scratch off the ORIGINAL, un-patched
    OpenAPI schema — see build_node_fields' own call site comment for
    why that rebuild has to run where it does (after the patch, not
    before), and why simply skipping or reordering around it isn't an
    option: that rebuild fixed a real, earlier bug of its own.

    Without this, apply_patch()'s merge step still deposits the stub
    correctly (metadata["fields"] doesn't exist yet at that point, so it
    lands cleanly) — but build_node_fields() runs immediately after and
    reassigns metadata["fields"] to an entirely fresh dict derived only
    from the real API's parameters/body_properties, silently discarding
    it a moment later. A patch-introduced field (one no OpenAPI schema
    documents at all, like HubSpot search's filterGroups) has NO entry
    in that fresh dict for its stub to even land on, so it isn't merged
    back in by anything downstream either — the override/reconcile step
    that runs after this can supply DataType/Required for such a field
    from its real value, but has no way to recover a description that
    already went missing before it got a chance to run.

    For a key build_node_fields DID derive for real (a genuine OpenAPI
    parameter/body property): only the specific label/input_type/
    description/required keys the stub explicitly carries are applied,
    same "author's explicit key always wins outright, anything they
    didn't mention is left alone" rule used everywhere else a patch
    touches this codebase's derived data.

    For a key build_node_fields has no entry for at all (a patch-
    introduced field): the stub is inserted outright — there's no real
    derivation underneath it to preserve, and the reconcile step right
    after this call fills in input_type/required from the patch's own
    real class/body value the same way it already does for any other
    patch-introduced field.
    """
    for key, stub in (stub_dict or {}).items():
        if not isinstance(stub, dict):
            continue
        if key in fields_dict:
            for meta_key in ("label", "input_type", "description", "required"):
                if meta_key in stub:
                    fields_dict[key][meta_key] = stub[meta_key]
            if isinstance(stub.get("fields"), dict) and isinstance(fields_dict[key].get("fields"), dict):
                _merge_patch_field_stubs(fields_dict[key]["fields"], stub["fields"])
        else:
            fields_dict[key] = stub


def _rebuild_overridden_fields(existing_fields, real_values):
    """
    Rebuilds a metadata.fields.class/body block for an 'override'd
    class/body — same "wholesale, not partial" semantics the override
    already has for the real value (see _shallow_override_into): any
    field NOT in the new real_values is dropped here too, matching the
    override itself discarding whatever it replaced.

    🛠️ FIX: used to rebuild via a blind {key: _infer_field_from_value(...)
    for key, value in real_values.items()} comprehension — correct for
    label/input_type/required (those only ever come from real_values
    itself, which is exactly what _infer_field_from_value derives them
    from), but it always produced description="" unconditionally, with
    no way for a patch to supply real text for an overridden field.
    Seeded here from 'existing_fields' instead — whatever apply_patch's
    own "merge" step already deposited into metadata.fields moments
    earlier (a patch author's own explicit entry, or a stub
    _expand_patch_shorthand() extracted from an inline shorthand
    description) — filtered down to only keys that still exist in the
    new real_values (so a stale/unrelated old entry can't leak through
    just because it happened to still be sitting in existing_fields),
    then run through the same _reconcile_fields_with_patched_values()
    backfill every other patched field already goes through — a seed
    entry with only "description" still ends up with a complete
    label/input_type/required, exactly as if it had been hand-derived.
    """
    seed = {
        key: stub for key, stub in (existing_fields or {}).items()
        if key in real_values
    }
    return _reconcile_fields_with_patched_values(seed, real_values)


def _reconcile_fields_with_patched_values(fields_dict, patched_dict):
    """
    Two separate jobs, not one:

    1. Adds a full field descriptor for any key in 'patched_dict' that
       'fields_dict' doesn't have at all — a patch-introduced field
       (HubSpot's filterGroups is the motivating case). Unchanged from
       the original version of this function.

    2. For a key BOTH already have: if the patched value is one of this
       DSL's own '{{DataType=X, Required=Z}}' placeholders, syncs
       'input_type'/'required' from that tag into the EXISTING entry.
       Without this, a patch that changes an EXISTING field's
       Required=True to Required=False (or its DataType) left
       metadata.fields silently disagreeing with the actual body/class
       the request gets built from — proved concretely: patching
       body.name from Required=True to Required=False changed the real
       placeholder correctly, but metadata.fields.body.name.required
       stayed stuck at True, meaning the rendered form would still show
       the field as mandatory (or the opposite failure mode: silently
       became actually-required with the form still showing it as
       optional, so a submission fails with a confusing missing-field
       error nothing in the form warned about).

    Deliberately does NOT touch 'label'/'description' on an existing
    entry, even while syncing input_type/required — those came from
    either the original OpenAPI schema or a deliberate
    'metadata.fields.<key>' patch (metadata is independently patchable —
    see apply_patch's call site), and a bare placeholder tag carries no
    replacement text for them. Blanking a real description out just
    because a patch changed Required= would be a regression, not a fix.

    Recurses into an existing nested 'group' entry's own 'fields' too,
    so a patch reaching into an EXISTING nested object's field (not just
    a top-level one) gets the same treatment.
    """
    for key, value in patched_dict.items():
        if key not in fields_dict:
            fields_dict[key] = _infer_field_from_value(key, value)
            continue

        tag = _parse_placeholder_tag(value)
        if tag is not None:
            # 🛠️ FIX: a patch's metadata.fields.<key> merge used to have
            # to restate the FULL descriptor (label/input_type/required/
            # description) just to change one piece — anything the
            # author didn't explicitly write (most commonly: they only
            # wanted to add a 'description') came out MISSING from the
            # output entirely, not just left at some prior default,
            # because fields_dict[key] here is whatever the patch's own
            # "merge" step deposited moments earlier, which for a
            # patch-introduced key is only ever exactly what the author
            # wrote — nothing auto-derives the rest first. setdefault()
            # backfills anything the author didn't mention from a fresh
            # derivation, while never touching a key they DID set
            # (including this same tag-sync's own DataType/Required
            # below, which still always wins for input_type/required
            # specifically, same as before this fix).
            _backfill_field_descriptor(fields_dict[key], key, value)
            if "DataType" in tag:
                fields_dict[key]["input_type"] = INPUT_TYPE_MAP.get(
                    tag["DataType"], fields_dict[key]["input_type"]
                )
            if "Required" in tag:
                fields_dict[key]["required"] = tag["Required"].lower() == "true"
        elif isinstance(value, dict) and isinstance(fields_dict[key].get("fields"), dict):
            _backfill_field_descriptor(fields_dict[key], key, value)
            _reconcile_fields_with_patched_values(fields_dict[key]["fields"], value)
        elif (
            isinstance(value, list) and value and isinstance(value[0], dict)
            and isinstance(fields_dict[key].get("fields"), dict)
        ):
            # 🛠️ FIX: an existing "array_group"/"group" field being
            # reconciled against a patched LIST used to fall straight
            # through to the catch-all rebuild below — meaning ANY patch
            # touching an array-of-objects field, at ANY depth, always
            # threw away its existing "fields" (and every human
            # description/label an author had written anywhere inside
            # them) and rebuilt from a blank slate via
            # _infer_field_from_value instead of actually reconciling.
            # Mirrors the dict/"group" branch immediately above, one
            # level of indirection down: recurse into the array's own
            # "fields" using its first element as the patched_dict, same
            # "first element is representative of all of them"
            # convention _infer_field_from_value/_build_body_payload
            # already use.
            _backfill_field_descriptor(fields_dict[key], key, value)
            _reconcile_fields_with_patched_values(fields_dict[key]["fields"], value[0])
        else:
            # 🛠️ FIX: this used to silently do nothing for any patched
            # value that was neither a placeholder tag NOR a dict merging
            # into an ALREADY-group-typed field. Concretely, a merge that
            # changes an EXISTING field into a literal constant (e.g.
            # "company": "Acme Inc", no {{...}} tag), or into a dict when
            # it wasn't previously 'group'-typed, or into a list when it
            # wasn't previously 'list'-typed, left the OLD field
            # descriptor completely stale — wrong input_type, wrong
            # required, and for the literal-constant case specifically,
            # the UI kept showing an editable input for a field the real
            # request-builder now hardcodes and silently ignores. Any
            # patched value landing here no longer matches what the
            # existing descriptor was built to describe, so it's rebuilt
            # fresh from the patched value instead of left untouched.
            #
            # 🛠️ FIX: rebuilding used to DISCARD whatever the OLD entry
            # had for label/description/required/input_type outright —
            # including anything a patch author had explicitly written
            # into metadata.fields.<key> moments earlier via "merge",
            # since THIS is exactly the branch a patch-introduced,
            # shape-mismatched (no matching "fields") field lands in.
            # Concretely: a patch that merges body.filterGroups (a new
            # list-of-dicts) alongside metadata.fields.body.filterGroups
            # = {"description": "..."} (author wrote description only,
            # no "fields" sub-tree) used to land here and lose that
            # description entirely, back to "". Old entry's authored
            # keys now carry over onto the freshly-derived skeleton
            # instead of being thrown away.
            old_entry = fields_dict.get(key)
            derived = _infer_field_from_value(key, value)
            if isinstance(old_entry, dict):
                for meta_key in ("label", "input_type", "description", "required"):
                    if meta_key in old_entry:
                        derived[meta_key] = old_entry[meta_key]
            fields_dict[key] = derived
    return fields_dict

# ---------------------------------------------------------------------------
# 1. Endpoint schemas
# ---------------------------------------------------------------------------

def _format_default_value(value):
    """Booleans render lowercase ('true'/'false') to match this DSL's
    established convention elsewhere; everything else is a plain str()."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_param_placeholder(dsl_type, required, default_value=None):
    """
    Builds a self-describing '{{DataType=X, Default=Y, Required=Z}}'
    placeholder for a path/query/header/cookie parameter — plain string
    concatenation, not an f-string, so there's no risk of the
    double-brace escaping mistake fixed earlier in this file's history.

    'Required' is the piece that was missing entirely: without it, the
    interpreter's build_schema() had no way to tell "the user left this
    blank and it's fine to omit" (a genuinely optional query flag like
    Asana's opt_pretty/opt_fields) apart from "the user left this blank
    and the request is now broken" (a missing required field) — every
    placeholder with no Default= was being treated as unconditionally
    required, regardless of what the OpenAPI spec or this DSL's own
    metadata.fields.*.required actually said.

    Note what's deliberately NOT here: a 'Location' tag. The interpreter
    already infers path-vs-query correctly by checking which 'class'
    keys get consumed as {name} references inside the url/headers
    templates — genuinely required ones are consumed, query params
    aren't referenced anywhere so they're structurally identifiable by
    elimination. Adding an explicit Location tag would just be a second,
    redundant source of truth nothing actually reads.
    """
    parts = [f"DataType={dsl_type}"]
    if default_value is not None:
        parts.append(f"Default={_format_default_value(default_value)}")
    parts.append(f"Required={'True' if required else 'False'}")
    return "{{" + ", ".join(parts) + "}}"


def _build_body_payload(properties, required_fields=None):
    """
    Recursively converts an OpenAPI 'properties' object into the universal
    DSL body shape. Nested objects (e.g. HubSpot's top-level 'properties'
    wrapper around the actual updatable fields) are unpacked one level at
    a time rather than collapsed into a single '{{DataType=dict}}' leaf,
    so the output matches update_contact.json's nested body.properties.*.

    A leaf whose OpenAPI schema declares a 'default' is pre-filled with
    that literal value instead of a placeholder — uses `"default" in
    prop_details` rather than truthiness, since a real, meaningful
    default can itself be falsy (0, False, "").

    🛠️ FIX (Required=): every OTHER leaf (no spec default) now carries a
    'Required=' tag via _build_param_placeholder(), the same helper
    path/query/header/cookie params already use — previously this
    function only ever emitted a bare '{{DataType=X}}' with no Required=
    tag at all, regardless of what metadata.fields.body[name].required
    said. build_schema() in interpreter.py treats a MISSING Required=
    tag as "required" (the safe default, protecting old schemas from a
    field silently going missing) — which meant every optional body
    field on every newly generated schema was silently caught by that
    same fallback too. required_fields is threaded through recursively
    the same way _build_body_fields_metadata already does: each nested
    object's OWN 'required' list applies only within that nesting level.

    🛠️ FIX (arrays of objects): an array whose items are objects (e.g.
    HubSpot search's 'filterGroups': [{filters: [{propertyName,
    operator, value}]}]) used to collapse into one opaque
    '{{DataType=list}}' leaf — no visibility into the nested fields at
    all, forcing hand-written per-endpoint patch files for anything
    shaped like a HubSpot search body. Represented here as a one-element
    template array — [{...}] — so the nested shape (and each leaf's own
    DataType/Required placeholder) is present and resolvable, and an
    interpreter/UI can treat that one element as the repeatable unit for
    an "add another" affordance. Mirrors _build_body_fields_metadata's
    'array_group' handling — same structural gap, same fix, on the
    execution side rather than the UI side.
    """
    required_fields = required_fields or set()
    payload = {}
    for prop_name, prop_details in properties.items():
        raw_type = prop_details.get("type", "string")
        nested_properties = prop_details.get("properties")
        items = prop_details.get("items")
        if raw_type == "object" and nested_properties:
            payload[prop_name] = _build_body_payload(
                nested_properties, set(prop_details.get("required", []) or [])
            )
        elif raw_type == "array" and isinstance(items, dict) and items.get("type") == "object" and items.get("properties"):
            payload[prop_name] = [
                _build_body_payload(items["properties"], set(items.get("required", []) or []))
            ]
        elif "default" in prop_details:
            payload[prop_name] = prop_details["default"]
        else:
            mapped_type = map_openapi_type(raw_type)
            payload[prop_name] = _build_param_placeholder(mapped_type, prop_name in required_fields)
    return payload

def _env_token_var(app_name):
    """
    Deterministic, per-provider env var name (e.g. 'hubapi_com' -> 'HUBAPI_COM_TOKEN').
    Using app_name (already unique — it's the same key backing target_dir)
    instead of a single shared 'ServiceToken' means every provider's
    generated schemas point at their own credential, not one shared value
    that different apps would silently collide on in production.
    Note: this won't match a hand-picked brand name like '$env.Hubspot' —
    OpenAPI specs don't reliably expose a "friendly" provider name, only
    the domain-derived one — but it's unique and predictable, which is
    what actually matters for correctness at scale.
    """
    return f"{app_name.upper()}_TOKEN"


def _safe_schema_name(raw_name: str, max_len: int = 80) -> str:
    """
    Caps a sanitized schema_name at max_len characters, appending a short
    deterministic hash so truncating two different long names can't
    collide them into the same file.

    Written for a real build failure: Google's Discovery-derived specs
    occasionally publish operationIds well over 100 characters for
    methods whose REST path legitimately chains two full resource paths
    together (e.g. assuredworkloads' analyzeWorkloadMove, which takes a
    full source AND target organizations/locations/workloads path —
    confirmed against Google's own API changelog, not a parsing bug on
    this side). Combined with a real install path
    (build\\bdist.win-amd64\\wheel\\...\\schemas\\<category>\\<app>\\), an
    uncapped name like that pushes the full path past Windows' default
    260-character MAX_PATH and 'pip wheel' fails with a bare
    "No such file or directory" that gives no hint the real cause is
    filename length. Short names (the overwhelming majority) pass
    through completely unchanged — this only ever activates once a name
    is already over the limit, so it doesn't change any existing
    schema's filename.
    """
    if len(raw_name) <= max_len:
        return raw_name
    import hashlib
    digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:8]
    prefix = raw_name[: max_len - len(digest) - 1]
    return f"{prefix}_{digest}"


_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")


def _identity_for_operation(method, path, resource_hint=None):
    """
    Canonical identity source for schema_name — method + a param-NAME-
    normalized path, deliberately NOT operationId.

    resource_hint (optional): folded onto the end of the identity,
    unconditionally, whenever the caller supplies one — NOT only when a
    collision is detected. Detecting collisions would make identity
    depend on which other files happen to run in the same batch and in
    what order, which is exactly the instability this function exists
    to avoid (see the operationId reasoning below). A multi-file spec
    (HubSpot's per-object files being the motivating case) gives every
    operation a resource_hint unconditionally for the same reason: many
    of those files share one generic, param-normalized path shape
    (HubSpot's own operationId AND URL path only ever say a version
    token for the object, never e.g. "Deals" — see
    _resource_hint_from_relative_path()'s docstring), so without a
    resource-level disambiguator here, 29 distinct object endpoints
    collapse onto one schema_name and every write after the first
    silently overwrites the one before it.

    Why this matters: operationId is only required by the OpenAPI spec
    to be unique WITHIN one document — nothing obligates it to stay the
    same ACROSS spec revisions, and vendors rename it constantly for
    entirely cosmetic reasons (a codegen tool change, an internal
    refactor, splitting one spec into per-resource files — HubSpot's own
    manifest source already does the latter). None of that changes the
    actual request. But schema_name IS the on-disk filename, and every
    one of the following is keyed off it staying stable: _load_patch(),
    _load_node(), _resolve_first_created() (reads the OLD file at this
    exact path to preserve its first_created), write_schema_index()'s
    published list, and — the one that actually matters to an end user —
    the SDK's own `action` parameter (getInputForm/buildSchema take this
    string directly; a user's saved automation referencing an action by
    name goes silently orphaned the moment operationId changes upstream
    for reasons that have nothing to do with the request itself).

    method+path is the actual contract instead — it's literally what
    becomes 'url'/'method' in the output schema — so it only changes
    identity when the real request changes, which is exactly when a NEW
    identity should be assigned.

    Path PARAM NAMES are normalized away too, for the identical reason:
    "/v1/contacts/{contactId}" and "/v1/contacts/{id}" are the same
    endpoint, and a vendor renaming the param is just as cosmetic as
    renaming operationId. Every "{...}" segment collapses to the same
    fixed token regardless of what's inside it, so a param rename alone
    can never change the resulting identity.

    Trailing slashes are stripped too, same reasoning: "/v1/contacts"
    and "/v1/contacts/" are the same route on the overwhelming majority
    of real APIs, and a vendor adding or dropping one between spec
    revisions is exactly as cosmetic as an operationId rename. The root
    path "/" itself is the one deliberate exception — rstrip("/") on it
    alone would otherwise collapse to an empty string.

    operationId isn't gone — _generate_action_label()/_infer_node_type()
    still read it straight off `details` for display-label purposes,
    where a vendor's own human-chosen name is genuinely useful — it's
    only removed from the identity/filename role, where its lack of any
    cross-revision stability guarantee made it a liability. See
    _build_node_metadata's "operation_id" field for where it's preserved
    as a pure display hint on the generated schema itself.
    """
    normalized_path = path.rstrip("/") or "/"
    normalized_path = _PATH_PARAM_RE.sub("_id_", normalized_path)
    raw = f"{method.lower()}{normalized_path}"
    if resource_hint:
        raw = f"{raw}_{resource_hint}"
    return "".join(c if c.isalnum() else "_" for c in raw).lower()


def _urlopen_read_with_retry(req, timeout, max_attempts=3, label=""):
    """
    Reads a full response body with retries against http.client.IncompleteRead
    specifically — confirmed against a real failure, twice in a row,
    both truncated at exactly 294912 bytes despite different amounts
    remaining each time. That exact-byte-count repeatability across two
    separate connections points at something structural between the
    client and GitHub (a corporate/AV proxy doing HTTPS inspection with
    a buffering cap, a content filter capping response size) rather
    than ordinary transient network flakiness — which a blind retry on
    a FRESH connection may or may not survive, but is still the right
    first thing to try, since urllib gives no partial-resume capability
    here (IncompleteRead's partial bytes aren't valid JSON on their own,
    so there's nothing to resume from — every retry re-fetches the
    entire response from scratch).

    If every attempt fails the SAME way, that's itself diagnostic
    information the caller's own log line should surface: something in
    the network path is deterministically capping response size, and no
    amount of client-side retrying fixes a server/proxy-side cap — the
    real fix at that point is investigating the network path itself
    (temporarily disabling AV/HTTPS-inspection to confirm, or an
    exclusion for api.github.com), not more retries.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except http.client.IncompleteRead as e:
            last_error = e
            if attempt < max_attempts:
                wait = 2 ** attempt
                print(f"⚠️  {label}: response truncated (attempt {attempt}/{max_attempts}), retrying in {wait}s — {e}")
                time.sleep(wait)
    print(
        f"❌ {label}: response truncated the same way on all {max_attempts} attempts — "
        "this looks like something in your network path (a corporate/AV proxy doing "
        "HTTPS inspection, a content filter capping response size) is consistently "
        "truncating this download, not random network flakiness. Try again from a "
        "different network, or temporarily disable HTTPS/web scanning in your "
        "antivirus to confirm before assuming it's this tool."
    )
    raise last_error


def fetch_patches_from_repo(repo, ref="main", patches_subdir="connectors", dest_dir="patches", timeout=15):
    """
    Downloads every file under '<repo>/<patches_subdir>' at 'ref' into
    'dest_dir', preserving the exact on-disk layout _load_patch() already
    expects:
        connectors/<category>/<app_name>/patches/<schema_name>.json
        connectors/<category>/<app_name>/community/patches/<schema_name>.json
    (and, incidentally, connectors/.../nodes/ and .../community/nodes/
    too — this walks the whole 'connectors' subtree generically rather
    than special-casing 'patches' specifically, so hand-authored node
    files land locally ready for whenever node consumption is wired up,
    without needing a second fetch mechanism later.)

    This is purely a one-time (or explicitly re-run) sync step, not
    something transpile_endpoints itself ever calls. Deliberately NOT
    wired into transpile_endpoints —
    _load_patch() does a local filesystem check per endpoint (potentially
    hundreds of times per app); hitting GitHub's API that often would be
    hundreds of round-trips per run for what a single 'git pull' (or one
    call to this function) already solves. Call this explicitly, once,
    whenever you actually want to refresh your local patches/ tree —
    mirrors how manifest.json/schemas/ already work in this project
    (clone/pull once, everything downstream reads local files).

    Uses GitHub's recursive git-trees API (one call gets the full file
    list) rather than the contents API (one call per directory) — a repo
    with patches nested several categories deep would otherwise take one
    request per directory level just to discover what exists before any
    actual file gets fetched.

    'repo' is "owner/name" (e.g. "stretis/universal_api_registry") — the
    main project repo itself, since connectors/ lives there, not a
    separate patches-only repo. Not a full URL — matches how a person
    would reference a GitHub repo casually, and avoids needing to strip
    a scheme/host from four different URL shapes GitHub could otherwise
    be referenced by.

    'dest_dir' is wiped and rebuilt from scratch on every call — the
    result is an exact mirror of '<repo>/<patches_subdir>' at 'ref' at
    the moment this ran, nothing carried over from before. A patch
    that's still upstream gets freshly re-downloaded and overwritten;
    a patch that's been renamed, moved, or deleted upstream since your
    last run is simply gone afterward too, same as it is on GitHub —
    not left behind for _load_patch() to keep silently applying.

    This directory is a pure fetched artifact, the same contract as
    USER_MANIFEST_PATH elsewhere in this project: nothing but this
    function ever writes here, so nothing here is ever "yours" to
    preserve. If you want a custom, hand-authored patch that survives
    updates, do NOT put it in this directory — point --patches-dir at
    a separate directory of your own instead (see cli.py's
    resolve_patches_root), or copy your custom file in fresh after
    each `patches update` run. Mixing local and fetched content in the
    same auto-managed directory is exactly the ambiguity this function
    is not trying to solve.
    """
    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)

    api_base = f"https://api.github.com/repos/{repo}"

    req = urllib.request.Request(
        f"{api_base}/git/trees/{ref}?recursive=1",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"},
    )
    # 🛠️ FIX: was a bare urlopen().read() with NO exception handling at
    # all — any failure here (confirmed: http.client.IncompleteRead,
    # truncated at the exact same byte count twice in a row against a
    # real repo) crashed the whole `patches update` command outright.
    # This single tree listing is the one call that HAS to succeed for
    # anything else in this function to happen at all, so it gets a
    # real retry rather than the per-file loop's simpler catch-and-skip.
    tree = json.loads(_urlopen_read_with_retry(req, timeout, label="fetching repo tree").decode("utf-8"))

    prefix = patches_subdir.rstrip("/") + "/"
    patch_entries = [
        item for item in tree.get("tree", [])
        if item.get("type") == "blob" and item.get("path", "").startswith(prefix)
        and item["path"].endswith(".json")
    ]

    fetched, failed = [], []
    for entry in patch_entries:
        relative_path = entry["path"][len(prefix):]  # <category>/<app_name>/<schema_name>.json
        raw_url = f"https://raw.githubusercontent.com/{repo}/{ref}/{entry['path']}"
        dest_path = os.path.join(dest_dir, relative_path)

        try:
            file_req = urllib.request.Request(raw_url, headers={"User-Agent": "Mozilla/5.0"})
            # 🛠️ FIX: retries on IncompleteRead same as the tree fetch
            # above, at the individual-file level. A single truncated
            # patch file shouldn't be worse off than the whole-repo
            # listing was — retry it too, then fall through to the
            # existing per-file catch-and-skip if it still fails.
            content = _urlopen_read_with_retry(file_req, timeout, label=relative_path)
            # Fail loudly on malformed JSON rather than silently caching a
            # broken patch file that would only surface as a confusing
            # error deep inside apply_patch() on some LATER transpile run,
            # far from where the actual problem (a bad file in the repo)
            # is visible.
            json.loads(content)
            pathlib.Path(os.path.dirname(dest_path)).mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(content)
            fetched.append(relative_path)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                ValueError, json.JSONDecodeError, http.client.IncompleteRead) as e:
            # 🛠️ FIX: http.client.IncompleteRead added to this tuple —
            # it's a separate exception hierarchy from URLError/
            # HTTPError/TimeoutError, so it was falling through this
            # except clause entirely and crashing the whole fetch loop
            # over ONE truncated file, rather than being logged as one
            # failed file the way every other failure mode here already is.
            print(f"WARN  Failed to fetch patch {relative_path}: {e}")
            failed.append(relative_path)

    print(f"Fetched {len(fetched)} patch(es) from {repo}@{ref} -> {dest_dir}/" + (f" ({len(failed)} failed)" if failed else ""))
    return {"fetched": fetched, "failed": failed, "dest_dir": dest_dir}


def transpile_endpoints(spec, ctx, max_endpoints=None, resource_hint=None, patches_root=None):
    """
    Parses OpenAPI paths and injects one universal-schema file per
    operation into ctx['target_dir'].

    Returns the list of schema_names generated (not just a count) —
    write_schema_index() needs the actual names to write the per-app
    index file, and the batch runner needs them to build the full
    catalog, so returning a bare count would just push a redundant
    directory-listing step onto both of those callers.

    max_endpoints: stop after generating this many schema files. For
    quick local testing against a real spec (some — Google's, Stripe's —
    have hundreds of operations) without waiting for or writing out the
    whole thing. None (default) means no limit — every real catalog run
    should leave this unset; it exists for fast iteration, not for
    trimming what ships.
    """
    paths = spec.get("paths", {})
    if not paths:
        return []  # Skip if no paths exist

    target_dir = ctx["target_dir"]
    pathlib.Path(target_dir).mkdir(parents=True, exist_ok=True) # Create only when writing
    base_url = ctx["base_url"]
    schema_names = []

    for path, methods in paths.items():
        if max_endpoints is not None and len(schema_names) >= max_endpoints:
            break
        for method, details in methods.items():
            if max_endpoints is not None and len(schema_names) >= max_endpoints:
                break
            if method.lower() not in ["get", "post", "put", "patch", "delete"]:
                continue

            # schema_name identity now comes from _identity_for_operation
            # (method + normalized path + resource_hint), NOT operationId
            # — see that function's docstring for why. operationId (raw,
            # possibly absent) is read directly off `details` wherever
            # it's still needed for DISPLAY purposes (_build_node_metadata's
            # label/node_type inference, and its own "operation_id" field).
            # resource_hint is passed through here too now (previously it
            # only reached the label generator below) — a multi-file spec
            # whose files share one generic path shape needs it in the
            # identity itself, or every file after the first silently
            # overwrites the one before it at the same schema_name.
            schema_name = _safe_schema_name(_identity_for_operation(method, path, resource_hint))

            class_params = {
                "_authorization": f"{{{{DataType=str, Default=$env.{_env_token_var(ctx['app_name'])}}}}}"
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer {_authorization}"
            }
            collisions = []

            # 1. Collect path-level parameters (defined on the route itself) and operation-level parameters
            path_parameters = methods.get("parameters", [])
            operation_parameters = details.get("parameters", [])
            
            # 2. Extract any path variables directly from the URL path string as a safety guarantee
            path_template_vars = re.findall(r"\{([^}]+)\}", path)

            param_map = {}
            for p in path_parameters:
                derefed_p = _deref(spec, p)
                if isinstance(derefed_p, dict) and "name" in derefed_p:
                    param_map[derefed_p["name"]] = derefed_p
            for p in operation_parameters:
                derefed_p = _deref(spec, p)
                if isinstance(derefed_p, dict) and "name" in derefed_p:
                    param_map[derefed_p["name"]] = derefed_p

            # 3. Ensure any path template variables present in the URL string are represented
            for var_name in path_template_vars:
                if var_name not in param_map:
                    param_map[var_name] = {
                        "name": var_name,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": f"Path parameter: {var_name}"
                    }

            parameters = list(param_map.values())

            for param in parameters:
                param_name = param.get("name")
                param_in = param.get("in")
                if param_name is None:
                    continue
                param_schema = _deref(spec, param.get("schema", param))
                p_type = map_openapi_type(param_schema.get("type", "string"))

                # 🛠️ FIX: was f"{{{{DataType={p_type}}}}}" for every param
                # regardless of required-ness or any spec-provided default —
                # neither was ever captured for path/query/header params
                # (only body properties got default-value support). Without
                # 'Required=', build_schema() in interpreter.py had no way
                # to tell "blank is fine, omit it" (a real optional query
                # flag) from "blank means the request is broken" — every
                # placeholder with no Default= was being treated as
                # unconditionally required.
                default_value = param_schema["default"] if "default" in param_schema else None

                if param_in in ["path", "query"]:
                    # 🛠️ FIX: this used to check "authorization" — a name
                    # real vendor APIs also use for their OWN parameters
                    # (Stripe's Issuing Authorizations API has an
                    # "authorization" path param identifying which
                    # authorization to act on). That collided with the
                    # reserved SYSTEM slot (see class_params' own
                    # "_authorization" key above) on every such endpoint,
                    # and this branch chose to protect the reserved slot —
                    # silently DROPPING the real path/query parameter
                    # rather than merely failing to label it nicely. Now
                    # checks the renamed reserved slot instead, so a real
                    # "authorization" parameter is treated as an ordinary
                    # field like any other — no collision, nothing dropped.
                    if param_name.lower() == "_authorization":
                        collisions.append(
                            f"class.'{param_name}' ({param_in}) ignored — reserved for the system auth token"
                        )
                        continue
                    if param_name in class_params:
                        collisions.append(
                            f"class.'{param_name}' ({param_in}) duplicate parameter name — last occurrence wins"
                        )
                    # Path params are ALWAYS required by REST/OpenAPI
                    # convention — there's no such thing as an optional
                    # path segment — so this isn't read from the spec's
                    # own 'required' field for that branch, it's simply true.
                    required = True if param_in == "path" else bool(param.get("required", False))
                    class_params[param_name] = _build_param_placeholder(p_type, required, default_value)

                elif param_in == "header":
                    if param_name.lower() == "authorization":
                        continue
                    existing_key = next(
                        (k for k in headers if k.lower() == param_name.lower()), None
                    )
                    if existing_key:
                        collisions.append(
                            f"headers.'{param_name}' overrides default '{existing_key}' header"
                        )
                        del headers[existing_key]
                    required = bool(param.get("required", False))
                    headers[param_name] = _build_param_placeholder(p_type, required, default_value)

            if collisions:
                print(f"⚠️  Key collision(s) in {schema_name}: " + "; ".join(collisions))

            body_payload = {}
            body_properties = {}
            required_fields = set()
            request_body = _deref(spec, details.get("requestBody", {}))
            content = request_body.get("content", {})

            target_content_type = next(
                (ct for ct in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data") 
                if ct in content), 
                None
            )

            if target_content_type:
                schema_node = content[target_content_type].get("schema", {})
                json_schema = _deref_schema_tree(spec, schema_node)
                body_properties = json_schema.get("properties", {})
                required_fields = set(json_schema.get("required", []) or [])
                # 🛠️ FIX: this call's result was always discarded — the
                # unconditional `if body_properties:` rebuild a few lines
                # down runs whenever this branch produces anything.
                # Removed; that rebuild is the only one that matters.


            # 👇 ADD THIS BLOCK: Fallback for Swagger 2.0 formData parameters
            if not body_properties:
                for param in parameters:
                    if param.get("in") == "formData":
                        p_name = param.get("name")
                        p_schema = _deref(spec, param.get("schema", param))
                        body_properties[p_name] = {
                            "type": p_schema.get("type", param.get("type", "string")),
                            "description": param.get("description", ""),
                        }
                        if param.get("required", False):
                            required_fields.add(p_name)

            if body_properties:
                # 🛠️ FIX: required_fields now actually threaded through —
                # previously this call never received it, so every body
                # leaf's placeholder came out with no 'Required=' tag no
                # matter what the spec said. See _build_body_payload's
                # own docstring for the full explanation.
                body_payload = _build_body_payload(body_properties, required_fields)

            node_metadata = _build_node_metadata(
                path, method, details, ctx, parameters, body_properties, required_fields, resource_hint
            )

            # Every top-level key is patchable, no exceptions — including
            # 'name', 'method', and 'url', which earlier only lived inside
            # a separately-tracked patch_target that omitted them. The
            # full universal_schema dict is assembled FIRST (with 'body'
            # always present, even {} for a bodyless GET, so a patch can
            # introduce a body that didn't exist), and the patch is
            # applied directly against that one object — no reconstruction,
            # no subset of fields held back.
            universal_schema = {
                "name": schema_name,
                "method": method.upper(),
                "url": f"{base_url}{path}",
                "class": class_params,
                "headers": headers,
                "body": body_payload,
                "metadata": node_metadata,
            }

            # patch lookup is keyed by schema_name as computed above —
            # that has to stay fixed before a patch runs (you need a
            # filename to find the patch file with in the first place).
            # A patch can still freely rewrite the *value* of the "name"
            # field inside the JSON payload above; that only changes what
            # the file itself records, not which file on disk this patch
            # was matched against by _load_patch().
            patch, patch_tier = _load_patch(patches_root, ctx["category"], ctx["app_name"], schema_name)
            if patch:
                apply_patch(universal_schema, patch)
                universal_schema["metadata"]["patched"] = True
                universal_schema["metadata"]["patch_source"] = patch_tier
                print(f"PATCHED ({patch_tier}): {ctx['category']}/{ctx['app_name']}/{schema_name}.json")

            # 🛠️ FIX: apply_patch()'s own "merge" step above may already
            # have deposited metadata.fields.class/body entries — an
            # author-written description, or a stub _expand_patch_
            # shorthand() extracted from an inline shorthand leaf — but
            # build_node_fields() right below unconditionally REASSIGNS
            # metadata["fields"] to a fresh dict, discarding whatever
            # just landed there. Captured here, before that reassignment,
            # so it can be merged back in afterward; see
            # _merge_patch_field_stubs' own docstring for the full story.
            # A plain reference, not a copy — build_node_fields reassigns
            # metadata["fields"] to a NEW dict rather than mutating it in
            # place, so this old dict is untouched by that reassignment.
            patch_field_stubs = universal_schema.get("metadata", {}).get("fields")

            # Drop 'body' from the OUTPUT when empty — same behavior as
            # before patches existed (a bodyless GET has no "body" key at
            # all). Checked AFTER patching: a patch that fills in a
            # previously-empty body causes it to be written; one that
            # empties it back out causes it to be omitted either way.
            if not universal_schema["body"]:
                del universal_schema["body"]

            # Fix added the build_node_fields function and called it to populate the metadata field
            #  after the patches are all done not before as the previous behavoiur before this fix
            # this will ey the field ey in the metadata sync with the api schema
            build_node_fields(
                metadata=universal_schema["metadata"], 
                parameters=parameters, body_properties=body_properties, 
                required_fields=required_fields
            )

            if patch_field_stubs:
                _merge_patch_field_stubs(
                    universal_schema["metadata"]["fields"]["class"], patch_field_stubs.get("class")
                )
                _merge_patch_field_stubs(
                    universal_schema["metadata"]["fields"]["body"], patch_field_stubs.get("body")
                )

            # A patch-introduced key (present in the actual patched class/
            # body, not in the pre-patch parameters/body_properties
            # build_node_fields() was just built from above) still needs a
            # form-field entry of its own, or the UI simply can't render
            # an input for it at all — see _reconcile_fields_with_patched_
            # values' docstring for why calling build_node_fields() AFTER
            # the patch wasn't, by itself, enough to guarantee that.
            #
            # 🛠️ FIX: an 'override' at the 'class'/'body' key means
            # WHOLESALE replacement (see _shallow_override_into) — not a
            # partial touch. Reconciling onto build_node_fields()'s
            # pre-patch output in that case left PHANTOM fields behind:
            # proved concretely — overriding body down to just
            # {"only_this_field": ...} correctly replaced the real body,
            # but metadata.fields.body still listed the original 'name'/
            # 'notes' (one of them still flagged required:true) alongside
            # the new field, none of which reflect the actual request
            # that block would build. So a block that was OVERRIDDEN gets
            # its fields REBUILT purely from the override's own keys
            # (discarding whatever build_node_fields() produced for it
            # entirely); a block that was only ever MERGED (or never
            # patched at all) keeps the reconcile-onto-existing behavior,
            # since merge is explicitly additive/partial by design — an
            # untouched sibling key was never meant to disappear just
            # because the patch touched a different key in the same block.
            override_block = (patch or {}).get("override", {})

            if "class" in override_block:
                universal_schema["metadata"]["fields"]["class"] = _rebuild_overridden_fields(
                    universal_schema["metadata"]["fields"].get("class"), universal_schema["class"]
                )
            else:
                _reconcile_fields_with_patched_values(
                    universal_schema["metadata"]["fields"]["class"], universal_schema["class"]
                )

            # 🛠️ FIX: neither branch above knows "_authorization" is
            # reserved — _build_class_fields_metadata's own skip (in
            # build_node_fields, above) only ever scans the real OpenAPI
            # `parameters` list, which never contains the reserved slot in
            # the first place (it's injected separately into class_params/
            # universal_schema["class"], not sourced from `parameters`).
            # So *this* reconciliation — driven directly off
            # universal_schema["class"], which DOES contain
            # "_authorization" — re-derives a fresh field entry for it
            # every time, via the plain "key not in fields_dict" branch,
            # regardless of build_node_fields' own skip. Stripped here
            # instead, once, after BOTH possible branches above (override-
            # rebuild reassigns the whole dict; reconcile mutates it in
            # place) have had their chance to (re)introduce it — the one
            # point downstream of everything that could have put it back.
            universal_schema["metadata"]["fields"]["class"].pop("_authorization", None)

            if "body" in override_block:
                universal_schema["metadata"]["fields"]["body"] = _rebuild_overridden_fields(
                    universal_schema["metadata"]["fields"].get("body"), universal_schema.get("body", {})
                )
            else:
                _reconcile_fields_with_patched_values(
                    universal_schema["metadata"]["fields"]["body"], universal_schema.get("body", {})
                )

            # 🛠️ FIX: a "delete" patch removes keys from the REAL
            # class/body dicts above (via apply_patch -> _delete_keys),
            # but nothing removed the matching entries from
            # metadata.fields.class/body — the exact same phantom-field
            # problem override's block-rebuild above already exists to
            # prevent, just via a different patch verb. metadata.fields
            # mirrors class/body's own top-level shape 1:1, so the same
            # delete patch applies directly against it, no translation
            # needed, removing whatever it removed from the real schema.
            # Runs last and unconditionally (independent of whether that
            # block was merged or overridden above) so it's correct either
            # way: if the block was overridden, this only fires for a key
            # the override's own replacement content still happened to
            # reintroduce under the same name and then chose to delete —
            # otherwise it's already a no-op, since _delete_keys is a
            # graceful pop(key, None).
            if patch and "delete" in patch:
                _delete_keys(universal_schema["metadata"]["fields"], patch["delete"])

            out_file = os.path.join(target_dir, f"{schema_name}.json")
            universal_schema["metadata"]["first_created"] = _resolve_first_created(
                out_file, ctx["last_updated"], nested_under_metadata=True
            )
            with open(out_file, "w", encoding="utf-8") as out_f:
                json.dump(universal_schema, out_f, indent=4)

            schema_names.append(schema_name)
            print(f"📥 Injected: {ctx['category']}/{ctx['app_name']}/{schema_name}.json")

    return schema_names


# ---------------------------------------------------------------------------
# 2. OAuth config
# ---------------------------------------------------------------------------

def extract_oauth_config(spec, ctx, patches_root=None):
    """
    Extracts OAuth2 security definitions (OpenAPI 3.0 securitySchemes,
    falling back to Swagger 2.0 securityDefinitions) into an auth
    schema file, placed in the same target_dir as the endpoint schemas.
    Returns the auth schema's name (e.g. 'hubapi_com_auth') if an OAuth
    scheme was found and written, else None — the name (not just a bool)
    is what write_schema_index() needs to list it alongside every
    endpoint schema by name.

    patches_root: same mechanism as transpile_endpoints' patches_root,
    just keyed by the fixed filename "_auth" instead of a schema_name -
    there's exactly one auth file per app, so there's no per-endpoint
    lookup here. Unlike transpile_endpoints (which builds patch_target as
    a subset of local variables because auth_schema doesn't exist as one
    object until several fields are computed), auth_schema here already
    IS a single complete dict by the time a patch would apply - so the
    patch is applied directly against it, in place, no reconstruction
    needed. Every top-level key (name/token_url/auth_link/method/class/
    metadata) is reachable - no carve-outs.
    """
    app_name = ctx["app_name"]
    target_dir = ctx["target_dir"]

    # 🛠️ FIX: a hand-authored "_auth" node used to get written correctly
    # by apply_nodes(), then silently overwritten a moment later when
    # THIS function ran right after and unconditionally generated+wrote
    # its own _auth.json regardless of what was already on disk. Checked
    # here, first, before touching the spec at all — a node fully
    # replaces this file, so there's nothing to generate or patch once
    # one exists; this also means a "_auth" node works for a SPEC-LESS
    # app (spec={}, no securitySchemes to find anyway) exactly the same
    # way it works for a spec-having one.
    node, node_tier = _load_node(patches_root, ctx["category"], app_name, "_auth")
    if node:
        node.setdefault("metadata", {})
        node["metadata"]["node_source"] = node_tier
        _derive_node_fields(node)
        out_file = os.path.join(target_dir, "_auth.json")
        node["metadata"]["first_created"] = _resolve_first_created(
            out_file, node["metadata"].get("last_updated") or ctx["last_updated"], nested_under_metadata=True
        )
        with open(out_file, "w", encoding="utf-8") as out_f:
            json.dump(node, out_f, indent=4)
        print(f"🧩 NODE ({node_tier}) _auth: {ctx['category']}/{app_name}/_auth.json")
        return "_auth"

    components = spec.get("components", {})
    security_schemes = components.get("securitySchemes", {})

    if not security_schemes:
        security_schemes = spec.get("securityDefinitions", {})

    auth_schema_name = None

    for scheme_name, scheme_details in security_schemes.items():
        if scheme_details.get("type") != "oauth2":
            continue

        flows = scheme_details.get("flows", {})
        flow_type = "authorizationCode" if "authorizationCode" in flows else next(iter(flows), None)
        if flow_type is None:
            continue
        flow_data = flows.get(flow_type, {})

        token_url = flow_data.get("tokenUrl", "")
        auth_url = flow_data.get("authorizationUrl", "")
        raw_scopes = flow_data.get("scopes", {})
        scopes_string = " ".join(raw_scopes.keys())

        auth_link_template = f"{auth_url}?client_id={{CLIENT_ID}}&redirect_uri={{REDIRECT_URI}}&scope={{scopes}}"

        auth_schema = {
            "name": f"{app_name}_oauth_config",
            "token_url": token_url,
            "auth_link": auth_link_template,
            "method": "POST",
            "class": {
                "CLIENT_ID": "{{DataType=str}}",
                "CLIENT_SECRET": "{{DataType=str}}",
                "scopes": f"{{{{DataType=str, Default={scopes_string}}}}}",
                "REDIRECT_URI": f"{{{{DataType=str, Default=http://localhost:8080/callback/{app_name}}}}}",
            },
            "metadata": {
                "display_name": f"Connect {ctx['info'].get('title', app_name)}",
                "description": f"Authorize access to {ctx['info'].get('title', app_name)} via OAuth2.",
                "icon_url": ctx["icon_url"],
                "color": ctx["color"],
                "category": ctx["category"],
                "node_type": "auth",
                "node_type_confidence": "verified",
                "source": ctx["source"],
                "fields": {
                    "class": {
                        "CLIENT_ID": _field_metadata("CLIENT_ID", "str", "OAuth client ID from the app's developer portal.", True),
                        "CLIENT_SECRET": _field_metadata("CLIENT_SECRET", "str", "OAuth client secret — store via secrets manager, never commit.", True),
                        "scopes": _field_metadata("scopes", "str", "Space-separated OAuth scopes to request. Pre-filled from the API spec — narrow this if the integration doesn't need full access.", True),
                        "REDIRECT_URI": _field_metadata("REDIRECT_URI", "str", "OAuth callback URL. Override to match your app's registered redirect URI.", True),
                    },
                    "body": {},
                },
                "last_updated": ctx["last_updated"],
            },
        }

        patch, patch_tier = _load_patch(patches_root, ctx["category"], app_name, "_auth")
        if patch:
            apply_patch(auth_schema, patch)
            auth_schema["metadata"]["patched"] = True
            auth_schema["metadata"]["patch_source"] = patch_tier
            print(f"PATCHED ({patch_tier}): {ctx['category']}/{app_name}/_auth.json")

            # 🛠️ FIX: mirrors transpile_endpoints' own override/merge
            # reconciliation (see its "PHANTOM fields" comment) — without
            # this, an 'override' on body/class silently leaves
            # metadata.fields.body/class exactly as they were initialized
            # above (body: {}), so the UI form never reflects a patched
            # body at all, and a merged body/class would leave newly-added
            # keys with no form field either. 'override' wholesale-rebuilds
            # the field list from the new block's own keys; anything else
            # (merge, or no touch) reconciles onto whatever fields.class/
            # body already had.
            override_block = patch.get("override", {})

            if "class" in override_block:
                auth_schema["metadata"]["fields"]["class"] = _rebuild_overridden_fields(
                    auth_schema["metadata"]["fields"].get("class"), auth_schema["class"]
                )
            else:
                _reconcile_fields_with_patched_values(
                    auth_schema["metadata"]["fields"]["class"], auth_schema["class"]
                )

            if "body" in override_block:
                auth_schema["metadata"]["fields"]["body"] = _rebuild_overridden_fields(
                    auth_schema["metadata"]["fields"].get("body"), auth_schema.get("body", {})
                )
            else:
                _reconcile_fields_with_patched_values(
                    auth_schema["metadata"]["fields"]["body"], auth_schema.get("body", {})
                )

            delete_patch = patch.get("delete")
            if delete_patch:
                _delete_keys(auth_schema["metadata"]["fields"], delete_patch)

        out_file = os.path.join(target_dir, "_auth.json")
        auth_schema["metadata"]["first_created"] = _resolve_first_created(
            out_file, ctx["last_updated"], nested_under_metadata=True
        )
        with open(out_file, "w", encoding="utf-8") as out_f:
            json.dump(auth_schema, out_f, indent=4)

        print(f"🔑 Extracted OAuth Schema: {out_file}")
        auth_schema_name = "_auth"
        break

    return auth_schema_name


# ---------------------------------------------------------------------------
# 3. Frontend metadata (favicon / logo / description)
# ---------------------------------------------------------------------------

def extract_app_metadata(spec, ctx, fetch_favicon=True, timeout=5, patches_root=None):
    """
    patches_root: same "one fixed filename per app" shape as
    extract_oauth_config's — keyed by "_meta" instead of "_auth", applied
    directly against the metadata dict in place. Every key here
    (display_name, description, favicon_url, logo_background_color, ...)
    is reachable — no carve-outs.
    """
    target_dir = ctx["target_dir"]
    app_name = ctx["app_name"]

    # 🛠️ FIX: same clobbering issue as extract_oauth_config's "_auth" —
    # a hand-authored "_meta" node was being overwritten a moment later
    # by this function's own unconditional generation. Checked first,
    # before touching 'info' at all, so it works identically whether or
    # not this app even has a spec (info={} for a spec-less app - moot
    # once a node exists anyway). favicon_local_path defaults to None if
    # the node didn't set one, since transpile_full reads that key
    # straight off this function's return value.
    node, node_tier = _load_node(patches_root, ctx["category"], app_name, "_meta")
    if node:
        node["node_source"] = node_tier
        node.setdefault("favicon_local_path", None)
        out_file = os.path.join(target_dir, "_meta.json")
        node["first_created"] = _resolve_first_created(
            out_file, node.get("last_updated") or ctx["last_updated"], nested_under_metadata=False
        )
        with open(out_file, "w", encoding="utf-8") as out_f:
            json.dump(node, out_f, indent=4)
        print(f"🧩 NODE ({node_tier}) _meta: {ctx['category']}/{app_name}/_meta.json")
        return node

    info = ctx["info"]

    favicon_url = ctx["icon_url"]

    metadata = {
        "name": app_name,
        "display_name": ctx.get("display_name") or info.get("title", app_name),
        "description": info.get("description", ""),
        "version": info.get("version", ""),
        "category": ctx["category"],
        "base_url": ctx["base_url"],
        "favicon_url": favicon_url,
        "favicon_local_path": None,
        "logo_background_color": ctx["color"],
        "source": ctx["source"],
        "last_updated": ctx["last_updated"],
    }

    if fetch_favicon and favicon_url:
        local_path = _download_favicon(favicon_url, target_dir, app_name, timeout)
        if local_path:
            metadata["favicon_local_path"] = local_path

    patch, patch_tier = _load_patch(patches_root, ctx["category"], app_name, "_meta")
    if patch:
        apply_patch(metadata, patch)
        metadata["patched"] = True
        metadata["patch_source"] = patch_tier
        print(f"PATCHED ({patch_tier}): {ctx['category']}/{app_name}/_meta.json")

    out_file = os.path.join(target_dir, "_meta.json")
    metadata["first_created"] = _resolve_first_created(
        out_file, ctx["last_updated"], nested_under_metadata=False
    )
    with open(out_file, "w", encoding="utf-8") as out_f:
        json.dump(metadata, out_f, indent=4)

    print(f"🖼️  Wrote metadata: {out_file}")
    return metadata


def _download_favicon(url, target_dir, app_name, timeout=5):
    """Best-effort favicon download. Returns local relative path or None."""
    ext = os.path.splitext(url.split("?")[0])[1] or ".png"
    if len(ext) > 5:
        ext = ".png"
    filename = f"{app_name}_favicon{ext}"
    out_path = os.path.join(target_dir, filename)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"⬇️  Downloaded favicon: {out_path}")
        return filename
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        print(f"⚠️  Favicon download failed for {app_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# 4. Per-app schema index
# ---------------------------------------------------------------------------

def write_schema_index(ctx, endpoint_schema_names, auth_schema_name=None, patches_root=None):
    """
    patches_root: same shape as the other two, keyed by "_index". Lets a
    patch override the published 'schemas' list directly - e.g.
    suppressing a schema that's known-broken from the index a consumer
    reads, without touching or deleting the actual generated file on
    disk. 'total_schemas' is recomputed AFTER the patch applies, since an
    override that changes 'schemas' would otherwise leave a stale count
    sitting next to the corrected list.
    """
    target_dir = ctx["target_dir"]

    # 🛠️ FIX: same clobbering issue as the other two — a hand-authored
    # "_index" node was being overwritten a moment later by this
    # function's own unconditional generation from endpoint_schema_names/
    # auth_schema_name. Checked first: a node here fully replaces the
    # published index (total_schemas recomputed from whatever "schemas"
    # list the node itself provides, same as the patch path below does).
    node, node_tier = _load_node(patches_root, ctx["category"], ctx["app_name"], "_index")
    if node:
        node["node_source"] = node_tier
        node["total_schemas"] = len(node.get("schemas", []))
        out_file = os.path.join(target_dir, "_index.json")
        with open(out_file, "w", encoding="utf-8") as out_f:
            json.dump(node, out_f, indent=4)
        print(f"🧩 NODE ({node_tier}) _index: {ctx['category']}/{ctx['app_name']}/_index.json")
        return node

    schemas = sorted(endpoint_schema_names)
    if auth_schema_name:
        schemas.append(auth_schema_name)

    index = {
        "app_name": ctx["app_name"],
        "category": ctx["category"],
        "generated_at": ctx["last_updated"],
        "total_schemas": len(schemas),
        "schemas": schemas,
    }

    patch, patch_tier = _load_patch(patches_root, ctx["category"], ctx["app_name"], "_index")
    if patch:
        apply_patch(index, patch)
        index["total_schemas"] = len(index["schemas"])
        index["patched"] = True
        index["patch_source"] = patch_tier
        print(f"PATCHED ({patch_tier}): {ctx['category']}/{ctx['app_name']}/_index.json")

    out_file = os.path.join(target_dir, "_index.json")
    with open(out_file, "w", encoding="utf-8") as out_f:
        json.dump(index, out_f, indent=4)

    print(f"📇 Wrote schema index ({len(index['schemas'])} schemas): {out_file}")
    return index


# ---------------------------------------------------------------------------
# 5. Hand-authored node overrides
# ---------------------------------------------------------------------------
# Distinct from patches: a patch merges/overrides/deletes FIELDS onto
# whatever transpile_endpoints already produced. A node is a COMPLETE,
# standalone, hand-authored schema that replaces the output file
# wholesale - written by a person reading the vendor's docs directly, not
# derived from any spec at all (see README's "Hand-authoring a schema"
# contribution guidance - the method/url/class/headers/body/
# metadata.fields shape a node is expected to already be valid in, on its
# own, with no auto-derivation needed the way patches rely on
# build_node_fields/_reconcile_fields_with_patched_values to keep
# metadata.fields in sync with class/body). Applies to ANY app, spec-
# having or spec-less alike, and at the SAME per-endpoint granularity as
# a patch - one node overrides exactly one schema_name, same official-
# then-community precedence as _load_patch().
#
# Called once per app, AFTER transpile_endpoints has finished (or even if
# it produced nothing at all, for a spec-less app) - never from inside
# transpile_endpoints itself, since a node can introduce a schema_name
# that never existed in any spec to begin with, and needs the FULL set of
# already-generated names to tell "override" from "brand new" apart
# (informational only - the write behavior is identical either way, this
# only affects the log line).

def _node_files(node_dir):
    if not os.path.isdir(node_dir):
        return {}
    return {
        fname[: -len(".json")]: os.path.join(node_dir, fname)
        for fname in sorted(os.listdir(node_dir))
        if fname.endswith(".json")
    }


def _extract_shorthand_descriptions(value):
    """
    Walks a class/body dict BEFORE _shorthand_to_placeholder strips it
    down to a bare placeholder string, pulling out any "description" a
    shorthand leaf provided — {"type": "str", "description": "..."} —
    into a field-descriptor stub shaped exactly like a real
    metadata.fields entry. Lets an author write a field's description
    INLINE, right next to its type/default/required, instead of having
    to duplicate the field a second time under a separate
    metadata.fields.* block just to attach one sentence — the whole
    point of the shorthand is fewer places to touch, not more.

    Recurses through EVERY level a real field can live at: a top-level
    field, a nested-object ("group") field, and a field nested inside an
    array-of-objects ("array_group", e.g. one leaf inside filterGroups) —
    matching _infer_field_from_value/_reconcile_fields_with_patched_values'
    own "array_group"/"first element is representative" handling exactly,
    so a description written anywhere those functions can now represent
    a field is preserved, not just the two shallowest levels.
    """
    stubs = {}
    for key, v in value.items():
        if isinstance(v, dict) and isinstance(v.get("type"), str):
            desc = v.get("description")
            if desc:
                stubs[key] = _field_metadata(key, v["type"], description=desc, required=bool(v.get("required", False)))
        elif isinstance(v, dict):
            nested_stubs = _extract_shorthand_descriptions(v)
            if nested_stubs:
                stubs[key] = {
                    "label": _humanize(key), "input_type": "group",
                    "description": "", "required": False,
                    "fields": nested_stubs,
                }
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            nested_stubs = _extract_shorthand_descriptions(v[0])
            if nested_stubs:
                stubs[key] = {
                    "label": _humanize(key), "input_type": "array_group",
                    "description": "", "required": False,
                    "fields": nested_stubs,
                }
    return stubs


def _shorthand_to_placeholder(value):
    """
    Converts an author-friendly field shorthand —
        {"type": "str", "default": "EQ", "required": true}
    (any subset; only "type" is meaningful, "default"/"required" are
    optional and default to None/False) — into the platform's real
        "{{DataType=str, Default=EQ, Required=True}}"
    placeholder string via _build_param_placeholder, the exact same
    helper the transpiler itself uses — so a node author never has to
    hand-type that syntax (easy to typo: a missing comma, or
    "Required=true" instead of "Required=True", fails SILENTLY, since
    build_schema() only ever checks for the literal string "True") while
    still producing output byte-identical to a transpiled field. Nothing
    downstream needs to know or care this came from a hand-written node.

    Recurses into nested dicts (an object-shaped field — same as a
    transpiled body's nested object) and into dicts found inside a list
    (so a shorthand field nested inside an array-of-objects, like
    HubSpot search's filterGroups, converts the same way, matching
    _build_body_payload's own array-of-objects handling). A value that's
    ALREADY a plain string (a literal constant, or an already-written
    "{{...}}" placeholder), number, bool, or None is returned completely
    untouched — this only ever converts a dict that actually LOOKS like
    shorthand (has a "type" key whose value is itself a string); any
    other dict is recursed into as a nested object rather than misread
    as a shorthand field.

    Known, accepted ambiguity: a genuine body field literally NAMED
    "type" that itself needs further nested shorthand underneath it
    can't be expressed this way (it'll be read as a shorthand leaf, not
    a nested object) — write the full "{{DataType=...}}" string directly
    for that one field instead; a raw string is always passed through
    untouched regardless of what it's nested inside.
    """
    if isinstance(value, dict):
        if isinstance(value.get("type"), str):
            return _build_param_placeholder(
                value["type"], bool(value.get("required", False)), value.get("default")
            )
        return {k: _shorthand_to_placeholder(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorthand_to_placeholder(v) for v in value]
    return value  # string/number/bool/None — already final, left as-is


def _complete_node_schema(node_schema, ctx):
    """
    Fills in exactly the boilerplate a hand-authored node would otherwise
    have to retype in every single file, and expands
    _shorthand_to_placeholder's friendly field syntax into the platform's
    real placeholder strings — run once, right before _derive_node_fields,
    so metadata.fields is always derived from the FINAL, expanded
    class/body, never the shorthand form the author actually wrote.

    Everything here only fills in a value the author didn't already
    provide — an explicit "class"/"headers"/"metadata.icon_url" (etc.)
    already present in the node file always wins outright, so an app
    with genuinely unusual auth (not the standard Bearer-token pattern)
    can still override any of this per-node, exactly like every other
    "explicit wins, otherwise sensible default" convention in this file.

    class._authorization / headers: identical boilerplate every
    TRANSPILED schema already carries too (see transpile_endpoints) —
    same $env.<TOKEN_VAR> pattern, same Content-Type/Authorization
    headers. Injected straight from ctx so it can never drift or be
    typo'd across dozens of hand-written files the way retyping it every
    time would risk. Reserved slot is "_authorization" (underscore-
    prefixed), not "authorization" — see transpile_endpoints' own
    class_params comment for why: a real vendor API parameter can
    legitimately be named "authorization" and must never collide with
    this system-injected one.

    metadata.display_name/description: promoted from the node's own
    top-level "display_name"/"description" keys if the author put them
    there instead of nested under "metadata" — purely a convenience so a
    minimal node doesn't need an empty "metadata": {} wrapper just to
    hold two strings.

    metadata.icon_url/color/category: inherited from ctx — the SAME
    values already written once to this app's _meta.json — unless the
    node's own metadata explicitly overrides them. These are PER-APP
    facts, not per-endpoint ones; requiring every node to repeat them is
    pure duplication with a real drift risk (change the app's icon once,
    and now every node file that duplicated it is stale).
    """
    node_schema.setdefault("class", {})
    node_schema["class"].setdefault(
        "_authorization", f"{{{{DataType=str, Default=$env.{_env_token_var(ctx['app_name'])}}}}}"
    )
    node_schema.setdefault("headers", {
        "Content-Type": "application/json",
        "Authorization": "Bearer {_authorization}",
    })

    node_schema.setdefault("metadata", {})
    for key in ("display_name", "description"):
        if key in node_schema and key not in node_schema["metadata"]:
            node_schema["metadata"][key] = node_schema.pop(key)
    for key in ("icon_url", "color", "category"):
        node_schema["metadata"].setdefault(key, ctx.get(key, ""))

    # 🛠️ FIX: an inline "description" written INSIDE a shorthand leaf
    # (e.g. {"type": "str", "description": "The deal property to filter
    # on."}) used to be silently dropped — _shorthand_to_placeholder only
    # ever reads type/default/required, so the description had nowhere
    # to go and just vanished, with no error. Extracted here, BEFORE the
    # shorthand collapses into a bare placeholder string, and seeded into
    # metadata.fields as a stub _reconcile_fields_with_patched_values
    # (called next, via _derive_node_fields) will find already-present —
    # so it only syncs input_type/required from the real placeholder tag
    # and leaves this seeded description untouched, exactly like it
    # already does for a human-written metadata.fields entry. An
    # author's own EXPLICIT metadata.fields entry for the same key still
    # wins outright (setdefault, never overwrites).
    existing_fields = node_schema["metadata"].setdefault("fields", {})
    existing_class_fields = existing_fields.setdefault("class", {})
    existing_body_fields = existing_fields.setdefault("body", {})
    for key, stub in _extract_shorthand_descriptions(node_schema["class"]).items():
        existing_class_fields.setdefault(key, stub)
    for key, stub in _extract_shorthand_descriptions(node_schema.get("body", {})).items():
        existing_body_fields.setdefault(key, stub)

    node_schema["class"] = _shorthand_to_placeholder(node_schema["class"])
    if "body" in node_schema:
        node_schema["body"] = _shorthand_to_placeholder(node_schema["body"])

    return node_schema


def _derive_node_fields(node_schema):
    """
    Derives metadata.fields.class/body directly from THIS node's own
    class/body content, reusing _reconcile_fields_with_patched_values()
    — the exact same function that already keeps a PATCHED schema's
    fields in sync with its real class/body (see transpile_endpoints'
    patch-application block). Reused here so a node's fields are equally
    guaranteed to match its own class/body, rather than needing to be
    hand-typed field-by-field by whoever authored the node — the same
    "derivative data shouldn't be duplicated by hand" principle that
    already governs a transpiled schema's fields.

    Seeded with whatever metadata.fields the author already wrote (if
    any) rather than a blank dict — a hand-written description for a
    specific field (the one thing genuinely worth a human writing by
    hand: WHY a field matters, not WHAT type it is) is preserved exactly
    as written; input_type/required for every field, and the existence
    of any field the author's own fields block left out entirely, always
    come from class/body itself — the one place that can't silently
    drift out of sync with the actual request being built.

    Everything ELSE in metadata (display_name, description, icon_url,
    category, node_type, ...) is untouched here — those are NOT
    derivative of class/body, they're the author's own authored content
    and this function has no opinion about them.

    🛠️ FIX: this had NO reserved-key skip at all — unlike the transpiled-
    endpoint path (_build_class_fields_metadata), which has always
    excluded the system-injected credential slot from metadata.fields.
    class, a hand-authored node's own "_authorization" (previously
    "authorization" — see _complete_node_schema) was reconciled into
    metadata.fields.class just like any real field, meaning it would
    surface as a fillable input in the UI for every hand-authored node.
    Popped from the derived result here — after reconciliation, not
    before — so the reserved key still gets its usual reconcile pass
    (harmless either way, since nothing meaningful reads its fields
    entry) and this stays a single, obvious removal point rather than
    threading a skip condition through the reconcile call itself.
    """
    node_schema.setdefault("metadata", {})
    existing_fields = node_schema["metadata"].get("fields") or {}
    class_fields = _reconcile_fields_with_patched_values(
        dict(existing_fields.get("class", {})), node_schema.get("class", {})
    )
    class_fields.pop("_authorization", None)
    node_schema["metadata"]["fields"] = {
        "class": class_fields,
        "body": _reconcile_fields_with_patched_values(
            dict(existing_fields.get("body", {})), node_schema.get("body", {})
        ),
    }
    return node_schema


def _write_node_file(src_path, target_dir, schema_name, category, app_name, tier, existing_schema_names, ctx=None):
    with open(src_path, "r", encoding="utf-8") as f:
        node_schema = json.load(f)

    # node_source (not patch_source) - a node isn't a modification applied
    # ON TOP of something, it IS the file, so it gets its own trust-tag
    # field rather than overloading "patched"/"patch_source", which mean
    # something structurally different (a merge/override/delete having
    # been applied to otherwise-transpiled content).
    node_schema.setdefault("metadata", {})
    node_schema["metadata"]["node_source"] = tier

    # 🛠️ FIX: a hand-authored node used to have to already BE the fully
    # expanded universal_schema shape — class.authorization, both
    # headers, and a complete metadata block, all retyped by hand in
    # every single node file. _complete_node_schema fills in exactly
    # that boilerplate (and expands the friendly field shorthand) before
    # _derive_node_fields runs, so fields are always derived from the
    # FINAL expanded class/body. Only runs when a ctx is available —
    # every real call site now provides one; ctx=None is preserved as a
    # fallback for any caller that can't (e.g. a bare unit test) rather
    # than making ctx a hard requirement.
    if ctx is not None:
        node_schema = _complete_node_schema(node_schema, ctx)

    _derive_node_fields(node_schema)

    out_file = os.path.join(target_dir, f"{schema_name}.json")
    node_schema["metadata"]["first_created"] = _resolve_first_created(
        out_file, node_schema["metadata"].get("last_updated") or _now_iso(), nested_under_metadata=True
    )

    with open(out_file, "w", encoding="utf-8") as out_f:
        json.dump(node_schema, out_f, indent=4)

    action = "overrode transpiled" if schema_name in existing_schema_names else "added new"
    print(f"🧩 NODE ({tier}) {action}: {category}/{app_name}/{schema_name}.json")


def _load_node(patches_root, category, app_name, schema_name):
    """
    Mirrors _load_patch()'s exact official-then-community resolution, one
    directory over: connectors/<category>/<app_name>/{nodes,community/nodes}/
    instead of .../{patches,community/patches}/. Same (dict_or_None,
    tier_or_None) return shape, same "official wins outright" rule.

    Used directly by extract_oauth_config/extract_app_metadata/
    write_schema_index (for "_auth"/"_meta"/"_index" specifically) so
    each of those can short-circuit to a node BEFORE generating and
    writing its own version — see the FIX note at each of those call
    sites for why apply_nodes() alone wasn't sufficient for those three
    filenames specifically.
    """
    if not patches_root:
        return None, None

    official_path = os.path.join(patches_root, category, app_name, "nodes", f"{schema_name}.json")
    if os.path.isfile(official_path):
        with open(official_path, "r", encoding="utf-8") as f:
            return json.load(f), "official"

    community_path = os.path.join(patches_root, category, app_name, "community", "nodes", f"{schema_name}.json")
    if os.path.isfile(community_path):
        with open(community_path, "r", encoding="utf-8") as f:
            return json.load(f), "community"

    return None, None


def apply_nodes(patches_root, category, app_name, target_dir, existing_schema_names, ctx=None):
    """
    Writes every hand-authored PER-ENDPOINT node found for this app
    directly into target_dir, official winning outright over community
    for the same schema_name (identical precedence rule to _load_patch(),
    just replacement instead of merge/override/delete). Safe to call
    even when patches_root is None (no-op) or the app has no nodes at all
    (no-op) - always call this after transpile_endpoints, whether or not
    that produced anything, since a node can be the ONLY source of a
    given schema_name for a spec-less app.

    🛠️ FIX: "_auth"/"_meta"/"_index" are now explicitly EXCLUDED from
    this sweep. Those three filenames are handled natively inside
    extract_oauth_config()/extract_app_metadata()/write_schema_index()
    via their own _load_node() check, run at the START of each function,
    BEFORE that function generates and writes its own version. Previously
    this function would write e.g. a "_meta" node here, and then
    extract_app_metadata() — which runs unconditionally right after in
    every call chain (transpile_full, run_multi_file_app,
    run_index_api_app) — would immediately overwrite it with a freshly
    generated _meta.json, silently clobbering the node a few lines later.
    Excluding the reserved names here means apply_nodes() only ever
    touches per-endpoint action schemas, which nothing downstream
    regenerates or overwrites after this point.

    Returns the updated schema_names list: every existing name plus every
    node-provided name (a name already present is a no-op union; a new
    one is how a node-only or node-added action gets included in
    write_schema_index()'s _index.json at all).
    """
    if not patches_root:
        return existing_schema_names

    reserved = {"_auth", "_meta", "_index"}
    official = {k: v for k, v in _node_files(os.path.join(patches_root, category, app_name, "nodes")).items() if k not in reserved}
    community = {k: v for k, v in _node_files(os.path.join(patches_root, category, app_name, "community", "nodes")).items() if k not in reserved}

    pathlib.Path(target_dir).mkdir(parents=True, exist_ok=True)
    applied_names = set()

    for schema_name, src_path in official.items():
        _write_node_file(src_path, target_dir, schema_name, category, app_name, "official", existing_schema_names, ctx=ctx)
        applied_names.add(schema_name)

    for schema_name, src_path in community.items():
        if schema_name in official:
            continue  # shadowed by an official node of the same name
        _write_node_file(src_path, target_dir, schema_name, category, app_name, "community", existing_schema_names, ctx=ctx)
        applied_names.add(schema_name)

    return sorted(set(existing_schema_names) | applied_names)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _load_spec_file(spec_path):
    ext = os.path.splitext(spec_path)[1].lower()
    with open(spec_path, "r", encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            import yaml
            return yaml.safe_load(f)
        return json.load(f)


def transpile_full(spec_path, base_output_dir="../schemas", fetch_favicon=True, max_endpoints=None,
                    category_override=None, icon_url_override=None, color_override=None, app_name_override=None,
                    resource_hint=None, source_override=None, display_name_override=None,
                    patches_root=None):
    spec = _load_spec_file(spec_path)
    # patches_root: forwarded straight through to transpile_endpoints() -
    # see _load_patch()/apply_patch() for what actually happens with it.
    # None (default) means no patches are looked up at all, same as
    # omitting --patch/--patches-dir at the CLI layer.
    ctx = get_app_context(spec, base_output_dir, category_override=category_override,
                           icon_url_override=icon_url_override, color_override=color_override,
                           app_name_override=app_name_override, source_override=source_override,
                           display_name_override=display_name_override)

    stage_errors = {}

    try:
        endpoint_schema_names = transpile_endpoints(spec, ctx, max_endpoints=max_endpoints, resource_hint=resource_hint, patches_root=patches_root)
    except Exception as e:
        print(f"⚠️  Endpoint stage failed for {ctx['app_name']}: {e}")
        stage_errors["endpoints"] = str(e)
        endpoint_schema_names = []

    # Runs regardless of whether transpile_endpoints produced anything —
    # a node can be the ONLY source of a schema_name for a spec-less app,
    # so this has to happen BEFORE the "nothing found, skip" check below,
    # not after it.
    endpoint_schema_names = apply_nodes(patches_root, ctx["category"], ctx["app_name"], ctx["target_dir"], endpoint_schema_names, ctx=ctx)

    try:
        auth_schema_name = extract_oauth_config(spec, ctx, patches_root=patches_root)
    except Exception as e:
        print(f"⚠️  OAuth stage failed for {ctx['app_name']}: {e}")
        stage_errors["oauth"] = str(e)
        auth_schema_name = None

    if not endpoint_schema_names and not auth_schema_name:
        print(f"⚠️  Skipping metadata/index for {ctx['app_name']}: No valid endpoints or auth found.")
        return {
            "app_name": ctx["app_name"],
            "category": ctx["category"],
            "target_dir": ctx["target_dir"],
            "endpoints_transpiled": 0,
            "schema_names": [],
            "oauth_config_found": False,
            "auth_schema_name": None,
            "favicon_fetched": False,
            "stage_errors": stage_errors,
            "last_updated": ctx["last_updated"],
        }

    try:
        metadata = extract_app_metadata(spec, ctx, fetch_favicon=fetch_favicon, patches_root=patches_root)
        favicon_fetched = metadata["favicon_local_path"] is not None
    except Exception as e:
        print(f"⚠️  Metadata stage failed for {ctx['app_name']}: {e}")
        stage_errors["metadata"] = str(e)
        favicon_fetched = False

    try:
        write_schema_index(ctx, endpoint_schema_names, auth_schema_name, patches_root=patches_root)
    except Exception as e:
        print(f"⚠️  Index stage failed for {ctx['app_name']}: {e}")
        stage_errors["index"] = str(e)

    summary = {
        "app_name": ctx["app_name"],
        "category": ctx["category"],
        "target_dir": ctx["target_dir"],
        "endpoints_transpiled": len(endpoint_schema_names),
        "schema_names": endpoint_schema_names,
        "oauth_config_found": auth_schema_name is not None,
        "auth_schema_name": auth_schema_name,
        "favicon_fetched": favicon_fetched,
        "stage_errors": stage_errors,
        "last_updated": ctx["last_updated"],
    }

    status = "✅" if not stage_errors else "⚠️ partial"
    print(
        f"{status} Done: {summary['endpoints_transpiled']} endpoints, "
        f"oauth={summary['oauth_config_found']}, "
        f"favicon={summary['favicon_fetched']} "
        f"→ {summary['target_dir']}"
    )
    return summary

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Transpile one OpenAPI spec into the universal schema DSL.")
    parser.add_argument("spec_file", nargs="?", default="sample_spec.json", help="Path to the OpenAPI spec (.json)")
    parser.add_argument("--output-dir", default="../schemas", help="Root output directory")
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Only transpile the first N endpoints — for a quick local test run against a "
             "large spec. Leave unset for a real catalog run; this exists for fast "
             "iteration, not for trimming what actually ships.",
    )
    parser.add_argument("--no-favicon", action="store_true", help="Skip favicon download")
    args = parser.parse_args()

    transpile_full(
        args.spec_file,
        base_output_dir=args.output_dir,
        fetch_favicon=not args.no_favicon,
        max_endpoints=args.limit,
    )