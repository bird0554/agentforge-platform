# Architecture

The platform is split into a browser console and an asynchronous FastAPI service. The API owns tenant-scoped session state, the bounded agent loop, model-provider normalization, tool authorization, approval state, and audit events. A run emits ordered events so clients can render planning, tool calls, results, and completion as one trace.

The default provider is deterministic and suitable for a first local run. An OpenAI-compatible provider can be enabled through environment configuration. Provider credentials stay server-side.

Tools are registered with JSON Schema and permission metadata. Arguments are validated before execution. Read operations may run directly while consequential operations produce a pending approval. Tool execution has a timeout and records a redacted audit event. Code execution is deliberately not exposed as a host-process tool. Any future code runner must use a separate constrained container or sandbox service.

SQLite is the zero-configuration development store. Repository boundaries keep storage and memory behind service interfaces so PostgreSQL and Redis can be introduced without changing the UI contract. MCP discovery/calls, A2A task exchange, vector retrieval, business connectors, and policy integrations are extension points rather than falsely claimed production integrations.

