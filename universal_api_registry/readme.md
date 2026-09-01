# universal_api_registry

Turn a public API description (OpenAPI, Google Discovery, GraphQL, AsyncAPI)
into one consistent, UI-ready schema DSL — on demand, locally, from
whatever source you point it at. No bundled catalog and redistribution of
anyone's API specs but your own generated output, which stays entirely on
your machine unless you choose to publish it.

Built for solo and small-team developers building automation platforms who
need broad integration coverage without either (a) hand-writing hundreds of
API wrappers, or (b) depending on a hosted, metered, lock-in platform for
something as basic as "what does this API's request shape look like."

## Why this exists

Every existing "unified API" product — Merge, Pipedream, Nango — wants to
own more of your stack: hosted credential custody, hosted execution,
metered pricing that scales with your own users. This project takes the
opposite bet: it's a library, not a platform. The SDK never touches your
credentials or fires a request unless you wire it to. The transpiler
generates files on your disk that you own outright. Nothing here runs on
anyone else's servers.

## 🚀 Live Demo
![Universal API Registry Demo](universal_api_registry/demo/universal_api_registry_demo.gif)

## Architecture

```
universal_api_registry/
  transpiler/          # stretis-transpiler (Python) — the CLI: `stretis transpile`, `stretis manifest`
  sdks/
    python/             # stretis-sdk — PiperSDK, CredentialStore, PiperExecutor
    node/               # @stretis-labs/piper-sdk — PiperSDK, CredentialStore, PiperExecutor
```

## Components

| Package | What it does |
|---|---|
| `stretis-transpiler` | `converter.py` (the actual OpenAPI→DSL engine), `batch_transpile_manifest.py` (orchestrator), `manifest.json` (curated source list), `diff_catalog.py` (structural drift detection), `smoke_test.py` (live endpoint validation), wrapped in the `stretis` CLI |
| `stretis-sdk` | Consumes generated schemas at runtime: lists apps/actions for a picker UI, renders input forms from schema metadata, turns filled forms into a ready-to-fire `{method, url, headers, body}`, handles OAuth flow + credential storage (you supply the storage backend) |
| `@stretis-labs/piper-sdk` | Node.js port of `stretis-sdk` — same five-method contract, same generated schema files, same Postgres/your-own vault. Not a proxy in front of the Python SDK; a first-class alternative for a Node platform |

## Installation

We highly recommend installing `stretis-transpiler` inside a virtual environment. This ensures the `stretis` command is automatically added to your terminal path without any global system configuration.

**1. Create a virtual environment:**
```bash
python -m venv venv
```

**2. Activate it:**

**For macOS / Linux:**
```bash
source venv/bin/activate
```

**For Git Bash (Windows):**
```bash
source venv/Scripts/activate
```

**For Windows (Command Prompt / PowerShell):**
```bash
venv\Scripts\activate
```

**3. Install the Transpiler:**
```bash
pip install stretis-transpiler
```

## Quick start

```bash
stretis transpile stripe asana        # generate schemas for specific apps
stretis transpile                     # or every app in the manifest
stretis transpile --check-drift --smoke-test   # re-check what's already generated for drift
```

## Install the PiperSdk

```bash
pip install stretis-sdk
```

To see the entire lifecycle wired up in a drop-in FastAPI application—spanning setup, UI-facing picker routes, OAuth redirects, static token credential seeding, payload hydration, and safe execution—check out the complete example file:
* **[`quick_usage.py`](quick_usage.py)** (single-file example)
* **[`integration_example/`](integration_example/)** folder (located at the root of the repository)

## Install the Node.js SDK

```bash
npm install @stretis-labs/piper-sdk
```

Same five-method contract as `stretis-sdk`, same generated schema files, same `{method, url, headers, body}` output — just a Node-native port rather than a wrapper around the Python package:

```js
const { PiperSDK } = require('@stretis-labs/piper-sdk');
const { SqliteCredentialStore } = require('@stretis-labs/piper-sdk/credentialStore');
const { getCryptoEngine } = require('@stretis-labs/piper-sdk/encryptionManager');

const cryptoEngine = getCryptoEngine(process.env.PIPER_SECRET_KEY);
const store = new SqliteCredentialStore(process.env.PIPER_DB_PATH || "credentials.db", cryptoEngine);

const sdk = new PiperSDK({
  store,
  // Base callback URL this app hosts — the SDK appends the app name to it
  // per OAuth flow (e.g. "http://127.0.0.1:8080/callback/hubspot").
  redirectBaseUrl: "http://127.0.0.1:8080/callback",
});

const form  = sdk.getInputForm("hubspot", "update_contact");
const ready = await sdk.buildSchema("acct_123", "hubspot", "update_contact",
                                     { "body.contactId": "42", "body.email": "a@b.com" });
```

To see the entire lifecycle wired up in a drop-in Express application—spanning setup, UI-facing picker routes, OAuth redirects, static app credential seeding, payload hydration, and safe execution—check out the complete example file:
* **[`integration_example/node_js/integration.js`](integration_example/node_js/integration.js)** (single-file example)


## How schema generation actually works

`manifest.json` maps an app name to a **source** — not a pre-fetched
file. Every `stretis transpile` run fetches fresh from that source and
transpiles locally. Three source shapes exist today, matching how
real vendors actually publish specs:

- **`official_url`** — one static file (Slack, Atlassian/Jira)
- **`github_repo`** / **`multi_file`** — a vendor's own GitHub repo, single
  file or a whole directory of per-product files (Stripe, OpenAI, GitHub,
  Discord, Asana, DocuSign, Plaid, PayPal, Twilio)
- **`official_api_index`** — a vendor's own live discovery endpoint that
  returns a JSON index of available specs, re-resolved fresh every run
  rather than hardcoding a snapshot (HubSpot)

### Supplementary discovery sources

Not every app has a clean official spec. Two fallback discovery
mechanisms exist for that gap — both wired through the exact same
`github_repo`/`multi_file` mechanism above, no separate code path:

- **[apis.io](https://apis.io)** (`apis_io_fetch.py`) — a real, documented
  discovery API indexing thousands of providers beyond APIs.guru's
  coverage.
- **[API Evangelist](https://github.com/api-evangelist)** — an individually
  maintained GitHub organization profiling public API surfaces
  vendor-by-vendor. Reachable through the standard GitHub API
  (`api.github.com/repos/api-evangelist/<provider>/...`), so any entry
  there slots into `manifest.json` as an ordinary `github_repo` source.

**Both of these carry a materially different trust level than a vendor's
own repo — read the next section before using either for anything you
plan to redistribute.**

## Drift detection & live validation

```bash
stretis transpile --check-drift              # structural diff only, blocks on breaking changes
stretis transpile --check-drift --smoke-test  # + live GET requests against unchanged apps
```

`diff_catalog.py` classifies every change (field added/removed, type
changed, required flag flipped, endpoint added/removed) as
BREAKING/NOTABLE/COSMETIC and refuses to apply a breaking change without
`--force`. `smoke_test.py` catches the case structural diffing is blind
to — the vendor's spec *text* didn't change, but the live API no longer
matches what's already committed — using fake credentials, GET-only, with
a corrected response classifier (see `smoke_test.py`'s own docstring for
the specific bugs this fixes versus a naive "expect a 401" check).

## License & redistribution implications

**This project's own code — the transpiler, the SDK, the CLI — is
Apache-2.0.** That license covers exactly that: the code you're reading
in this repository. It does **not** extend any rights to the *content* of
any API description this tool generates a schema from. Those are two
separate things, and conflating them is exactly the mistake this project
exists to avoid making at scale.

### Why nothing is bundled and redistributed

Redistributing a derivative of someone else's published API description,
in bulk, on behalf of third-party vendors creates a fundamentally risky legal 
posture. That is why this project takes a different approach: **you** run
the transpiler, **you** fetch **you**'ve chosen to fetch, against sources
**you** can inspect, and the output lives on **your** disk under **your**
name. Nothing here operates as a bulk redistributor of vendor content.

### Three trust tiers — check which one applies before you redistribute anything you generate

**Tier 1 — Vendor's own official source** (`official_url`, `github_repo`,
`multi_file`, `official_api_index` entries whose `url` points at the
vendor's own domain or GitHub org — Stripe, OpenAI, GitHub, HubSpot,
Twilio, PayPal, Asana, DocuSign, Plaid, Slack, Discord, Atlassian in the
current manifest). This is the vendor's own artifact. It's still subject
to *their* terms — most vendor API description repos are published under
a permissive license for exactly this kind of tooling use, but **check
the specific repo's own LICENSE file or the vendor's API terms of
service before redistributing what you generate from it**, especially
before bundling it into a commercial product. A manifest entry's `note`
field flags anything unusual already found (e.g. PayPal's specs default
to their sandbox host, not production — see that entry).

**Tier 2 — APIs.guru** (used by `batch_transpile_manifest.py` for the broader,
non-manifest catalog). A community-maintained aggregator of specs that
are themselves generally sourced from vendors' own published files.
Aggregation doesn't create new rights beyond what the original vendor
granted — the same "check the source" rule applies, one hop removed.

**Tier 3 — apis.io and API Evangelist** — genuinely different, not just a
lower-confidence version of Tier 1. API Evangelist's own repos state this
directly, verbatim, on every profile: *"This is not our API. This
repository is an independent, third-party profile of a company's
publicly available API surface... API Evangelist does not operate, host,
resell, or support this company's APIs, and is not affiliated with or
endorsed by the company unless stated."* That's a candid, direct
statement from the source itself, not a limitation being called out here
externally. Some individual profiles do carry forward the original
license faithfully when the assembler cited a specific upstream
release — a few explicitly document exactly which official source they
harvested from and under what license — but this is **inconsistent
across profiles, not a project-wide guarantee**. Treat anything sourced
from Tier 3 as a *starting point for your own verification*, not a
cleared-for-redistribution artifact, until you've independently confirmed
what the underlying vendor actually permits.

### Practical rule of thumb

- Generating a schema and using it **privately**, inside your own
  platform, to fire requests against an API you already have legitimate
  access to — low risk, this is what the tool is for.
- **Redistributing** the generated schema file itself — as part of an
  open-source catalog, a commercial product, or anything a third party
  will receive from you — check the tier above, then check the specific
  vendor's actual terms. Tier 1 is usually fine; Tier 3 needs its own
  verification every time.

**This is factual context to help you make an informed decision, not
legal advice.** If redistribution at scale is central to your product,
talk to an actual lawyer about your specific situation — this project
generates artifacts for you to review, it doesn't make legal
determinations on your behalf.

"All product names, logos, brands, and trademarks are property of their respective owners. All company, product, and service names used in this repository are for identification purposes only."

## Contributing

See `manifest.json` for the format expected of a new source entry. A
`note` field is required for anything that isn't a single self-contained
file (multi-file repos, unusual server/version selection, anything a
future maintainer would otherwise have to rediscover by trial and
error) — see the existing entries for the expected level of detail.

**Hand-authoring a schema instead of adding a manifest source?** The
`method`/`url`/`class`/`headers`/`body`/`metadata.fields` structure and
the `{{DataType=..., Default=...}}` placeholder syntax are this project's
own format — reuse them freely for any app, official spec or not,
the same way any project's own schema shape is free to reuse.
The one rule that matters: field names, types, and endpoint paths are
functional facts — use the API's real names, you can't call it correctly
otherwise. But write every `description` and `label` from your own
understanding of what the field does, never lifted or lightly reworded
from a vendor's docs page — closely paraphrasing sentence-by-sentence
with synonyms swapped in doesn't count as "your own words." Set
`metadata.source` to `"community_authored"`, not the transpiler's default
`"transpiled_official"` — that field exists specifically so a consumer of
the catalog can tell at a glance which schemas came from an official spec
versus a contributor's own research.

## License

Apache-2.0 for the code in this repository. See
[License & redistribution implications](#license--redistribution-implications)
above for what that does and does not cover.