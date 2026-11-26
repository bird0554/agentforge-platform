# AgentForge

An extensible, self-hosted agent platform for building and observing tool-using agents. The project combines an async Python API, a React operations console, an auditable tool gateway, session memory, configurable MCP/A2A integrations, and a hardened Docker deployment profile.

中文生产使用说明见 [`docs/使用说明书.md`](docs/使用说明书.md)，Word 版见 [`docs/AgentForge系统使用说明书.docx`](docs/AgentForge系统使用说明书.docx)，运维值班流程见 [`docs/运维手册.md`](docs/运维手册.md)。

## Start locally

1. Copy `.env.example` to `.env`, replace `APP_SECRET` with a random value of at least 32 characters, and optionally set an OpenAI-compatible endpoint, API key, and model. Without credentials, the deterministic demo provider keeps the chat and tool loop usable.
2. Run `docker compose up --build`.
3. Open <http://localhost:8080>.

For development, run the API with `cd api && python -m pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`. Run the web console with `cd web && npm install && npm run dev`. Vite proxies `/api` to `http://127.0.0.1:8000` in local development. Set `VITE_API_URL` only when the API is hosted elsewhere.

On Windows without Docker Desktop, create `.data`, then run `uvicorn app.main:app --host 127.0.0.1 --port 8000` from `api/` and `npm run dev -- --port 5173` from `web/`. Open <http://localhost:5173>.

## Production deployment

Use the hardened Compose profile on a Linux host with Docker Engine and Compose v2. It requires `APP_SECRET` and never falls back to the development secret.

```bash
cp .env.example .env
# edit .env and set APP_SECRET, model settings, and WEB_ORIGIN
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
```

The API runs as a non-root user with a read-only root filesystem. The production profile uses PostgreSQL and requires an `APP_SECRET`, a PostgreSQL password, and signed HS256 Bearer JWTs on protected API routes. Agent requests remain synchronous and Redis is provisioned for future queue integration. Review the authentication and deployment constraints in [`docs/使用说明书.md`](docs/使用说明书.md) before exposing the operator console.

## Capabilities

- Async bounded Agent loop with ReAct, Plan-Execute prompting, and Self-Critique review modes, configurable history/context limits, tool traces, and demo or OpenAI-compatible model providers.
- Persisted model and Agent settings, encrypted API keys, model connection testing, configurable tool enablement, permission, and timeout policies.
- Tool registry with JSON Schema argument checks, redaction, audit records, and human approval before write actions.
- Tenant-scoped local sessions, conversation history, run inspection, approval queue, and metrics APIs.
- MCP HTTP client with encrypted headers, JSON-RPC tool discovery/calls, audit records, and automatic Agent tool registration. JSON and SSE event-stream responses are parsed over HTTP POST. Legacy SSE GET subscriptions, Streamable HTTP session IDs, and resumable streams are not implemented.
- A2A connection manager with encrypted bearer tokens, Agent Card discovery, JSON-RPC task delegation/query, and automatic delegation tools in the Agent loop. The runtime implements this request/response subset and does not provide push notifications or streaming task updates.
- SQLite-backed memory with tenant/user visibility, expiry, forgetting, CRUD APIs, and configurable retrieval/auto-capture policies. Its 512-dimensional deterministic hashed-term vectors provide local lexical similarity, not model-generated semantic embeddings or an external vector database.
- Docker code sandbox with network isolation, read-only containers, dropped capabilities, resource limits, and a registered `code_sandbox` Agent tool. Output is truncated after subprocess capture, so `max_output_chars` limits returned text but is not a hard memory bound while a process writes output.

The development profile uses a local fallback identity and SQLite. Production mode requires authenticated requests and tenant context, rejects weak or missing secrets, exposes dependency-aware health status, and keeps credentials encrypted at rest. SQLite remains a single-instance deployment boundary. PostgreSQL migration, centralized identity, and multi-replica coordination are required before horizontal scaling.

## Runtime settings API

`GET /api/settings` returns saved model, Agent, tool, sandbox, memory, MCP, and A2A settings. Secrets are never returned, only configuration flags are exposed.

`PUT /api/settings/model` accepts `provider` (`demo` or `openai-compatible`), `base_url`, `model`, `api_key`, `timeout_seconds`, `temperature`, and `max_tokens`. Unspecified values retain their current settings. Leave `api_key` out or send an empty value to retain the saved key. Send `clear_api_key: true` to clear it, which is allowed only when switching to demo mode. OpenAI-compatible endpoints require a valid HTTP(S) URL and a configured key. OpenAI-compatible services such as DeepSeek, Doubao, and DashScope can be configured by supplying their compatible endpoint, model name, and API key.

`POST /api/settings/model/test` accepts the same model fields and tests the supplied values without saving them. A blank or omitted `api_key` uses the saved key. The response reports success or a sanitized connection failure, including a recoverable message when an encrypted saved credential is no longer readable.

`PUT /api/settings/agent` accepts `name`, `system_prompt`, `mode` (`react`, `plan_execute`, or `self_critique`), `max_tool_rounds` (1–20), `history_window` (1–100), and `context_window_tokens` (512–128000). Changes affect new runs immediately and the configured Agent name appears in the workbench.

`PATCH /api/settings/tools/{name}` accepts `enabled`, `permission` (`read` or `write`), and `timeout_seconds`. The console displays `write` tools as requiring approval. Built-in write tools retain write permission and require approval. Disabled tools are hidden from model tool schemas and rejected at execution time.

`GET/PUT /api/sandbox/settings` configures the Docker image, timeout, memory, CPU, PID, and output limits. `POST /api/sandbox/run` executes code under those limits. Docker Desktop must be available when the sandbox is used.

`GET/PUT /api/memory/settings` controls enablement, retrieval, automatic capture, similarity threshold, and result limit. `/api/memory` and its `/api/memory/items` alias support listing and create operations, `/api/memory/search` performs similarity search, and the same resource IDs support update, delete, and forget operations. Memory records are scoped to the local tenant and optional user owner. Agent retrieval and automatic capture honor these settings on every new run.

`GET/PUT/DELETE /api/mcp/servers/{name}` manages MCP endpoints, transport, timeout, enabled state, and encrypted headers. Leave `headers` out to retain saved credentials, or send `clear_headers: true` to remove them. The console supports adding, editing, deleting, and rediscovering connections. `POST /api/mcp/servers/{name}/discover` persists tool schemas and makes them available to the Agent. `POST /api/mcp/servers/{name}/tools/{tool_name}/call` provides direct invocation. Dynamic MCP tools currently have no per-tool permission or approval configuration and are exposed as read operations.

`GET/POST/PUT/DELETE /api/a2a/agents` manages A2A connections, timeout, enabled state, and encrypted bearer tokens. Updates retain the saved token when `bearer_token` is omitted, or clear it with `clear_bearer_token: true`. The console supports adding, editing, deleting, and rediscovering connections. `POST /api/a2a/agents/{id}/discover` stores an Agent Card. `POST /api/a2a/agents/{id}/tasks` delegates a task and `GET /api/a2a/agents/{id}/tasks/{task_id}` queries it. Enabled connections also appear as Agent tools. A2A tools currently have connection-level enablement and timeout but no independent permission or approval configuration.

MCP and A2A tools use the same `/api/settings/tools/{name}` enablement, permission, and timeout controls as built-in tools. Marking a remote tool as `write` queues its invocation for approval. The remote call runs only after approval, duplicate concurrent approvals cannot start the same call twice, and both the decision and execution are audited.

Additional operational endpoints include `GET /api/agents/runs?limit=50&offset=0` and `DELETE /api/agents/sessions/{session_id}`. Deleting a session cancels its pending approvals and cascades its stored messages and runs.

In production, set `APP_ENV=production` and provide a unique `APP_SECRET` with at least 32 characters. Do not change `APP_SECRET` after saving encrypted model credentials unless those credentials are re-entered.

## Project layout

- `api/app/` contains the service, agent loop, model adapter, tools, storage, memory, and security controls.
- `api/tests/` contains focused API and agent behavior tests.
- `web/src/main.tsx` mounts the React operator console into the `#root` element, and `web/src/styles.css` contains its responsive interface styles.
- `docker-compose.yml` runs the API and web console with persistent local data.
- `docker-compose.production.yml` runs the hardened single-instance production profile.
- `docs/` describes architecture, extension points, and the implementation roadmap.

## Verification

Run `cd api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest` and `cd web && npm run build`.

