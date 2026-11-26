# AgentForge

[English](README.md) | [简体中文](README.zh-CN.md)

AgentForge 是一个可自行部署、可扩展的智能体平台，用于构建和观察能够调用工具的 Agent。项目提供异步 Python API、React 管理控制台、带审计的工具网关、会话记忆、可配置的 MCP/A2A 集成，以及加固的 Docker 部署配置。

配套文档：[使用说明书](docs/使用说明书.md)、[Word 版说明书](docs/AgentForge系统使用说明书.docx)、[运维手册](docs/运维手册.md)和[架构说明](docs/architecture.md)。

## 本地启动

### Docker Compose

需要安装 Docker Engine 或 Docker Desktop，并具备 Compose v2。

1. 将 `.env.example` 复制为 `.env`。PowerShell 使用 `Copy-Item .env.example .env`；POSIX Shell 使用 `cp .env.example .env`。
2. 将 `APP_SECRET` 替换为至少 32 个字符的随机值。可选配置 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `OPENAI_MODEL`。未配置模型凭据时，系统使用确定性的演示模型，仍可体验对话和工具调用流程。
3. 在仓库根目录运行以下命令，然后访问 <http://localhost:8080>。

```shell
docker compose up --build
```

开发 Compose 文件固定使用 SQLite，数据库位于持久卷 `agent_data` 中的 `/data/agent-platform.db`。Web 容器将 `/api` 请求转发给 API 容器。此配置使用本地默认身份，适用于本地开发。

### 从源码启动

容器构建使用 Python 3.12 和 Node.js 22；本地开发请使用兼容版本。分别打开两个终端运行后端和前端。

后端终端，从仓库根目录开始：

```shell
cd api
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端终端，从仓库根目录开始：

```shell
cd web
npm install
npm run dev -- --port 5173
```

访问 <http://localhost:5173>。Vite 将 `/api` 转发到 `http://127.0.0.1:8000`。只有 API 部署在其他地址时，才需要设置 `VITE_API_URL`。

直接启动 API 时不会自动读取仓库根目录的 `.env`。请在 API 进程的环境变量中设置配置，或在控制台配置模型。没有设置 `DATABASE_URL` 时，从 `api/` 启动会创建 `api/data/agent-platform.db`，父目录由程序自动创建。如需指定其他位置，请显式设置 `DATABASE_URL`，例如 `sqlite:///./.data/agent-platform.db`，其中相对路径以 API 的工作目录为准。

### 常用配置

| 变量 | 用途 |
| --- | --- |
| `APP_ENV` | `development` 使用本地默认身份；`production` 要求 Bearer 身份验证。 |
| `APP_SECRET` | 凭据加密密钥，应使用稳定保存且至少 32 个字符的随机值。 |
| `DATABASE_URL` | SQLite 或 PostgreSQL 连接地址。开发 Compose 文件会指定自己的 SQLite 地址。 |
| `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` | Compose 读取的模型默认配置，会映射到 API 的 `LLM_*` 变量。直接启动 API 也支持这些名称，优先使用 `LLM_*`。 |
| `WEB_ORIGIN` | 允许的浏览器来源，包含协议和端口。 |
| `WEB_PORT` | 生产 Compose 对外发布的 Web 端口，默认 `8080`。 |
| `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD` | 生产 PostgreSQL 初始化参数。 |
| `REDIS_URL` | Redis 连接配置；当前 Agent 运行流程尚未接入后台任务队列。 |

不要将 `.env` 或凭据提交到版本控制。已保存的运行时配置可能覆盖初始环境变量。更换 `APP_SECRET` 可能导致之前加密保存的模型、MCP 和 A2A 凭据无法读取；应安全保管该密钥，轮换时重新录入相关凭据。

## 生产部署

在安装 Docker Engine 和 Compose v2 的 Linux 主机上使用生产 Compose 配置。启动前，编辑 `.env` 并显式设置：

- 至少 32 个字符的随机 `APP_SECRET`，以及强度足够的 `POSTGRES_PASSWORD`。
- `DATABASE_URL=postgresql://<用户>:<经过URL编码的密码>@postgres:5432/<数据库>`，其值应与 `POSTGRES_USER`、`POSTGRES_PASSWORD` 和 `POSTGRES_DB` 一致。默认用户名和数据库名均为 `agentforge`。必须替换从 `.env.example` 复制的 SQLite 地址；仅设置 `POSTGRES_PASSWORD` 不会同步更改 API 的连接地址。
- 与控制台公开访问地址匹配的 `WEB_ORIGIN`、可选的 `WEB_PORT`，以及模型配置。

```bash
cp .env.example .env
# 按上述要求编辑 .env，再启动服务。
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
```

API 以非 root 用户运行，根文件系统只读。PostgreSQL 16 和 Redis 7 使用持久卷。Agent 请求仍同步处理，Redis 为后续队列集成预留。

生产环境受保护的 `/api/*` 接口要求带 HS256 签名的 Bearer JWT。令牌必须包含 `sub` 和 `tenant_id`（或 `tid`）；身份系统应签发带有效期的令牌。验证时优先使用 `AUTH_JWT_SECRET`，未配置时使用 `APP_SECRET`。仓库中的 Compose 文件传入 `APP_SECRET`；如需独立认证密钥，必须将 `AUTH_JWT_SECRET` 补充到 API 容器环境配置中。

控制台目前没有内置的终端用户登录和令牌获取流程。对外开放前，需要完成身份认证与 API 请求携带令牌的集成；仅启动生产容器不代表这项集成已经完成。运行时设置共享同一配置空间，应由可信管理人员维护。部署操作可参考[使用说明书](docs/使用说明书.md)和[运维手册](docs/运维手册.md)。

`GET /api/health` 无需认证，返回 API 状态及当前模型配置或演示模式。它不能替代数据库、Redis 或模型连接的端到端检查。SQLite 适用于单实例；项目已实现 PostgreSQL 支持，但现有 SQLite 数据迁移、集中身份管理和多副本协调仍需在横向扩容前落实。

## 主要功能

- 异步、有轮数上限的 Agent 循环，支持 ReAct、Plan-Execute 提示模式和 Self-Critique 自我评审模式；可配置历史窗口、上下文限制，查看工具执行记录，并使用演示模型或 OpenAI 兼容模型。
- 持久化的模型和 Agent 设置、加密保存的 API Key、模型连接测试，以及工具启用状态、权限和超时策略。
- 工具注册表、JSON Schema 参数校验、敏感信息脱敏、审计记录，以及写操作的人为审批。
- 按租户隔离的本地会话、对话历史、运行详情、审批队列和指标接口。
- MCP HTTP 客户端，支持加密请求头、JSON-RPC 工具发现和调用、审计及 Agent 工具自动注册。支持解析 HTTP POST 返回的 JSON 或 SSE 事件流；尚未实现旧版 SSE GET 订阅、Streamable HTTP 会话 ID 或可恢复流。
- A2A 连接管理，支持加密 Bearer Token、Agent Card 发现、JSON-RPC 任务委派和查询，并自动注册委派工具。当前实现请求/响应子集，尚不支持推送通知或流式任务更新。
- 基于 SQLite 或 PostgreSQL 的记忆存储，支持租户/用户可见范围、过期、遗忘、增删改查，以及可配置的检索和自动采集策略。512 维确定性词项哈希向量用于本地词汇相似度检索，不是模型生成的语义向量，也不是外部向量数据库。
- Docker 代码沙箱，包含网络隔离、只读容器、能力移除、资源限制和 `code_sandbox` Agent 工具。输出在子进程捕获后截断，因此 `max_output_chars` 限制的是返回文本，不能作为运行期间输出占用内存的硬上限。

代码沙箱要求 API 进程所在环境具备 Docker CLI，并可访问 Docker daemon。仓库提供的 API 容器没有安装 Docker CLI，也没有挂载 Docker socket；直接启动标准 Compose 配置不会自动启用沙箱执行。使用前需要配置合适的执行环境。

## 控制台与 API 调用

1. 打开控制台，在设置中选择演示模型，或配置、测试并保存 OpenAI 兼容模型。
2. 在工作台创建会话，查看 Agent 回复、工具调用记录及运行历史。
3. 在审批队列检查写操作请求，明确批准或拒绝。
4. 在对应设置区域管理记忆、工具策略、MCP 服务和 A2A 连接。

本地开发环境的 PowerShell API 调用示例：

```powershell
Invoke-RestMethod -Uri 'http://localhost:8080/api/health'
$body = @{ message = 'Explain how tool approvals work.' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://localhost:8080/api/agents/runs' -ContentType 'application/json' -Body $body
```

从源码启动时，可通过 Vite 的 `5173` 端口访问，也可直接使用 API 的 `8000` 端口。生产 API 客户端还必须发送 `Authorization: Bearer <token>`。

| 接口 | 用途 |
| --- | --- |
| `POST /api/agents/runs` | 使用 `message` 和可选的 `session_id` 运行 Agent。 |
| `GET /api/agents/runs?limit=50&offset=0` | 分页读取已保存的运行记录。 |
| `GET /api/agents/runs/{run_id}` | 查看单次运行详情。 |
| `GET /api/agents/sessions` | 列出会话。 |
| `GET /api/agents/sessions/{session_id}` | 读取会话及其消息。 |
| `DELETE /api/agents/sessions/{session_id}` | 删除会话的消息和运行记录，并取消其待处理审批。 |
| `GET /api/approvals` | 列出待处理审批。 |
| `POST /api/approvals/{approval_id}/decision` | 提交 `{"decision":"approve"}` 或 `{"decision":"reject"}`。 |
| `GET /api/tools` | 查看已注册工具及其策略。 |
| `GET /api/metrics/summary` | 读取汇总运行指标。 |

## 运行时设置 API

`GET /api/settings` 返回已保存的模型、Agent、工具、沙箱、记忆、MCP 和 A2A 设置。响应不返回凭据值，只提供是否已配置等状态。

`PUT /api/settings/model` 接受 `provider`（`demo` 或 `openai-compatible`）、`base_url`、`model`、`api_key`、`timeout_seconds`、`temperature` 和 `max_tokens`。未提供的字段保留现值；省略或传入空的 `api_key` 会保留已保存的 Key。使用 `clear_api_key: true` 可清除 Key，仅允许在切换到演示模式时使用。OpenAI 兼容端点必须使用有效的 HTTP(S) 地址并配置 Key。DeepSeek、豆包、DashScope 等兼容服务可通过相应的兼容地址、模型名和 API Key 接入。

`POST /api/settings/model/test` 接受相同的模型字段，仅测试连接而不保存。空白或省略的 `api_key` 会使用已保存的 Key。响应返回成功状态或脱敏后的失败原因；如已加密凭据不可读取，会返回可恢复的错误提示。

`PUT /api/settings/agent` 接受 `name`、`system_prompt`、`mode`（`react`、`plan_execute` 或 `self_critique`）、`max_tool_rounds`（1–20）、`history_window`（1–100）和 `context_window_tokens`（512–128000）。配置对新的运行立即生效，Agent 名称会显示在工作台中。

`PATCH /api/settings/tools/{name}` 接受 `enabled`、`permission`（`read` 或 `write`）和 `timeout_seconds`。控制台将 `write` 工具标为需要审批；内置写工具保留写权限并要求审批。被禁用的工具不会进入模型可见的工具 Schema，执行时也会被拒绝。

`GET/PUT /api/sandbox/settings` 配置 Docker 镜像、超时、内存、CPU、PID 和输出限制；`POST /api/sandbox/run` 在这些限制下执行代码。API 进程必须满足前文的 Docker 沙箱运行条件。

`GET/PUT /api/memory/settings` 控制记忆启用、检索、自动采集、相似度阈值和返回数量。`/api/memory` 及其别名 `/api/memory/items` 支持列表与新增，`/api/memory/search` 执行相似度检索。资源 ID 可用于读取、更新和删除，`POST /api/memory/forget` 用于遗忘。记忆受租户及可选用户归属范围限制；每次新运行中的检索和自动采集均遵循这些设置。

`GET /api/mcp/servers` 列出 MCP 连接；`PUT/DELETE /api/mcp/servers/{name}` 管理端点、传输方式、超时、启用状态和加密请求头。省略 `headers` 保留已保存凭据，`clear_headers: true` 清除请求头。控制台支持新增、编辑、删除和重新发现连接。`POST /api/mcp/servers/{name}/discover` 保存工具 Schema 并供 Agent 使用。`POST /api/mcp/servers/{name}/tools/{tool_name}/call` 支持直接调用，并遵循已配置的审批策略。

`GET/POST /api/a2a/agents` 列出或创建 A2A 连接；`PUT/DELETE /api/a2a/agents/{id}` 更新或删除连接。配置包含超时、启用状态和加密 Bearer Token。更新时省略 `bearer_token` 保留已有 Token，`clear_bearer_token: true` 清除它。控制台支持新增、编辑、删除和重新发现连接。`POST /api/a2a/agents/{id}/discover` 保存 Agent Card；`POST /api/a2a/agents/{id}/tasks` 委派任务；`GET /api/a2a/agents/{id}/tasks/{task_id}` 查询任务。启用的连接也会注册为 Agent 工具。

MCP 和 A2A 工具与内置工具共用 `/api/settings/tools/{name}` 的启用、权限和超时设置。新发现的远程工具默认标为 `read`，自动使用前应先审查并设置正确权限。标为 `write` 的远程工具会进入审批队列，批准后才执行远程调用。并发重复审批不能重复启动同一次调用，决策和执行均记录审计。

## 工程目录

| 路径 | 内容 |
| --- | --- |
| `api/app/main.py` | FastAPI 入口，以及运行时设置、运行记录、会话、审批和指标接口。 |
| `api/app/agent.py`、`provider.py`、`runtime.py` | Agent 循环、模型集成和执行上下文。 |
| `api/app/tools.py`、`sandbox.py` | 工具注册、审批和 Docker 代码执行。 |
| `api/app/database.py`、`vector_memory.py` | SQLite/PostgreSQL 存储和本地相似度记忆。 |
| `api/app/auth.py`、`settings.py`、`security.py` | 请求身份、持久化设置、加密和脱敏。 |
| `api/app/mcp.py`、`a2a_runtime.py` | MCP 和 A2A 远程集成。 |
| `api/tests/`、`api/requirements.txt`、`api/Dockerfile` | 后端测试、依赖和镜像构建。 |
| `web/src/main.tsx`、`web/src/styles.css` | React 控制台及响应式样式。 |
| `web/package.json`、`web/vite.config.ts` | 前端命令、依赖及开发代理。 |
| `web/Dockerfile`、`web/nginx.conf` | 前端镜像和 API 反向代理。 |
| `docker-compose.yml` | 带持久化 SQLite 数据的本地 API/Web 部署。 |
| `docker-compose.production.yml` | 包含 PostgreSQL 和 Redis 的加固部署。 |
| `.env.example` | 不含真实凭据的配置模板。 |
| `docs/` | 架构、用户文档和运维流程。 |

## 验证方式

安装依赖后，在 `api/` 中运行后端测试：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest
```

POSIX Shell 对应命令为 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest`。在 `web/` 中构建前端：

```shell
npm run build
```

这些检查验证代码行为和前端构建，不能证明真实模型、远程 MCP/A2A、Docker 沙箱或生产认证连接可用。相关集成需要在目标环境中分别验证。
