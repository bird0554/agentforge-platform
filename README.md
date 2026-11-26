# AgentForge

[English](README.md) | [简体中文](README.zh-CN.md)

An extensible, self-hosted agent platform for building and observing tool-using agents. The project combines an async Python API, a React operations console, an auditable tool gateway, session memory, configurable MCP/A2A integrations, and a hardened Docker deployment profile.

Additional Chinese documentation: [user manual](docs/使用说明书.md), [Word manual](docs/AgentForge系统使用说明书.docx), and [operations handbook](docs/运维手册.md). The [architecture guide](docs/architecture.md) describes the major components.

## Start locally

### Docker Compose

Requires Docker Engine or Docker Desktop with Compose v2.

1. Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell, or `cp .env.example .env` in a POSIX shell).
2. Replace `APP_SECRET` with a random value of at least 32 characters. Optionally set `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`. Without model credentials, the deterministic demo provider keeps the chat and tool loop usable.
3. Run the following command from the repository root, then open <http://localhost:8080>.

```shell
docker compose up --build
```

The development Compose file explicitly uses SQLite at `/data/agent-platform.db` in the persistent `agent_data` volume. The web container proxies `/api` to the API container. This profile uses a fallback local identity and is intended for local development.

### Run the source directly

The container builds use Python 3.12 and Node.js 22; use compatible versions for development. Run the API and web console in separate terminals.

API terminal, starting at the repository root:

```shell
cd api
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Web terminal, starting at the repository root:

```shell
cd web
npm install
npm run dev -- --port 5173
```

Open <http://localhost:5173>. Vite proxies `/api` to `http://127.0.0.1:8000`. Set `VITE_API_URL` only when the API is hosted elsewhere.

The API does not automatically load the root `.env` file outside Compose. Export configuration in the API process environment, or configure the model in the console. With no `DATABASE_URL`, the API creates `api/data/agent-platform.db` when started from `api/`; parent directories are created automatically. To choose another location, explicitly set `DATABASE_URL` (for example, `sqlite:///./.data/agent-platform.db`, relative to the API working directory).

### Common configuration

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development` uses a fallback identity; `production` requires bearer authentication. |
| `APP_SECRET` | Encryption secret; use a stable random value of at least 32 characters. |
| `DATABASE_URL` | SQLite or PostgreSQL connection URL. The development Compose file sets its own SQLite URL. |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` | Model defaults read by Compose and mapped to the API's `LLM_*` variables. A direct API process also accepts these names; `LLM_*` takes precedence. |
| `WEB_ORIGIN` | Allowed browser origin, including scheme and port. |
| `WEB_PORT` | Published web port in the production Compose file; default `8080`. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Production PostgreSQL initialization settings. |
| `REDIS_URL` | Redis connection setting; the current Agent run path does not use a background queue. |

Keep `.env` and credentials out of version control. Saved runtime settings can override initial environment defaults. Changing `APP_SECRET` can make previously encrypted model, MCP, and A2A credentials unreadable; retain it securely and re-enter credentials when rotating it.

## Production deployment

Use the hardened Compose profile on a Linux host with Docker Engine and Compose v2. Before launching it, edit `.env` and explicitly configure:

- A random `APP_SECRET` of at least 32 characters and a strong `POSTGRES_PASSWORD`.
- `DATABASE_URL=postgresql://<user>:<url-encoded-password>@postgres:5432/<database>`, with values matching `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`. The defaults for user and database are both `agentforge`. Replace the SQLite URL copied from `.env.example`; setting `POSTGRES_PASSWORD` alone does not update the API URL.
- `WEB_ORIGIN` matching the public console origin, any `WEB_PORT` override, and optional model settings.

```bash
cp .env.example .env
# Edit .env using the requirements above before starting services.
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
```

The API runs as a non-root user with a read-only root filesystem. PostgreSQL 16 and Redis 7 use persistent volumes. Agent requests remain synchronous; Redis is provisioned for future queue integration.

Protected `/api/*` routes require signed HS256 bearer JWTs in production. Tokens must carry `sub` and `tenant_id` (or `tid`); use expiring tokens issued by your identity integration. The verifier uses `AUTH_JWT_SECRET` when configured, otherwise `APP_SECRET`. The supplied Compose file passes `APP_SECRET`; a separate authentication secret requires adding `AUTH_JWT_SECRET` to the API container environment.

The console currently has no built-in end-user login/token acquisition flow. Integrate authentication and authenticated API requests before exposing it; starting the production containers alone does not complete this integration. Runtime settings share a configuration space and should be managed by trusted operators. Review the [user manual](docs/使用说明书.md) and [operations handbook](docs/运维手册.md) for deployment procedures.

`GET /api/health` is unauthenticated and reports API status and configured model/demo mode. It is not an end-to-end database, Redis, or model connectivity test. SQLite is suited to a single instance; PostgreSQL support is implemented, but migrating existing SQLite data, centralized identity, and multi-replica coordination remain deployment work before horizontal scaling.

## Capabilities

- Async bounded Agent loop with ReAct, Plan-Execute prompting, and Self-Critique review modes, configurable history/context limits, tool traces, and demo or OpenAI-compatible model providers.
- Persisted model and Agent settings, encrypted API keys, model connection testing, configurable tool enablement, permission, and timeout policies.
- Tool registry with JSON Schema argument checks, redaction, audit records, and human approval before write actions.
- Tenant-scoped local sessions, conversation history, run inspection, approval queue, and metrics APIs.
- MCP HTTP client with encrypted headers, JSON-RPC tool discovery/calls, audit records, and automatic Agent tool registration. JSON and SSE event-stream responses are parsed over HTTP POST. Legacy SSE GET subscriptions, Streamable HTTP session IDs, and resumable streams are not implemented.
- A2A connection manager with encrypted bearer tokens, Agent Card discovery, JSON-RPC task delegation/query, and automatic delegation tools in the Agent loop. The runtime implements this request/response subset and does not provide push notifications or streaming task updates.
- Database-backed memory (SQLite or PostgreSQL) with tenant/user visibility, expiry, forgetting, CRUD APIs, and configurable retrieval/auto-capture policies. Its 512-dimensional deterministic hashed-term vectors provide local lexical similarity, not model-generated semantic embeddings or an external vector database.
- Docker code sandbox with network isolation, read-only containers, dropped capabilities, resource limits, and a registered `code_sandbox` Agent tool. Output is truncated after subprocess capture, so `max_output_chars` limits returned text but is not a hard memory bound while a process writes output.

The code sandbox requires the Docker CLI and a reachable Docker daemon in the environment where the API process runs. The supplied API container does not include the CLI or mount a Docker socket, so the standard Compose launch does not automatically enable sandbox execution. Configure a suitable execution environment before using it.

## Using the console and API

1. Open the console, select the demo provider or configure and test an OpenAI-compatible model in settings, then save it.
2. Start a session in the workbench. Review tool traces and run history as the Agent responds.
3. Inspect write requests in the approval queue and explicitly approve or reject them.
4. Configure memory, tool policies, MCP servers, and A2A connections in their respective settings panels.

For a local development instance, a PowerShell API example is:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8080/api/health'
$body = @{ message = 'Explain how tool approvals work.' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://localhost:8080/api/agents/runs' -ContentType 'application/json' -Body $body
```

Use port `5173` through Vite, or `8000` directly, when running the source. Production API clients must also send `Authorization: Bearer <token>`.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/agents/runs` | Run an Agent with `message` and optional `session_id`. |
| `GET /api/agents/runs?limit=50&offset=0` | List persisted runs. |
| `GET /api/agents/runs/{run_id}` | Inspect one run. |
| `GET /api/agents/sessions` | List sessions. |
| `GET /api/agents/sessions/{session_id}` | Read a session and its messages. |
| `DELETE /api/agents/sessions/{session_id}` | Delete stored messages/runs and cancel pending approvals for the session. |
| `GET /api/approvals` | List pending approvals. |
| `POST /api/approvals/{approval_id}/decision` | Submit `{"decision":"approve"}` or `{"decision":"reject"}`. |
| `GET /api/tools` | Inspect registered tools and their policies. |
| `GET /api/metrics/summary` | Read aggregate operational metrics. |

## Runtime settings API

`GET /api/settings` returns saved model, Agent, tool, sandbox, memory, MCP, and A2A settings. Secrets are never returned, only configuration flags are exposed.

`PUT /api/settings/model` accepts `provider` (`demo` or `openai-compatible`), `base_url`, `model`, `api_key`, `timeout_seconds`, `temperature`, and `max_tokens`. Unspecified values retain their current settings. Leave `api_key` out or send an empty value to retain the saved key. Send `clear_api_key: true` to clear it, which is allowed only when switching to demo mode. OpenAI-compatible endpoints require a valid HTTP(S) URL and a configured key. OpenAI-compatible services such as DeepSeek, Doubao, and DashScope can be configured by supplying their compatible endpoint, model name, and API key.

`POST /api/settings/model/test` accepts the same model fields and tests the supplied values without saving them. A blank or omitted `api_key` uses the saved key. The response reports success or a sanitized connection failure, including a recoverable message when an encrypted saved credential is no longer readable.

`PUT /api/settings/agent` accepts `name`, `system_prompt`, `mode` (`react`, `plan_execute`, or `self_critique`), `max_tool_rounds` (1–20), `history_window` (1–100), and `context_window_tokens` (512–128000). Changes affect new runs immediately and the configured Agent name appears in the workbench.

`PATCH /api/settings/tools/{name}` accepts `enabled`, `permission` (`read` or `write`), and `timeout_seconds`. The console displays `write` tools as requiring approval. Built-in write tools retain write permission and require approval. Disabled tools are hidden from model tool schemas and rejected at execution time.

`GET/PUT /api/sandbox/settings` configures the Docker image, timeout, memory, CPU, PID, and output limits. `POST /api/sandbox/run` executes code under those limits. The API process must meet the Docker sandbox prerequisites described above.

`GET/PUT /api/memory/settings` controls enablement, retrieval, automatic capture, similarity threshold, and result limit. `/api/memory` and its `/api/memory/items` alias support listing and create operations; `/api/memory/search` performs similarity search. Resource IDs support reading, updating, and deleting records; `POST /api/memory/forget` handles forgetting. Memory records are scoped to the tenant and optional user owner. Agent retrieval and automatic capture honor these settings on every new run.

`GET /api/mcp/servers` lists MCP connections; `PUT/DELETE /api/mcp/servers/{name}` manages endpoints, transport, timeout, enabled state, and encrypted headers. Leave `headers` out to retain saved credentials, or send `clear_headers: true` to remove them. The console supports adding, editing, deleting, and rediscovering connections. `POST /api/mcp/servers/{name}/discover` persists tool schemas and makes them available to the Agent. `POST /api/mcp/servers/{name}/tools/{tool_name}/call` provides direct invocation and respects the configured approval policy.

`GET/POST /api/a2a/agents` lists or creates A2A connections; `PUT/DELETE /api/a2a/agents/{id}` updates or deletes them. Settings include timeout, enabled state, and encrypted bearer tokens. Updates retain the saved token when `bearer_token` is omitted, or clear it with `clear_bearer_token: true`. The console supports adding, editing, deleting, and rediscovering connections. `POST /api/a2a/agents/{id}/discover` stores an Agent Card. `POST /api/a2a/agents/{id}/tasks` delegates a task and `GET /api/a2a/agents/{id}/tasks/{task_id}` queries it. Enabled connections also appear as Agent tools.

MCP and A2A tools use the same `/api/settings/tools/{name}` enablement, permission, and timeout controls as built-in tools. Newly discovered remote tools default to `read`; review and classify them before enabling automated use. Marking a remote tool as `write` queues its invocation for approval. The remote call runs only after approval, duplicate concurrent approvals cannot start the same call twice, and both the decision and execution are audited.

## Project layout

| Path | Contents |
| --- | --- |
| `api/app/main.py` | FastAPI application, runtime settings, runs, sessions, approvals, and metrics routes. |
| `api/app/agent.py`, `provider.py`, `runtime.py` | Agent loop, model integration, and execution context. |
| `api/app/tools.py`, `sandbox.py` | Tool registry, approvals, and Docker code execution. |
| `api/app/database.py`, `vector_memory.py` | SQLite/PostgreSQL storage and local similarity memory. |
| `api/app/auth.py`, `settings.py`, `security.py` | Request identity, persisted settings, encryption, and redaction. |
| `api/app/mcp.py`, `a2a_runtime.py` | Remote MCP and A2A integrations. |
| `api/tests/`, `api/requirements.txt`, `api/Dockerfile` | Backend tests, dependencies, and image build. |
| `web/src/main.tsx`, `web/src/styles.css` | React console and responsive styles. |
| `web/package.json`, `web/vite.config.ts` | Frontend scripts, dependencies, and development proxy. |
| `web/Dockerfile`, `web/nginx.conf` | Frontend image build and API reverse proxy. |
| `docker-compose.yml` | Local API/web deployment with persistent SQLite data. |
| `docker-compose.production.yml` | Hardened deployment with PostgreSQL and Redis. |
| `.env.example` | Non-secret configuration template. |
| `docs/` | Architecture, user documentation, and operations procedures. |

## Verification

After installing dependencies, run backend tests from `api/`:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest
```

In a POSIX shell, use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest`. Build the frontend from `web/`:

```shell
npm run build
```

These checks validate code behavior and the frontend build; they do not establish live model, remote MCP/A2A, Docker sandbox, or production authentication connectivity. Verify those integrations separately in the intended environment.
