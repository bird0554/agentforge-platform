# AgentForge

An extensible, self-hosted agent platform starter for building and observing tool-using agents. The project combines an async Python API, a React operations console, an auditable tool gateway, session memory, and a local Docker deployment.

## Start locally

1. Copy `.env.example` to `.env` and optionally set an OpenAI-compatible endpoint, API key, and model. Without credentials, the deterministic demo provider keeps the chat and tool loop usable.
2. Run `docker compose up --build`.
3. Open <http://localhost:8080>.

For development, run the API with `cd api && python -m pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`. Run the web console with `cd web && npm install && npm run dev`.

## Capabilities

- Async ReAct-style run loop with bounded iterations, model adapters, event traces, retryable failures, and deterministic demo mode.
- Tool registry with JSON Schema validation, permission labels, timeouts, redaction, audit records, and human approval for consequential actions.
- Tenant-scoped sessions and short-term conversation memory with context-window trimming.
- Agent run, tool, approval, session, and metrics APIs with a console for inspection and interaction.
- Extension points and documented protocol boundaries for MCP, A2A, vector memory, business connectors, and isolated code execution.

The starter is intended for local evaluation and extension. Production deployments should configure a durable database, identity provider, secrets management, network policy, and an isolated sandbox for untrusted code.

## Project layout

- `api/app/` contains the service, agent loop, model adapter, tools, storage, memory, and security controls.
- `api/tests/` contains focused API and agent behavior tests.
- `web/src/` contains the operator console and API client.
- `docker-compose.yml` runs the API and web console with persistent local data.
- `docs/` describes architecture, extension points, and the implementation roadmap.

## Verification

Run `cd api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest` and `cd web && npm run build`.

