import { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Code2,
  Command,
  Database,
  FileClock,
  Filter,
  Gauge,
  GitBranch,
  Layers3,
  LockKeyhole,
  Menu,
  MessageSquareText,
  MoreHorizontal,
  Plus,
  Radio,
  Search,
  Send,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
  Server,
  Workflow,
  Box,
  Trash2,
} from "lucide-react";
import "./styles.css";

type Trace = {
  id?: string;
  kind?: string;
  title?: string;
  detail?: string;
  status?: string;
  duration_ms?: number;
  created_at?: string;
};
type ChatMessage = {
  role: "user" | "assistant" | "tool";
  content: string;
  traces?: Trace[];
  created_at?: string;
};
type Session = {
  id: string;
  title?: string;
  status?: string;
  updated_at?: string;
};
type Tool = {
  name: string;
  description?: string;
  parameters?: Record<string, unknown>;
  permission?: string;
  enabled?: boolean;
  timeout_seconds?: number;
};
type Approval = {
  id: string;
  tool_name?: string;
  action?: string;
  reason?: string;
  status?: string;
  arguments?: Record<string, unknown>;
  created_at?: string;
  reviewed_at?: string;
};
type Run = {
  id: string;
  session_id?: string;
  conversation_id?: string;
  status?: string;
  response?: string;
  steps?: Trace[];
  created_at?: string;
};
type Metrics = {
  runs?: number;
  tool_runs?: number;
  successful_runs?: number;
  pending_approvals?: number;
  success_rate?: number;
  tool_failures?: number;
  avg_latency_ms?: number;
};
type ModelSettings = {
  provider: "demo" | "openai-compatible" | string;
  base_url: string;
  model: string;
  api_key_configured: boolean;
  api_key_masked?: string;
  timeout_seconds: number;
  temperature: number;
  max_tokens: number;
};
type AgentSettings = {
  name: string;
  system_prompt: string;
  mode: "react" | "plan_execute" | "self_critique" | string;
  max_tool_rounds: number;
  history_window: number;
  context_window_tokens: number;
};
type SandboxSettings = {
  enabled: boolean;
  runtime: string;
  image: string;
  timeout_seconds: number;
  memory_mb: number;
  cpu_limit: number;
  pids_limit: number;
  max_output_chars: number;
  runtime_available?: boolean;
};
type MCPServer = {
  name: string;
  endpoint: string;
  transport: string;
  enabled: boolean;
  timeout_seconds: number;
  headers_configured: boolean;
  tools?: Array<{ name: string }>;
  last_error?: string | null;
};
type A2AAgent = {
  id: string;
  name: string;
  url: string;
  timeout_seconds: number;
  bearer_token_configured: boolean;
  enabled?: boolean;
  agent_card?: Record<string, unknown> | null;
};
type Memory = {
  id: string;
  memory_type: string;
  content: string;
  visibility: string;
  owner_id?: string | null;
  source?: string;
  similarity?: number;
  expires_at?: string | null;
  created_at?: string;
};
type MemorySettings = {
  enabled: boolean;
  retrieval_enabled: boolean;
  auto_capture: boolean;
  threshold: number;
  limit: number;
};
type Settings = {
  model: ModelSettings;
  agent: AgentSettings;
  tools: Tool[];
  sandbox?: SandboxSettings;
  memory?: MemorySettings;
  mcp?: { servers: MCPServer[] };
  a2a?: { agents: A2AAgent[] };
};

const API = import.meta.env.VITE_API_URL || "/api";
const welcomeMessage: ChatMessage = {
  role: "assistant",
  content:
    "你好，我是支持运营 Agent。请描述需要处理的任务，我会按当前工作区配置执行，并在需要时提交人工审批。",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = "";
    try {
      detail = (await response.json()).detail || "";
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function unwrap<T>(value: { data?: T[]; items?: T[] } | T[]): T[] {
  return Array.isArray(value) ? value : value.data || value.items || [];
}

function App() {
  const [section, setSection] = useState("工作台");
  const [drawer, setDrawer] = useState(false);
  const [query, setQuery] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState("");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMessage]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [metrics, setMetrics] = useState<Metrics>({});
  const [settings, setSettings] = useState<Settings | null>(null);
  const [activeTrace, setActiveTrace] = useState<Trace[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);

  async function loadData() {
    setError("");
    const results = await Promise.allSettled([
      api<{ items?: Session[] }>("/agents/sessions"),
      api<{ items?: Tool[] }>("/tools"),
      api<{ items?: Approval[] }>("/approvals"),
      api<Metrics>("/metrics/summary"),
      api<{ items?: Run[] }>("/agents/runs?limit=50"),
      api<Settings>("/settings"),
    ]);
    const [
      sessionResult,
      toolResult,
      approvalResult,
      metricResult,
      runResult,
      settingsResult,
    ] = results;
    if (sessionResult.status === "fulfilled")
      setSessions(unwrap(sessionResult.value));
    if (toolResult.status === "fulfilled") setTools(unwrap(toolResult.value));
    if (approvalResult.status === "fulfilled")
      setApprovals(unwrap(approvalResult.value));
    if (metricResult.status === "fulfilled") setMetrics(metricResult.value);
    if (runResult.status === "fulfilled") setRuns(unwrap(runResult.value));
    if (settingsResult.status === "fulfilled")
      setSettings(settingsResult.value);
    setOnline(results.some((result) => result.status === "fulfilled"));
    const failed = results.find((result) => result.status === "rejected");
    if (failed && failed.status === "rejected")
      setError(
        failed.reason instanceof Error
          ? failed.reason.message
          : "部分服务接口不可用",
      );
  }

  useEffect(() => {
    void loadData();
  }, []);

  const visibleSessions = useMemo(
    () =>
      sessions.filter((session) =>
        (session.title || "新建对话")
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [sessions, query],
  );

  async function openSession(sessionId: string) {
    setError("");
    try {
      const session = await api<{ messages?: ChatMessage[] }>(
        `/agents/sessions/${sessionId}`,
      );
      setActiveSession(sessionId);
      setMessages(
        session.messages?.length
          ? session.messages.filter((message) => message.role !== "tool")
          : [welcomeMessage],
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法打开会话");
    }
  }

  function newRun() {
    setActiveSession(null);
    setMessages([welcomeMessage]);
    setActiveTrace([]);
    setSection("工作台");
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const content = input.trim();
    if (!content || busy) return;
    setError("");
    setMessages((current) => [...current, { role: "user", content }]);
    setInput("");
    setBusy(true);
    setActiveTrace([
      {
        id: `pending-${Date.now()}`,
        kind: "plan",
        title: "运行中",
        detail: "Agent 正在分析请求并选择工具。",
        status: "running",
      },
    ]);
    try {
      const result = await api<{
        response?: string;
        answer?: string;
        output?: string;
        content?: string;
        steps?: Trace[];
        traces?: Trace[];
        session_id?: string;
      }>("/agents/runs", {
        method: "POST",
        body: JSON.stringify({
          message: content,
          ...(activeSession ? { session_id: activeSession } : {}),
        }),
      });
      const trace = result.traces || result.steps || [];
      setActiveTrace(trace);
      if (result.session_id) {
        setActiveSession(result.session_id);
        void loadData();
      }
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content:
            result.response ||
            result.answer ||
            result.output ||
            result.content ||
            "运行完成。",
          traces: trace,
        },
      ]);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "运行失败";
      setError(message);
      setActiveTrace([]);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: `运行失败：${message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function decideApproval(id: string, decision: "approve" | "reject") {
    try {
      await api(`/approvals/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批操作失败");
    }
  }

  const navItems = [
    {
      group: "工作区",
      rows: [
        { name: "工作台", icon: MessageSquareText },
        { name: "运行记录", icon: FileClock },
        { name: "工具中心", icon: Wrench },
      ],
    },
    {
      group: "治理",
      rows: [
        { name: "审批队列", icon: ShieldAlert, count: approvals.length },
        { name: "记忆库", icon: Database },
        { name: "评估指标", icon: Gauge },
        { name: "设置", icon: Settings2 },
      ],
    },
  ];

  return (
    <div className="app-shell">
      <aside className={`sidebar ${drawer ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <Layers3 size={17} />
          </div>
          <span>FIELDNOTES</span>
          <small>AGENT STUDIO</small>
          <button
            className="icon-button sidebar-close"
            aria-label="关闭导航"
            onClick={() => setDrawer(false)}
          >
            <X size={16} />
          </button>
        </div>
        <button className="workspace-switch">
          <div className="workspace-avatar">N</div>
          <span>
            <strong>Northstar Support</strong>
            <small>当前租户</small>
          </span>
          <ChevronDown size={15} />
        </button>
        <button className="new-run" onClick={newRun}>
          <Plus size={16} /> 新建运行
        </button>
        {navItems.map((group) => (
          <div className="nav-group" key={group.group}>
            <div className="nav-label">{group.group}</div>
            {group.rows.map((item) => (
              <button
                key={item.name}
                onClick={() => {
                  setSection(item.name);
                  setDrawer(false);
                }}
                className={`nav-item ${section === item.name ? "selected" : ""}`}
              >
                <item.icon size={16} />
                <span>{item.name}</span>
                {item.count ? <b className="nav-count">{item.count}</b> : null}
              </button>
            ))}
          </div>
        ))}
        <div className="sessions-heading">
          <span>最近对话</span>
          <button
            className="icon-button"
            aria-label="刷新会话"
            onClick={() => void loadData()}
          >
            <Activity size={14} />
          </button>
        </div>
        <label className="session-search">
          <Search size={14} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索对话"
          />
        </label>
        <div className="session-list">
          {visibleSessions.map((session) => (
            <button
              className={`session-link ${activeSession === session.id ? "active" : ""}`}
              key={session.id}
              onClick={() => void openSession(session.id)}
            >
              <span className="session-dot" />
              {session.title || "新建对话"}
            </button>
          ))}
          {!visibleSessions.length && (
            <div className="empty-sidebar">暂无会话</div>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="profile-avatar">LC</div>
          <span>
            <strong>当前用户</strong>
            <small>工作区管理员</small>
          </span>
          <MoreHorizontal size={17} />
        </div>
      </aside>
      {drawer && (
        <button
          className="scrim"
          aria-label="关闭导航"
          onClick={() => setDrawer(false)}
        />
      )}
      <main className="main-area">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="打开导航"
            onClick={() => setDrawer(true)}
          >
            <Menu size={19} />
          </button>
          <div className="breadcrumbs">
            <span>工作区</span>
            <ArrowRight size={13} />
            <strong>{section}</strong>
          </div>
          <div className="top-actions">
            <span className={`connection ${online ? "connected" : ""}`}>
              <span />
              {online ? "API 已连接" : "API 离线"}
            </span>
            <button className="icon-button" title="帮助与文档">
              <CircleHelp size={17} />
            </button>
            <button
              className="icon-button"
              title="设置"
              onClick={() => setSection("设置")}
            >
              <Settings2 size={17} />
            </button>
          </div>
        </header>
        {error && (
          <div className="error-banner">
            <ShieldAlert size={15} /> <span>{error}</span>
            <button
              className="icon-button"
              onClick={() => setError("")}
              aria-label="关闭错误"
            >
              <X size={14} />
            </button>
          </div>
        )}
        {section === "工作台" ? (
          <Workspace
            agentName={settings?.agent.name || "支持运营助手"}
            messages={messages}
            input={input}
            setInput={setInput}
            busy={busy}
            activeSession={activeSession}
            activeTrace={activeTrace}
            tools={tools}
            approvals={approvals}
            onSubmit={sendMessage}
            onNavigate={setSection}
          />
        ) : section === "设置" ? (
          <SettingsView settings={settings} tools={tools} onSaved={loadData} />
        ) : (
          <OperationalView
            section={section}
            tools={tools}
            approvals={approvals}
            runs={runs}
            metrics={metrics}
            onDecision={decideApproval}
            onNavigate={setSection}
          />
        )}
      </main>
    </div>
  );
}

function Workspace({
  agentName,
  messages,
  input,
  setInput,
  busy,
  activeSession,
  activeTrace,
  tools,
  approvals,
  onSubmit,
  onNavigate,
}: {
  agentName: string;
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  activeSession: string | null;
  activeTrace: Trace[];
  tools: Tool[];
  approvals: Approval[];
  onSubmit: (event: FormEvent) => void;
  onNavigate: (section: string) => void;
}) {
  return (
    <div className="workspace">
      <section className="conversation-panel">
        <div className="conversation-head">
          <div>
            <div className="eyebrow">
              <span className="live-pulse" />
              AGENT RUN · {activeSession?.slice(0, 12) || "新会话"}
            </div>
            <h1>{agentName}</h1>
          </div>
          <div className="head-controls">
            <button className="select-control">
              <Bot size={15} /> {agentName} <ChevronDown size={13} />
            </button>
          </div>
        </div>
        <div className="run-mode">
          <span>运行模式</span>
          <span className="mode-active">
            {activeTrace.length ? "运行中" : "就绪"}
          </span>
          <span className="mode-separator" />
          <span className="model-label">
            <Radio size={13} /> 当前配置由设置面板管理
          </span>
        </div>
        <div className="chat-scroll">
          <div className="date-divider">
            <span>当前会话</span>
          </div>
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`message-row ${message.role}`}
            >
              <div className={`message-avatar ${message.role}`}>
                {message.role === "assistant" ? (
                  <Sparkles size={15} />
                ) : message.role === "tool" ? (
                  <Wrench size={14} />
                ) : (
                  "你"
                )}
              </div>
              <div className="message-body">
                <div className="message-meta">
                  <strong>
                    {message.role === "assistant"
                      ? agentName
                      : message.role === "tool"
                        ? "Tool"
                        : "你"}
                  </strong>
                  <span>{message.created_at || ""}</span>
                  {message.role === "assistant" && (
                    <span className="safe-tag">
                      <ShieldCheck size={12} /> 已经过安全策略
                    </span>
                  )}
                </div>
                <div className="message-content">{message.content}</div>
                {message.traces && (
                  <div className="inline-run">
                    <span>
                      <Check size={13} /> {message.traces.length} 个步骤
                    </span>
                    <button onClick={() => onNavigate("运行记录")}>
                      查看运行 <ArrowRight size={12} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div className="thinking">
              <span />
              <span />
              <span /> Agent 正在执行
            </div>
          )}
        </div>
        <form className="composer" onSubmit={onSubmit}>
          <div className="composer-tools">
            <button type="button" title="添加上下文">
              <Plus size={16} />
            </button>
            <span>
              <LockKeyhole size={13} /> 隔离上下文
            </span>
            <button type="button" className="context-button">
              <Code2 size={14} /> 上下文 <ChevronDown size={12} />
            </button>
            <button type="button" className="context-button">
              <Command size={14} /> 工具权限 <ChevronDown size={12} />
            </button>
          </div>
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSubmit(event as unknown as FormEvent);
              }
            }}
            placeholder="描述任务，或输入 / 调用工具…"
            rows={2}
          />
          <div className="composer-footer">
            <span>Enter 发送 · Shift + Enter 换行</span>
            <button
              className="send-button"
              type="submit"
              disabled={!input.trim() || busy}
              aria-label="发送消息"
            >
              <Send size={15} />
            </button>
          </div>
        </form>
      </section>
      <aside className="inspector-panel">
        <div className="inspector-tabs">
          <button className="tab-active">运行详情</button>
          <button onClick={() => onNavigate("工具中心")}>
            工具 <span>{tools.length}</span>
          </button>
          <button onClick={() => onNavigate("审批队列")}>
            审批 {approvals.length > 0 && <b>{approvals.length}</b>}
          </button>
        </div>
        <div className="inspector-content">
          {activeTrace.length ? (
            <>
              <div className="run-summary">
                <div>
                  <span className="summary-label">当前运行</span>
                  <strong>最新任务</strong>
                </div>
                <span className="status-pill success">
                  <span /> 已返回
                </span>
              </div>
              <div className="trace-title">
                <h2>执行轨迹</h2>
                <Filter size={15} />
              </div>
              <div className="trace-list">
                {activeTrace.map((trace, index) => (
                  <div className="trace-item" key={trace.id || index}>
                    <div className={`trace-icon ${trace.kind || "plan"}`}>
                      <GitBranch size={14} />
                    </div>
                    <div className="trace-info">
                      <div className="trace-name">
                        {trace.title || trace.kind || "步骤"}
                        <span className={`trace-state ${trace.status || ""}`}>
                          {trace.status || "完成"}
                        </span>
                      </div>
                      <p>{trace.detail || ""}</p>
                      <div className="trace-meta">
                        <span>{(trace.kind || "step").toUpperCase()}</span>
                        {trace.duration_ms ? (
                          <span>
                            <Clock3 size={11} /> {trace.duration_ms} ms
                          </span>
                        ) : null}
                      </div>
                    </div>
                    {index < activeTrace.length - 1 && (
                      <div className="trace-connector" />
                    )}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state">
              <Activity size={20} />
              <strong>暂无运行</strong>
              <span>发送一条任务后，这里会显示真实执行轨迹。</span>
            </div>
          )}
          <div className="guardrail-note">
            <div>
              <ShieldCheck size={15} />
              <strong>安全策略状态</strong>
            </div>
            <p>策略与模型参数在设置页面统一管理。</p>
            <button onClick={() => onNavigate("设置")}>
              打开设置 <ArrowRight size={12} />
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}

function SettingsView({
  settings,
  tools,
  onSaved,
}: {
  settings: Settings | null;
  tools: Tool[];
  onSaved: () => Promise<void>;
}) {
  const [model, setModel] = useState<ModelSettings>({
    provider: "demo",
    base_url: "",
    model: "",
    api_key_configured: false,
    timeout_seconds: 25,
    temperature: 0.2,
    max_tokens: 2048,
  });
  const [agent, setAgent] = useState<AgentSettings>({
    name: "",
    system_prompt: "",
    mode: "react",
    max_tool_rounds: 5,
    history_window: 20,
    context_window_tokens: 12000,
  });
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [sandbox, setSandbox] = useState<SandboxSettings>({
    enabled: true,
    runtime: "docker",
    image: "python:3.12-alpine",
    timeout_seconds: 10,
    memory_mb: 256,
    cpu_limit: 0.5,
    pids_limit: 64,
    max_output_chars: 12000,
  });
  const [memory, setMemory] = useState<MemorySettings>({
    enabled: true,
    retrieval_enabled: true,
    auto_capture: false,
    threshold: 0.15,
    limit: 5,
  });
  const [mcpName, setMcpName] = useState("");
  const [mcpEndpoint, setMcpEndpoint] = useState("");
  const [mcpTransport, setMcpTransport] = useState("streamable_http");
  const [mcpTimeout, setMcpTimeout] = useState(20);
  const [mcpAuthorization, setMcpAuthorization] = useState("");
  const [mcpEnabled, setMcpEnabled] = useState(true);
  const [clearMcpAuthorization, setClearMcpAuthorization] = useState(false);
  const [editingMcp, setEditingMcp] = useState<string | null>(null);
  const [a2aName, setA2aName] = useState("");
  const [a2aUrl, setA2aUrl] = useState("");
  const [a2aToken, setA2aToken] = useState("");
  const [a2aTimeout, setA2aTimeout] = useState(20);
  const [a2aEnabled, setA2aEnabled] = useState(true);
  const [clearA2aToken, setClearA2aToken] = useState(false);
  const [editingA2a, setEditingA2a] = useState<string | null>(null);
  useEffect(() => {
    if (settings) {
      setModel(settings.model);
      setAgent(settings.agent);
      if (settings.sandbox) setSandbox(settings.sandbox);
      if (settings.memory) setMemory(settings.memory);
    }
  }, [settings]);

  function modelPayload(includeClear = true) {
    return {
      provider: model.provider,
      base_url: model.base_url,
      model: model.model,
      timeout_seconds: model.timeout_seconds,
      temperature: model.temperature,
      max_tokens: model.max_tokens,
      ...(apiKey ? { api_key: apiKey } : {}),
      ...(includeClear && clearKey ? { clear_api_key: true } : {}),
    };
  }
  async function saveModel(event: FormEvent) {
    event.preventDefault();
    setSaving("model");
    setNotice("");
    try {
      const result = await api<{ model: ModelSettings } | ModelSettings>(
        "/settings/model",
        { method: "PUT", body: JSON.stringify(modelPayload()) },
      );
      const saved =
        typeof result.model === "object" && result.model !== null
          ? result.model
          : (result as ModelSettings);
      setModel(saved);
      setApiKey("");
      setClearKey(false);
      setNotice("模型配置已保存，并已应用到新的运行");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving("");
    }
  }
  async function testModel() {
    setSaving("test");
    setNotice("");
    try {
      const result = await api<{ status?: string; message?: string }>(
        "/settings/model/test",
        { method: "POST", body: JSON.stringify(modelPayload(false)) },
      );
      setNotice(result.message || "模型连接测试通过");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "连接测试失败");
    } finally {
      setSaving("");
    }
  }
  async function saveAgent(event: FormEvent) {
    event.preventDefault();
    setSaving("agent");
    setNotice("");
    try {
      const result = await api<{ agent: AgentSettings } | AgentSettings>(
        "/settings/agent",
        { method: "PUT", body: JSON.stringify(agent) },
      );
      const saved = "agent" in result ? result.agent : result;
      setAgent(saved);
      setNotice("Agent 策略已保存");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving("");
    }
  }
  async function updateTool(tool: Tool, patch: Partial<Tool>) {
    try {
      const result = await api<{ tool: Tool } | Tool>(
        `/settings/tools/${encodeURIComponent(tool.name)}`,
        { method: "PATCH", body: JSON.stringify(patch) },
      );
      const saved = "tool" in result ? result.tool : result;
      setNotice(`${saved.name} 配置已保存`);
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "工具配置保存失败");
    }
  }
  async function saveSandbox(event: FormEvent) {
    event.preventDefault();
    setSaving("sandbox");
    try {
      await api("/sandbox/settings", {
        method: "PUT",
        body: JSON.stringify(sandbox),
      });
      setNotice("代码沙箱策略已保存");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "沙箱配置保存失败");
    } finally {
      setSaving("");
    }
  }
  async function saveMemory(event: FormEvent) {
    event.preventDefault();
    setSaving("memory");
    try {
      await api("/memory/settings", {
        method: "PUT",
        body: JSON.stringify(memory),
      });
      setNotice("向量记忆策略已保存");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "记忆配置保存失败");
    } finally {
      setSaving("");
    }
  }
  async function saveMcp(event: FormEvent) {
    event.preventDefault();
    if (!mcpName || !mcpEndpoint) return;
    setSaving("mcp");
    setNotice("");
    try {
      const headers = mcpAuthorization.trim()
        ? {
            Authorization: mcpAuthorization.trim().startsWith("Bearer ")
              ? mcpAuthorization.trim()
              : `Bearer ${mcpAuthorization.trim()}`,
          }
        : {};
      await api(`/mcp/servers/${encodeURIComponent(mcpName)}`, {
        method: "PUT",
        body: JSON.stringify({
          endpoint: mcpEndpoint,
          transport: mcpTransport,
          timeout_seconds: mcpTimeout,
          headers,
          clear_headers: clearMcpAuthorization,
          enabled: mcpEnabled,
        }),
      });
      await api(`/mcp/servers/${encodeURIComponent(mcpName)}/discover`, {
        method: "POST",
      });
      setMcpName("");
      setMcpEndpoint("");
      setMcpAuthorization("");
      setMcpEnabled(true);
      setClearMcpAuthorization(false);
      setEditingMcp(null);
      setNotice("MCP 服务已保存并完成工具发现");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "MCP 配置失败");
    } finally {
      setSaving("");
    }
  }
  async function editMcp(server: MCPServer) {
    setEditingMcp(server.name);
    setMcpName(server.name);
    setMcpEndpoint(server.endpoint);
    setMcpTransport(server.transport);
    setMcpTimeout(server.timeout_seconds);
    setMcpAuthorization("");
    setMcpEnabled(server.enabled);
    setClearMcpAuthorization(false);
  }
  async function deleteMcp(name: string) {
    try {
      await api(`/mcp/servers/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (editingMcp === name) {
        setEditingMcp(null);
        setMcpName("");
        setMcpEndpoint("");
        setMcpAuthorization("");
      }
      setNotice(`MCP 服务 ${name} 已删除`);
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "MCP 删除失败");
    }
  }

  async function discoverMcp(name: string) {
    setSaving(`mcp:${name}`);
    setNotice("");
    try {
      const result = await api<{ tools?: Array<{ name: string }> }>(
        `/mcp/servers/${encodeURIComponent(name)}/discover`,
        { method: "POST" },
      );
      setNotice(`MCP 服务发现完成，共 ${result.tools?.length || 0} 个工具`);
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "MCP 工具发现失败");
    } finally {
      setSaving("");
    }
  }
  async function saveA2a(event: FormEvent) {
    event.preventDefault();
    if (!a2aName || !a2aUrl) return;
    setSaving("a2a");
    setNotice("");
    try {
      const payload = {
        name: a2aName,
        url: a2aUrl,
        timeout_seconds: a2aTimeout,
        enabled: a2aEnabled,
        clear_bearer_token: clearA2aToken,
        ...(a2aToken.trim() ? { bearer_token: a2aToken.trim() } : {}),
      };
      const result = editingA2a
        ? await api<{ agent: A2AAgent }>(`/a2a/agents/${editingA2a}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          })
        : await api<{ agent: A2AAgent }>("/a2a/agents", {
            method: "POST",
            body: JSON.stringify(payload),
          });
      await api(`/a2a/agents/${result.agent.id}/discover`, { method: "POST" });
      setA2aName("");
      setA2aUrl("");
      setA2aToken("");
      setA2aEnabled(true);
      setClearA2aToken(false);
      setEditingA2a(null);
      setNotice("A2A Agent 已保存并完成 Agent Card 发现");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "A2A 配置失败");
    } finally {
      setSaving("");
    }
  }
  function editA2a(agentItem: A2AAgent) {
    setEditingA2a(agentItem.id);
    setA2aName(agentItem.name);
    setA2aUrl(agentItem.url);
    setA2aTimeout(agentItem.timeout_seconds);
    setA2aToken("");
    setA2aEnabled(agentItem.enabled !== false);
    setClearA2aToken(false);
  }
  async function deleteA2a(id: string) {
    try {
      await api(`/a2a/agents/${id}`, { method: "DELETE" });
      if (editingA2a === id) {
        setEditingA2a(null);
        setA2aName("");
        setA2aUrl("");
        setA2aToken("");
      }
      setNotice("A2A Agent 已删除");
      await onSaved();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "A2A 删除失败");
    }
  }

  async function discoverA2a(agentItem: A2AAgent) {
    setSaving(`a2a:${agentItem.id}`);
    setNotice("");
    try {
      await api(`/a2a/agents/${agentItem.id}/discover`, { method: "POST" });
      setNotice(`A2A Agent ${agentItem.name} 的 Agent Card 已更新`);
      await onSaved();
    } catch (reason) {
      setNotice(
        reason instanceof Error ? reason.message : "A2A Agent Card 发现失败",
      );
    } finally {
      setSaving("");
    }
  }

  return (
    <section className="ops-page settings-page">
      <div className="ops-heading">
        <div>
          <div className="eyebrow">RUNTIME CONFIGURATION</div>
          <h1>设置</h1>
          <p>
            配置模型、Agent、协议连接、记忆和沙箱，保存后立即作用于新的运行。
          </p>
        </div>
      </div>
      {notice && (
        <div className="settings-notice">
          <ShieldCheck size={15} /> {notice}
        </div>
      )}
      {!settings && (
        <div className="empty-state settings-empty">
          <Settings2 size={22} />
          <strong>配置接口不可用</strong>
          <span>请先启动 API 服务，设置项加载后才可编辑。</span>
        </div>
      )}
      {settings && (
        <div className="settings-layout">
          <form className="settings-card" onSubmit={saveModel}>
            <div className="settings-card-head">
              <div>
                <h2>模型连接</h2>
                <p>选择演示模式或 OpenAI-compatible 接口。</p>
              </div>
              <span
                className={
                  model.api_key_configured
                    ? "config-status ok"
                    : "config-status"
                }
              >
                {model.api_key_configured ? "密钥已配置" : "未配置密钥"}
              </span>
            </div>
            <div className="form-grid">
              <label>
                提供商
                <select
                  value={model.provider}
                  onChange={(event) =>
                    setModel({ ...model, provider: event.target.value })
                  }
                >
                  <option value="demo">demo 演示模式</option>
                  <option value="openai-compatible">OpenAI-compatible</option>
                </select>
              </label>
              <label>
                模型名称
                <input
                  value={model.model}
                  onChange={(event) =>
                    setModel({ ...model, model: event.target.value })
                  }
                  placeholder="gpt-4o-mini"
                />
              </label>
              <label className="form-span-2">
                Base URL
                <input
                  value={model.base_url}
                  onChange={(event) =>
                    setModel({ ...model, base_url: event.target.value })
                  }
                  placeholder="https://api.example.com/v1"
                />
              </label>
              <label className="secret-field">
                API Key
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={
                    model.api_key_configured ? "留空保持已保存密钥" : "输入密钥"
                  }
                />
              </label>
              <label>
                超时（秒）
                <input
                  type="number"
                  min="1"
                  max="300"
                  value={model.timeout_seconds}
                  onChange={(event) =>
                    setModel({
                      ...model,
                      timeout_seconds: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                Temperature
                <input
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={model.temperature}
                  onChange={(event) =>
                    setModel({
                      ...model,
                      temperature: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                最大 Token
                <input
                  type="number"
                  min="1"
                  max="131072"
                  value={model.max_tokens}
                  onChange={(event) =>
                    setModel({
                      ...model,
                      max_tokens: Number(event.target.value),
                    })
                  }
                />
              </label>
            </div>
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={clearKey}
                onChange={(event) => setClearKey(event.target.checked)}
              />{" "}
              清除已保存的 API Key
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="secondary-action"
                onClick={() => void testModel()}
                disabled={saving !== ""}
              >
                <Radio size={14} /> 测试连接
              </button>
              <button className="primary-action" disabled={saving !== ""}>
                <Check size={14} /> 保存模型配置
              </button>
            </div>
          </form>
          <form className="settings-card" onSubmit={saveAgent}>
            <div className="settings-card-head">
              <div>
                <h2>Agent 运行策略</h2>
                <p>控制循环方式、工具调用上限和上下文窗口。</p>
              </div>
            </div>
            <div className="form-grid">
              <label>
                Agent 名称
                <input
                  value={agent.name}
                  onChange={(event) =>
                    setAgent({ ...agent, name: event.target.value })
                  }
                />
              </label>
              <label>
                循环模式
                <select
                  value={agent.mode}
                  onChange={(event) =>
                    setAgent({ ...agent, mode: event.target.value })
                  }
                >
                  <option value="react">ReAct</option>
                  <option value="plan_execute">Plan → Execute</option>
                  <option value="self_critique">Self-Critique</option>
                </select>
              </label>
              <label>
                最大工具轮次
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={agent.max_tool_rounds}
                  onChange={(event) =>
                    setAgent({
                      ...agent,
                      max_tool_rounds: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                历史消息窗口
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={agent.history_window}
                  onChange={(event) =>
                    setAgent({
                      ...agent,
                      history_window: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                上下文窗口（Token）
                <input
                  type="number"
                  min="512"
                  max="128000"
                  value={agent.context_window_tokens}
                  onChange={(event) =>
                    setAgent({
                      ...agent,
                      context_window_tokens: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label className="form-span-2">
                系统提示词
                <textarea
                  className="prompt-input"
                  value={agent.system_prompt}
                  onChange={(event) =>
                    setAgent({ ...agent, system_prompt: event.target.value })
                  }
                  rows={8}
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="primary-action" disabled={saving !== ""}>
                <Check size={14} /> 保存 Agent 策略
              </button>
            </div>
          </form>
          <form className="settings-card" onSubmit={saveMemory}>
            <div className="settings-card-head">
              <div>
                <h2>向量记忆</h2>
                <p>控制召回阈值、召回数量和自动捕获。</p>
              </div>
            </div>
            <div className="form-grid">
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={memory.enabled}
                  onChange={(event) =>
                    setMemory({ ...memory, enabled: event.target.checked })
                  }
                />{" "}
                启用记忆服务
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={memory.retrieval_enabled}
                  onChange={(event) =>
                    setMemory({
                      ...memory,
                      retrieval_enabled: event.target.checked,
                    })
                  }
                />{" "}
                运行前召回
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={memory.auto_capture}
                  onChange={(event) =>
                    setMemory({ ...memory, auto_capture: event.target.checked })
                  }
                />{" "}
                运行后自动写入
              </label>
              <label>
                相似度阈值
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={memory.threshold}
                  onChange={(event) =>
                    setMemory({
                      ...memory,
                      threshold: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                召回数量
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={memory.limit}
                  onChange={(event) =>
                    setMemory({ ...memory, limit: Number(event.target.value) })
                  }
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="primary-action" disabled={saving !== ""}>
                <Check size={14} /> 保存记忆策略
              </button>
            </div>
          </form>
          <form className="settings-card" onSubmit={saveSandbox}>
            <div className="settings-card-head">
              <div>
                <h2>代码沙箱</h2>
                <p>Docker 隔离执行，网络关闭并限制资源。</p>
              </div>
              <span
                className={`config-status ${sandbox.runtime_available ? "ok" : ""}`}
              >
                {sandbox.runtime_available ? "Docker 可用" : "Docker 未运行"}
              </span>
            </div>
            <div className="form-grid">
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={sandbox.enabled}
                  onChange={(event) =>
                    setSandbox({ ...sandbox, enabled: event.target.checked })
                  }
                />{" "}
                启用沙箱工具
              </label>
              <label>
                镜像
                <input
                  value={sandbox.image}
                  onChange={(event) =>
                    setSandbox({ ...sandbox, image: event.target.value })
                  }
                />
              </label>
              <label>
                超时（秒）
                <input
                  type="number"
                  min="1"
                  max="120"
                  value={sandbox.timeout_seconds}
                  onChange={(event) =>
                    setSandbox({
                      ...sandbox,
                      timeout_seconds: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                内存（MB）
                <input
                  type="number"
                  min="64"
                  max="2048"
                  value={sandbox.memory_mb}
                  onChange={(event) =>
                    setSandbox({
                      ...sandbox,
                      memory_mb: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                CPU
                <input
                  type="number"
                  min="0.1"
                  max="4"
                  step="0.1"
                  value={sandbox.cpu_limit}
                  onChange={(event) =>
                    setSandbox({
                      ...sandbox,
                      cpu_limit: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                进程上限
                <input
                  type="number"
                  min="16"
                  max="512"
                  value={sandbox.pids_limit}
                  onChange={(event) =>
                    setSandbox({
                      ...sandbox,
                      pids_limit: Number(event.target.value),
                    })
                  }
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="primary-action" disabled={saving !== ""}>
                <Check size={14} /> 保存沙箱策略
              </button>
            </div>
          </form>
          <form className="settings-card" onSubmit={saveMcp}>
            <div className="settings-card-head">
              <div>
                <h2>MCP 服务</h2>
                <p>连接远程 MCP 服务，发现的工具会进入 Agent 工具清单。</p>
              </div>
            </div>
            <div className="form-grid">
              <label>
                服务名
                <input
                  value={mcpName}
                  onChange={(event) => setMcpName(event.target.value)}
                  placeholder="support"
                />
              </label>
              <label>
                Endpoint
                <input
                  value={mcpEndpoint}
                  onChange={(event) => setMcpEndpoint(event.target.value)}
                  placeholder="https://.../rpc"
                />
              </label>
              <label>
                传输方式
                <select
                  value={mcpTransport}
                  onChange={(event) => setMcpTransport(event.target.value)}
                >
                  <option value="streamable_http">Streamable HTTP</option>
                  <option value="sse">SSE 响应（HTTP POST）</option>
                </select>
              </label>
              <label>
                请求超时（秒）
                <input
                  type="number"
                  min="1"
                  max="300"
                  value={mcpTimeout}
                  onChange={(event) =>
                    setMcpTimeout(Number(event.target.value))
                  }
                />
              </label>
              <label className="form-span-2">
                Authorization Token
                <input
                  type="password"
                  autoComplete="new-password"
                  value={mcpAuthorization}
                  onChange={(event) => setMcpAuthorization(event.target.value)}
                  placeholder="留空保留已有凭据，输入 Bearer Token"
                />
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={mcpEnabled}
                  onChange={(event) => setMcpEnabled(event.target.checked)}
                />
                启用 MCP 服务
              </label>
              {editingMcp && (
                <label className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={clearMcpAuthorization}
                    onChange={(event) =>
                      setClearMcpAuthorization(event.target.checked)
                    }
                  />
                  清除已保存凭据
                </label>
              )}
            </div>
            <div className="form-actions">
              {editingMcp && (
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => {
                    setEditingMcp(null);
                    setMcpName("");
                    setMcpEndpoint("");
                    setMcpAuthorization("");
                    setMcpTransport("streamable_http");
                    setMcpTimeout(20);
                    setMcpEnabled(true);
                    setClearMcpAuthorization(false);
                  }}
                >
                  取消编辑
                </button>
              )}
              <button className="primary-action" disabled={saving !== ""}>
                {editingMcp ? <Check size={14} /> : <Plus size={14} />}
                {editingMcp ? "更新 MCP 服务" : "添加 MCP 服务"}
              </button>
            </div>
            {settings.mcp?.servers?.map((server) => (
              <div
                className="tool-setting-row connection-setting-row"
                key={server.name}
              >
                <div>
                  <strong>{server.name}</strong>
                  <small>
                    {server.tools?.length || 0} 个已发现工具 · {server.endpoint}{" "}
                    · {server.transport} · 超时 {server.timeout_seconds} 秒 ·{" "}
                    {server.headers_configured ? "凭据已保存" : "无凭据"}
                  </small>
                </div>
                <span className={`config-status ${server.enabled ? "ok" : ""}`}>
                  {server.enabled ? "启用" : "停用"}
                </span>
                <div
                  className="connection-actions"
                  style={{
                    display: "flex",
                    gap: 4,
                    justifyContent: "flex-end",
                  }}
                >
                  <button
                    type="button"
                    className="icon-button"
                    title="重新发现 MCP 工具"
                    aria-label={`重新发现 ${server.name} 的 MCP 工具`}
                    disabled={saving !== ""}
                    onClick={() => void discoverMcp(server.name)}
                  >
                    <Radio size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    title="编辑 MCP 服务"
                    aria-label={`编辑 MCP 服务 ${server.name}`}
                    onClick={() => void editMcp(server)}
                  >
                    <Settings2 size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-button danger-action"
                    title="删除 MCP 服务"
                    aria-label={`删除 MCP 服务 ${server.name}`}
                    onClick={() => void deleteMcp(server.name)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </form>
          <form className="settings-card" onSubmit={saveA2a}>
            <div className="settings-card-head">
              <div>
                <h2>A2A Agent</h2>
                <p>发现 Agent Card，并允许 Agent 循环委派任务。</p>
              </div>
            </div>
            <div className="form-grid">
              <label>
                Agent 名称
                <input
                  value={a2aName}
                  onChange={(event) => setA2aName(event.target.value)}
                  placeholder="Research Agent"
                />
              </label>
              <label>
                Agent URL
                <input
                  value={a2aUrl}
                  onChange={(event) => setA2aUrl(event.target.value)}
                  placeholder="https://agent.example.com"
                />
              </label>
              <label>
                请求超时（秒）
                <input
                  type="number"
                  min="1"
                  max="120"
                  value={a2aTimeout}
                  onChange={(event) =>
                    setA2aTimeout(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Bearer Token
                <input
                  type="password"
                  autoComplete="new-password"
                  value={a2aToken}
                  onChange={(event) => setA2aToken(event.target.value)}
                  placeholder="留空保留已有凭据"
                />
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={a2aEnabled}
                  onChange={(event) => setA2aEnabled(event.target.checked)}
                />
                启用 A2A Agent
              </label>
              {editingA2a && (
                <label className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={clearA2aToken}
                    onChange={(event) => setClearA2aToken(event.target.checked)}
                  />
                  清除已保存 Token
                </label>
              )}
            </div>
            <div className="form-actions">
              {editingA2a && (
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => {
                    setEditingA2a(null);
                    setA2aName("");
                    setA2aUrl("");
                    setA2aToken("");
                    setA2aTimeout(20);
                    setA2aEnabled(true);
                    setClearA2aToken(false);
                  }}
                >
                  取消编辑
                </button>
              )}
              <button className="primary-action" disabled={saving !== ""}>
                {editingA2a ? <Check size={14} /> : <Plus size={14} />}
                {editingA2a ? "更新 A2A Agent" : "添加 A2A Agent"}
              </button>
            </div>
            {settings.a2a?.agents?.map((agentItem) => (
              <div
                className="tool-setting-row connection-setting-row"
                key={agentItem.id}
              >
                <div>
                  <strong>{agentItem.name}</strong>
                  <small>
                    {agentItem.agent_card
                      ? "Agent Card 已发现"
                      : "尚未发现 Agent Card"}{" "}
                    · {agentItem.url} · 超时 {agentItem.timeout_seconds} 秒 ·{" "}
                    {agentItem.bearer_token_configured
                      ? "凭据已保存"
                      : "无凭据"}
                  </small>
                </div>
                <span className="config-status ok">
                  {agentItem.enabled === false ? "停用" : "启用"}
                </span>
                <div
                  className="connection-actions"
                  style={{
                    display: "flex",
                    gap: 4,
                    justifyContent: "flex-end",
                  }}
                >
                  <button
                    type="button"
                    className="icon-button"
                    title="重新发现 Agent Card"
                    aria-label={`重新发现 ${agentItem.name} 的 Agent Card`}
                    disabled={saving !== ""}
                    onClick={() => void discoverA2a(agentItem)}
                  >
                    <Radio size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    title="编辑 A2A Agent"
                    aria-label={`编辑 A2A Agent ${agentItem.name}`}
                    onClick={() => editA2a(agentItem)}
                  >
                    <Settings2 size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-button danger-action"
                    title="删除 A2A Agent"
                    aria-label={`删除 A2A Agent ${agentItem.name}`}
                    onClick={() => void deleteA2a(agentItem.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </form>
          <div className="settings-card tools-settings">
            <div className="settings-card-head">
              <div>
                <h2>工具权限与限时</h2>
                <p>每个工具独立控制启用状态、权限等级和超时时间。</p>
              </div>
            </div>
            {tools.length ? (
              tools.map((tool) => (
                <div className="tool-setting-row" key={tool.name}>
                  <div>
                    <strong>{tool.name}</strong>
                    <small>{tool.description || "已注册工具"}</small>
                  </div>
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={tool.enabled !== false}
                      onChange={(event) =>
                        void updateTool(tool, { enabled: event.target.checked })
                      }
                    />
                    <span />
                  </label>
                  <select
                    value={tool.permission === "write" ? "write" : "read"}
                    onChange={(event) =>
                      void updateTool(tool, { permission: event.target.value })
                    }
                  >
                    <option value="read">只读</option>
                    <option value="write">写入（需审批）</option>
                  </select>
                  <input
                    className="timeout-input"
                    type="number"
                    min="1"
                    max="300"
                    value={tool.timeout_seconds || 30}
                    onChange={(event) =>
                      void updateTool(tool, {
                        timeout_seconds: Number(event.target.value),
                      })
                    }
                  />
                  <span className="unit-label">秒</span>
                </div>
              ))
            ) : (
              <div className="empty-inline">暂无已注册工具</div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function OperationalView({
  section,
  tools,
  approvals,
  runs,
  metrics,
  onDecision,
  onNavigate,
}: {
  section: string;
  tools: Tool[];
  approvals: Approval[];
  runs: Run[];
  metrics: Metrics;
  onDecision: (id: string, decision: "approve" | "reject") => void;
  onNavigate: (section: string) => void;
}) {
  const [search, setSearch] = useState("");
  if (section === "审批队列")
    return (
      <section className="ops-page">
        <div className="ops-heading">
          <div>
            <div className="eyebrow">GOVERNANCE / HUMAN REVIEW</div>
            <h1>审批队列</h1>
            <p>高风险工具调用需经授权人员复核后执行。</p>
          </div>
        </div>
        <div className="approval-banner">
          <ShieldAlert size={19} />
          <div>
            <strong>{approvals.length} 项待处理</strong>
            <span>所有操作均关联租户、会话和审计事件。</span>
          </div>
          <LockKeyhole size={17} />
        </div>
        <div className="ops-table">
          <div className="table-header">
            <span>工具 / 操作</span>
            <span>参数</span>
            <span>状态</span>
            <span>时间</span>
            <span>决策</span>
          </div>
          {approvals.map((item) => (
            <div className="approval-row" key={item.id}>
              <div className="approval-tool">
                <span className="tool-symbol">
                  <Wrench size={15} />
                </span>
                <span>
                  <strong>{item.tool_name || item.action || "工具调用"}</strong>
                  <small>{item.reason || "需要人工复核的工具调用"}</small>
                </span>
              </div>
              <span className="muted-cell">
                {item.arguments
                  ? JSON.stringify(item.arguments).slice(0, 80)
                  : "-"}
              </span>
              <span>
                <b className="risk-high">{item.status || "pending"}</b>
              </span>
              <span className="muted-cell">{item.created_at || "-"}</span>
              <div className="decision-actions">
                <button
                  className="reject-button"
                  onClick={() => void onDecision(item.id, "reject")}
                  title="拒绝"
                >
                  <X size={15} />
                </button>
                <button
                  className="approve-button"
                  onClick={() => void onDecision(item.id, "approve")}
                >
                  <Check size={14} /> 批准
                </button>
              </div>
            </div>
          ))}
          {!approvals.length && (
            <div className="empty-table">当前没有待处理审批</div>
          )}
        </div>
        <div className="audit-caption">
          <FileClock size={14} /> 审批决策会写入审计日志。
        </div>
      </section>
    );
  if (section === "工具中心")
    return (
      <section className="ops-page">
        <div className="ops-heading">
          <div>
            <div className="eyebrow">CAPABILITY REGISTRY</div>
            <h1>工具中心</h1>
            <p>查看已注册工具，并在设置中管理权限和执行策略。</p>
          </div>
          <button className="primary-action" onClick={() => onNavigate("设置")}>
            <Settings2 size={15} /> 管理工具配置
          </button>
        </div>
        <div className="toolbar">
          <label className="ops-search">
            <Search size={15} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索工具名称或描述"
            />
          </label>
          <span className="result-count">{tools.length} 个工具</span>
        </div>
        <div className="tool-grid">
          {tools
            .filter((tool) =>
              `${tool.name} ${tool.description || ""}`
                .toLowerCase()
                .includes(search.toLowerCase()),
            )
            .map((tool) => (
              <article className="tool-card" key={tool.name}>
                <div className="tool-card-head">
                  <span className="tool-symbol">
                    <Wrench size={16} />
                  </span>
                  <span
                    className={`permission-tag ${tool.permission || "read"}`}
                  >
                    {tool.permission === "write" ? "需审批" : "只读"}
                  </span>
                  <span
                    className={`tool-state ${tool.enabled === false ? "disabled" : ""}`}
                  >
                    {tool.enabled === false ? "已停用" : "已启用"}
                  </span>
                </div>
                <h3>{tool.name}</h3>
                <p>{tool.description || "已注册工具"}</p>
                <div className="tool-card-foot">
                  <span>超时 {tool.timeout_seconds || "-"} 秒</span>
                  <span>
                    JSON Schema <ArrowRight size={11} />
                  </span>
                </div>
              </article>
            ))}
        </div>
        {!tools.length && (
          <div className="empty-state">
            <Wrench size={20} />
            <strong>暂无工具</strong>
            <span>请在后端注册工具后刷新此页面。</span>
          </div>
        )}
      </section>
    );
  if (section === "评估指标") {
    const total = metrics.runs ?? metrics.tool_runs ?? 0;
    const successRate =
      metrics.success_rate ??
      (total ? (metrics.successful_runs || 0) / total : 0);
    return (
      <section className="ops-page">
        <div className="ops-heading">
          <div>
            <div className="eyebrow">OBSERVABILITY</div>
            <h1>评估指标</h1>
            <p>来自真实 Agent 运行与工具调用的聚合数据。</p>
          </div>
        </div>
        <div className="metric-cards">
          <MetricCard
            label="Agent 运行"
            value={total.toLocaleString()}
            change="当前累计"
            icon={<Activity size={16} />}
          />
          <MetricCard
            label="任务成功率"
            value={`${(successRate * (successRate <= 1 ? 100 : 1)).toFixed(1)}%`}
            change="当前累计"
            icon={<Check size={16} />}
          />
          <MetricCard
            label="待审批"
            value={String(metrics.pending_approvals || 0)}
            change="需要处理"
            icon={<ShieldAlert size={16} />}
          />
          <MetricCard
            label="工具失败"
            value={String(metrics.tool_failures || 0)}
            change="当前累计"
            icon={<Wrench size={16} />}
          />
        </div>
        <div className="empty-state metrics-empty">
          <Gauge size={20} />
          <strong>趋势图等待数据</strong>
          <span>当运行记录积累后，这里会展示按时间聚合的成功率与耗时。</span>
        </div>
      </section>
    );
  }
  if (section === "记忆库") return <MemoryPanel />;
  const filteredRuns = runs.filter((run) =>
    `${run.id} ${run.response || ""}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <section className="ops-page">
      <div className="ops-heading">
        <div>
          <div className="eyebrow">AGENT RUNS</div>
          <h1>运行记录</h1>
          <p>查看真实运行状态、响应和执行步骤。</p>
        </div>
      </div>
      <div className="toolbar">
        <label className="ops-search">
          <Search size={15} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索运行 ID 或响应内容"
          />
        </label>
        <span className="result-count">{filteredRuns.length} 条记录</span>
      </div>
      <div className="ops-table">
        <div className="table-header">
          <span>运行 ID</span>
          <span>响应摘要</span>
          <span>状态</span>
          <span>步骤</span>
          <span>时间</span>
        </div>
        {filteredRuns.map((run) => (
          <div className="history-row" key={run.id}>
            <div>
              <span className="tool-symbol">
                <Bot size={15} />
              </span>
              <span>
                <strong>{run.id.slice(0, 12)}</strong>
                <small>{run.session_id || run.conversation_id || "-"}</small>
              </span>
            </div>
            <span className="muted-cell">
              {(run.response || "").slice(0, 80) || "-"}
            </span>
            <span className="status-pill success">
              <span />
              {run.status || "-"}
            </span>
            <span className="muted-cell">{run.steps?.length || 0}</span>
            <span className="muted-cell">{run.created_at || "-"}</span>
          </div>
        ))}
        {!filteredRuns.length && (
          <div className="empty-table">暂无运行记录</div>
        )}
      </div>
    </section>
  );
}

function MemoryPanel() {
  const [items, setItems] = useState<Memory[]>([]);
  const [query, setQuery] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function load() {
    try {
      const result = await api<{ items: Memory[] }>(
        `/memory${query ? `/search?query=${encodeURIComponent(query)}` : ""}`,
      );
      setItems(result.items || []);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "记忆加载失败");
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function add() {
    if (!content.trim()) return;
    setBusy(true);
    try {
      await api("/memory", {
        method: "POST",
        body: JSON.stringify({
          content: content.trim(),
          memory_type: "fact",
          source: "console",
        }),
      });
      setContent("");
      setNotice("记忆已写入");
      await load();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "写入失败");
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    try {
      await api(`/memory/${id}`, { method: "DELETE" });
      setItems((current) => current.filter((item) => item.id !== id));
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "删除失败");
    }
  }
  return (
    <section className="ops-page">
      <div className="ops-heading">
        <div>
          <div className="eyebrow">MEMORY / VECTOR STORE</div>
          <h1>记忆库</h1>
          <p>管理长期记忆的写入、检索、删除和租户隔离。</p>
        </div>
      </div>
      {notice && <div className="settings-notice">{notice}</div>}
      <div className="toolbar">
        <label className="ops-search">
          <Search size={15} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void load();
            }}
            placeholder="输入关键词检索记忆"
          />
        </label>
        <span className="result-count">{items.length} 条记忆</span>
      </div>
      <div className="settings-card memory-compose">
        <div className="form-grid">
          <label className="form-span-2">
            新增长期记忆
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={3}
              placeholder="例如：客户偏好邮件通知"
            />
          </label>
        </div>
        <div className="form-actions">
          <button
            className="primary-action"
            onClick={() => void add()}
            disabled={busy}
          >
            <Plus size={14} /> 写入记忆
          </button>
        </div>
      </div>
      <div className="memory-list">
        {items.map((item) => (
          <div className="memory-row" key={item.id}>
            <span className="memory-type">{item.memory_type}</span>
            <p>{item.content}</p>
            <span>
              {item.similarity
                ? `相似度 ${(item.similarity * 100).toFixed(0)}%`
                : item.visibility}
            </span>
            <button
              className="icon-button"
              onClick={() => void remove(item.id)}
              title="删除记忆"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {!items.length && <div className="empty-table">暂无记忆记录</div>}
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  change,
  icon,
}: {
  label: string;
  value: string;
  change: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">
        {label}
        <span>{icon}</span>
      </div>
      <strong>{value}</strong>
      <small>{change}</small>
    </div>
  );
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Missing #root element");
createRoot(rootElement).render(<App />);
