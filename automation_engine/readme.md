# Piper Engine

Bare-metal / offline bootstrap for the Piper automation engine — a self-hosted stack for running automated Python/Node workloads behind a secured Docker socket, with a web frontend, Postgres-backed persistence, and an optional Ngrok tunnel for external access.

One script (`setup_v4.sh`) provisions the entire stack: it generates credentials, writes a locked-down Nginx config, builds the Docker Compose topology on the fly, validates it, and brings everything up with health checks — all without requiring a pre-existing `docker-compose.yml`.

---

## Architecture

```
                        ┌─────────────┐
   Internet / LAN ───▶  │    nginx    │  (only port exposed to the host)
                        └──────┬──────┘
                               │ X-Piper-Secret header required
                        ┌──────▼──────┐
                        │ piper-servers│──▶ piper-frontend (Next.js, :3000)
                        └──────┬──────┘
                               │
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                        ▼
 piper-manager         piper-controller           piper-services
                               │
              ┌────────────────┼─────────────────┐
              ▼                ▼                  ▼
        docker-proxy     redis-broker        Postgres (db)
     (locked-down Docker  (task_queue,
          API)           pipeline_stream)
              │
   ┌──────────┴──────────────────────────────┐
   ▼                                          ▼
piper-worker-0..N                    piper-runner-<lang>
(warm pool, runs                     (python/js/ts/php/go/rust/
 run_worker.py,                       java/cpp/csharp — idle,
 scaled to MAX_WORKERS)                docker-exec'd into per task)
```

All services communicate over an internal `piper-network` Docker network. The only container listening on the host is `nginx` (plus `certbot` for renewals and `piper-frontend`/`piper-controller`, which expose dev ports directly — see [Ports](#ports-exposed-to-the-host)).

Direct access to the Docker daemon is never given to application containers. Instead, `docker-proxy` (`tecnativa/docker-socket-proxy`) sits in front of the real socket and only allows a restricted set of API calls (container/image/network/volume management — no `exec`, no `build`, no swarm operations).

---

## Controller: a lightweight, Kubernetes-style scheduler

`piper-controller` runs [`controller/watcher.py`](./controller/watcher.py) (see `entrypoint` in the generated Compose config) and is the piece that actually keeps the execution layer alive. It's not just a task dispatcher — it runs a continuous reconciliation loop that behaves a lot like a stripped-down kubelet/scheduler combo, scoped to a single host instead of a cluster:

- **Capacity-aware scheduling.** Before spawning anything, the controller queries the Docker daemon's own `info()` for total host memory and derives how many language-runner containers it can safely support (`total_memory_gb / 1.5`, capped at 10, overridable via `MAX_LANGUAGE_CONTAINERS`) — the same idea as a Kubernetes scheduler checking node capacity before placing a pod.
- **Declarative reconciliation, not one-shot provisioning.** `sync_language_runners()` is handed a desired list of languages and diffs it against what's actually running: it stops/removes runner containers that are no longer wanted and starts/creates ones that are missing. That's the same "desired state vs. actual state" loop a ReplicaSet controller runs — just implemented directly against the Docker API instead of etcd.
- **A warm pool with self-healing.** `init_worker_pool()` maintains `MAX_WORKERS` `piper-worker-*` containers at all times. The main loop re-checks the pool's size on every iteration and refills it if any workers have died — analogous to a ReplicaSet keeping replica count at spec.
- **Resource requests/limits, enforced by cgroups.** Every runner and worker container gets an explicit `mem_limit` and `nano_cpus` (`RUNNER_MEM_LIMIT`/`RUNNER_CPU_LIMIT`, `WORKER_MEM_LIMIT`/`WORKER_CPU_LIMIT`) — the same cgroup mechanism Kubernetes' resource requests/limits ultimately compile down to, preventing one runaway user script from starving the rest of the host.
- **Liveness-style eviction.** Every 30 seconds the controller pulls live memory stats per worker and restarts (`recycles`) any worker above 85% of its memory limit — functionally a liveness probe with automatic pod restart.
- **Exec-based task execution, not per-task containers.** Runner containers don't run the user's language interpreter directly — they idle on `tail -f /dev/null`, and the executor `docker exec`s into them per task. This keeps startup latency near zero (no cold container start per job) at the cost of weaker isolation between consecutive tasks on the same runner — worth knowing if you're running untrusted code.
- **Queue-fed dispatch.** The controller blocks on a Redis list (`task_queue`), and on each task writes an individual payload key (`task_payload:<id>`) and pushes onto a shared `pipeline_stream` for consumer-group-based fan-out to the worker pool — the rough equivalent of a scheduler binding a pod to a queue of pending work.

It's a single-host, single-process version of what Kubernetes does with a scheduler + kubelet + ReplicaSet controller + liveness probes — useful to understand if you're debugging why a runner or worker container disappeared or got recycled: it almost certainly wasn't manual, the controller's reconciliation loop did it on purpose.

---

## Prerequisites

- **Docker** and either the `docker compose` plugin (v2) or the standalone `docker-compose` binary
- **OpenSSL** (used to generate secrets; the script falls back to timestamp-based values if unavailable, but this is not recommended for anything beyond local testing)
- **Bash** — on Windows, use **Git Bash**. The script auto-detects `msys`/`cygwin` and adjusts host paths and Docker socket wiring accordingly.
- A Docker daemon that's actually running before you start (`docker info` must succeed)

---

## Quick start

## Quick start

To provision and run the stack instantly via remote execution:

```bash
curl -fsSL [https://raw.githubusercontent.com/philz-dev/piper_engine/main/setup_v4.sh](https://raw.githubusercontent.com/philz-dev/piper_engine/main/setup_v4.sh) | bash

```bash
git clone https://github.com/philz-dev/piper_engine.git
cd your-repo
sh setup_v4.sh
```

On first run you'll be prompted for an optional **Ngrok authtoken** (press Enter to skip — the tunnel is disabled by default). Everything else is generated automatically.

The script will:

1. Check for required tools and a running Docker daemon
2. Generate (or reuse) `DATABASE_URL`, `INSTALL_TOKEN`, `PIPER_ADMIN_SECRET`, and `MASTER_PASSWORD` into `.env`
3. Detect whether it's running on a local machine or a headless/cloud host
4. Write a locked-down Nginx config to `./.piper_internal/nginx.conf`
5. Build and validate the full Compose configuration in memory (no `docker-compose.yml` is checked into the repo)
6. Tear down any previous stack cleanly and bring the new one up
7. Wait for Postgres to become healthy, then verify every service actually stayed running
8. Install a global `piper` CLI wrapper and run `piper init`

On success you'll see:

```
✅ SUCCESS: Piper Engine Online & Secured (Bare Mode)
```

---

## Configuration

All configuration lives in a git-ignored `.env` file, created automatically on first run. You generally shouldn't need to edit it by hand, but the relevant keys are:

| Variable | Purpose | Default |
|---|---|---|
| `NGINX_HTTP_PORT` / `NGINX_HTTPS_PORT` | Host ports for the reverse proxy. Override if 80/443 are already taken (common on Windows, e.g. IIS or Skype). | `80` / `443` |
| `NGROK_AUTHTOKEN` | Enables the optional tunnel. `disabled` skips it. | `disabled` |
| `INSTALL_TOKEN` / `PIPER_API_KEY` | Shared install/API token used by manager, controller, and servers. | generated |
| `PIPER_ADMIN_SECRET` | Required as the `X-Piper-Secret` request header to reach anything behind Nginx. | generated |
| `MASTER_PASSWORD` | Internal service auth secret. | generated |
| `DATABASE_URL` | Postgres connection string. | generated |

> **Regenerating credentials:** delete `.env` and rerun the script. Existing values are otherwise reused across runs so containers don't get invalidated on every restart.

### Reaching the app through Nginx

The generated Nginx config rejects any request that doesn't carry the admin secret:

```bash
curl -H "X-Piper-Secret: $(grep PIPER_ADMIN_SECRET .env | cut -d= -f2)" http://localhost/
```

---

## Ports exposed to the host

| Port | Service |
|---|---|
| `80` / `443` (configurable) | nginx (reverse proxy, gated by `X-Piper-Secret`) |
| `3000` | piper-frontend |
| `8001` | piper-controller |
| `8003` | piper-services |
| `8099` | piper-servers |
| `50000–50050/udp`, `50000–50011/tcp` | piper-servers (media/runner ports) |

Everything else (`db`, `redis-broker`, `docker-proxy`, `piper-manager`, the runner containers) is internal-only.

---

## The `piper` CLI

After setup, a `piper` wrapper is installed to `~/piper_bin` and added to your `PATH`. It runs the `piper-manager` image against your current directory and the `piper-network`, so it always operates on the stack you just started — and, like every other service in the stack, it talks to Docker through `docker-proxy` (`DOCKER_HOST=tcp://docker-proxy:2375`) rather than the host daemon, so it inherits the same locked-down API surface (no `exec`, no `build`, etc.).

`piper-manager` is where the CLI actually lives — its entrypoint is [`manager/core.py`](./manager/core.py), a `click`-based tool that goes well beyond starting/stopping the local stack. Under the hood it's a small multi-tenant fleet manager: each **client** gets its own `templates/<client>/` directory (a `waterfall.yml` pipeline definition, an encrypted `.piper_vault` for that client's secrets, and its own `.env`), and the CLI can spin up a dedicated `<client>_engine` container per client on demand.

Everything sensitive is gated behind a **Master Password**, set once via `piper create password` (or interactively on first run) and checked with `verify_password()` before any destructive or secret-touching command runs.

| Command | Purpose |
|---|---|
| `piper init` | Zero-touch setup — verifies the master password vault, creates DB tables, creates `logs/`, `templates/`, `temp_downloads/`. Runs automatically at the end of `setup_v4.sh`. |
| `piper start [clients...]` / `piper stop [clients...]` | Start or stop specific clients (or the whole fleet if none named). |
| `piper status` | Lists all running `*_engine` containers and their status. |
| `piper logs -c <client>` | Streams `docker logs -f` for a specific client's engine container. |
| `piper stats` | Aggregates live CPU/memory usage across every running container into one summary panel. |
| `piper inspect -c <client> <task>` | Pulls a task's stored execution context out of Postgres and renders it as a table. |
| `piper update [-c client \| --all]` | Checks GitHub for a newer `piper-engine` release, pulls it, and rolls one or all clients onto it. |
| `piper secrets set <key> -c <client>` | Encrypts and stores a per-client secret (e.g. a third-party API key) in that client's vault. |
| `piper removeapi <service_key> -c <client>` | Removes a single secret from a client's vault. |
| `piper reset` / `piper resetcontext` | Wipes and recreates `pipeline_storage` / the context table. |
| `piper dropall` | 🚨 Drops **every** table in the database. Requires explicit confirmation plus the master password. |

> Several commands in `core.py` (`startttt`, `startooo`, `stopoooo`, `stoppppppp`) are older iterations left in place alongside their replacements (`start`, `stop`, `dep`) — if you're extending the CLI, check which variant is actually wired into `setup_build.py` before assuming a given command is the live one.

---

## Troubleshooting

**A port is already in use**
The script detects `bind:` / `address already in use` errors on `up` and tells you which port conflicted. Set `NGINX_HTTP_PORT` / `NGINX_HTTPS_PORT` in `.env` to something free (e.g. `8080` / `8443`) and rerun.

**Database takes a long time to become ready**
Expected after an unclean shutdown, especially on Docker Desktop for Windows where volume I/O is slower. The script waits up to 5 minutes by default (`DB_WAIT_TIMEOUT`, in seconds) and prints Postgres's own log lines every 20s so you can see whether it's recovering or actually stuck.

**A service is stuck restarting after `up`**
The post-start health check will list any container not in a `running` state. Check its logs:
```bash
docker logs <container-name>
```
A common cause for `nginx` specifically is a startup race: its config resolves the `piper-engine-servers` hostname at boot, and if that container isn't fully registered on the Docker network yet, nginx exits and restarts in a loop. Retrying (`docker restart piper-nginx`) after the rest of the stack is up usually resolves it.

**Domain unexpectedly not `localhost` in the printed Nginx line**
The bare/offline profile hardcodes a local configuration, but `.env` values from a previous run (or a different deployment mode) are loaded and take precedence over the script's defaults. If you see an unexpected domain in the "Nginx config generated" line, check:
```bash
grep USER_DOMAIN .env
```
and remove that line if you want the plain local behavior.

**`piper <command>` fails with `host.docker.internal:2375 ... Network is unreachable`**
This was a bug in the generated `piper` wrapper (fixed as of this version): it hardcoded `DOCKER_HOST=tcp://host.docker.internal:2375`, which only works if Docker Desktop's insecure "expose daemon on tcp://localhost:2375" setting is manually enabled, and bypasses `docker-proxy` even when it does. If you're hitting this, delete `~/piper_bin/piper` and rerun `setup_v4.sh` to regenerate the wrapper with the corrected `DOCKER_HOST=tcp://docker-proxy:2375`.

---

## Security notes

- The Docker socket is never mounted into application containers directly — only into `docker-proxy`, with `EXEC`, `BUILD`, `SERVICES`, `TASKS`, `SECRETS`, `CONFIGS`, `NODES`, and `SWARM` all disabled on the proxied API.
- The generated `nginx.conf` is `chmod 600` and requires a secret header for any request to reach the app.
- `.env` contains live secrets (DB password, admin secret, install token, and your Ngrok authtoken if set). **Do not commit it** — make sure it's in `.gitignore`. If it's ever been shared or exposed, rotate everything by deleting `.env` and rerunning.
- `piper dep -c <client>` writes the Master Password directly into that client's generated Compose config, both as `MASTER_PASSWORD` and as the literal Postgres password in `DATABASE_URL` — it never goes through the separately-generated `DB_PASSWORD` in `.env`. That config is streamed straight into `docker compose up`, but the same string is also what `docker inspect`/`docker compose config` will show in plaintext for that container going forward. Worth hardening before running this in anything beyond a trusted local setup.

---

## License

Stretis Engine is source-available under the **Stretis Sustainable Use License** (see [`LICENSE.md`](./LICENSE.md)) — modeled on the "fair-code" approach used by projects like n8n. In short: free to use, modify, and self-host for internal or personal purposes; reselling it, or offering it as a hosted service to third parties, requires a separate commercial agreement.