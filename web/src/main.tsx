import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Activity, ArrowDown, ArrowRight, Bot, Check, ChevronDown, CircleHelp, Clock3, Code2, Command, Database, FileClock, Filter, Gauge, GitBranch, Layers3, LockKeyhole, Menu, MessageSquareText, MoreHorizontal, Plus, Radio, Search, Send, Settings2, ShieldAlert, ShieldCheck, Sparkles, Terminal, Wrench, X } from 'lucide-react'
import './styles.css'

type Trace = { id: string; kind: string; title: string; detail?: string; status: string; duration_ms?: number; created_at?: string }
type ChatMessage = { role: 'user' | 'assistant'; content: string; traces?: Trace[] }
type Session = { id: string; title?: string; status?: string; updated_at?: string }
type Tool = { name: string; description?: string; permission?: string; enabled?: boolean }
type Approval = { id: string; tool_name?: string; action?: string; reason?: string; status?: string }
type Metrics = { runs?: number; success_rate?: number; tool_failures?: number; avg_latency_ms?: number }

const API = import.meta.env.VITE_API_URL || '/api'
const demoTools: Tool[] = [
  { name: 'search_knowledge', description: '检索已授权的知识库', permission: 'read', enabled: true },
  { name: 'create_ticket', description: '创建并分派服务工单', permission: 'approval', enabled: true },
  { name: 'run_python', description: '隔离沙箱中的 Python 执行', permission: 'sandbox', enabled: true },
]
const demoMetrics: Metrics = { runs: 1284, success_rate: 96.4, tool_failures: 23, avg_latency_ms: 1840 }
const initialMessages: ChatMessage[] = [{ role: 'assistant', content: '你好，我是支持运营 Agent。可以检索知识库、梳理工单并起草处理建议。涉及外部写入的操作会先进入审批队列。' }]

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`)
  return response.json() as Promise<T>
}

function App() {
  const [section, setSection] = useState('工作台')
  const [drawer, setDrawer] = useState(false)
  const [query, setQuery] = useState('')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [online, setOnline] = useState(false)
  const [sessions, setSessions] = useState<Session[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages)
  const [tools, setTools] = useState<Tool[]>(demoTools)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [metrics, setMetrics] = useState<Metrics>(demoMetrics)
  const [activeTrace, setActiveTrace] = useState<Trace[]>([
    { id: 't1', kind: 'plan', title: '任务理解与计划', detail: '识别工单意图，检索相似案例，再整理处理建议。', status: 'completed', duration_ms: 18 },
    { id: 't2', kind: 'tool', title: 'search_knowledge', detail: 'collection=support-handbook · top_k=4', status: 'completed', duration_ms: 342 },
    { id: 't3', kind: 'reflection', title: '结果校验', detail: '检查引用相关性与租户范围。', status: 'completed', duration_ms: 27 },
  ])
  const [activeSession, setActiveSession] = useState<string | null>(null)

  useEffect(() => {
    Promise.allSettled([
      api<{ data?: Session[] } | Session[]>('/agents/sessions'),
      api<{ data?: Tool[] } | Tool[]>('/tools'),
      api<{ data?: Approval[] } | Approval[]>('/approvals'),
      api<Metrics>('/metrics/summary'),
    ]).then(([sessionResult, toolResult, approvalResult, metricResult]) => {
      const unwrap = <T,>(value: { data?: T[]; items?: T[] } | T[]): T[] => Array.isArray(value) ? value : value.data || value.items || []
      if (sessionResult.status === 'fulfilled') setSessions(unwrap(sessionResult.value))
      if (toolResult.status === 'fulfilled') setTools(unwrap(toolResult.value))
      if (approvalResult.status === 'fulfilled') setApprovals(unwrap(approvalResult.value))
      if (metricResult.status === 'fulfilled') setMetrics(metricResult.value)
      setOnline([sessionResult, toolResult, approvalResult, metricResult].some(result => result.status === 'fulfilled'))
    })
  }, [])

  const visibleSessions = useMemo(() => sessions.filter(session => (session.title || '新建对话').toLowerCase().includes(query.toLowerCase())), [sessions, query])

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    const content = input.trim()
    if (!content || busy) return
    setMessages(current => [...current, { role: 'user', content }])
    setInput('')
    setBusy(true)
    setActiveTrace([{ id: `plan-${Date.now()}`, kind: 'plan', title: '分析任务', detail: '拆解目标并选择合适的工具。', status: 'running' }])
    try {
      const result = await api<{ answer?: string; output?: string; content?: string; traces?: Trace[]; steps?: Trace[]; session_id?: string }>('/agents/runs', {
        method: 'POST', body: JSON.stringify({ message: content, ...(activeSession ? { session_id: activeSession } : {}), mode: 'react' }),
      })
      const trace = result.traces || result.steps || []
      setActiveTrace(trace.length ? trace : [{ id: 'done', kind: 'reflection', title: '任务完成', detail: 'Agent 已返回结果。', status: 'completed' }])
      if (result.session_id) setActiveSession(result.session_id)
      setMessages(current => [...current, { role: 'assistant', content: result.answer || result.output || result.content || (result as any).response || '运行完成。', traces: trace }])
    } catch {
      await new Promise(resolve => setTimeout(resolve, 550))
      const trace: Trace[] = [
        { id: `p-${Date.now()}`, kind: 'plan', title: '拆解请求', detail: '把问题拆分为知识检索与结果归纳。', status: 'completed', duration_ms: 16 },
        { id: `tool-${Date.now()}`, kind: 'tool', title: 'search_knowledge', detail: '在当前租户授权的知识集合中检索。', status: 'completed', duration_ms: 236 },
        { id: `review-${Date.now()}`, kind: 'reflection', title: '输出校验', detail: '引用范围与内容完整性检查通过。', status: 'completed', duration_ms: 21 },
      ]
      setActiveTrace(trace)
      setMessages(current => [...current, { role: 'assistant', content: `已完成请求分析：${content}\n\n当前运行在本地演示模式。连接后端后，这里将展示模型生成结果和真实工具调用。`, traces: trace }])
    } finally { setBusy(false) }
  }

  async function decideApproval(id: string, decision: 'approve' | 'reject') {
    try { await api(`/approvals/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) }) } catch { /* demo action */ }
    setApprovals(current => current.filter(item => item.id !== id))
  }

  const navItems = [
    { group: '工作区', rows: [{ name: '工作台', icon: MessageSquareText }, { name: '运行记录', icon: FileClock }, { name: '工具中心', icon: Wrench }] },
    { group: '治理', rows: [{ name: '审批队列', icon: ShieldAlert, count: approvals.length }, { name: '记忆库', icon: Database }, { name: '评估指标', icon: Gauge }] },
  ]

  return <div className="app-shell">
    <aside className={`sidebar ${drawer ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Layers3 size={17} /></div><span>FIELDNOTES</span><small>AGENT STUDIO</small><button className="icon-button sidebar-close" aria-label="关闭导航" onClick={() => setDrawer(false)}><X size={16} /></button></div>
      <button className="workspace-switch"><div className="workspace-avatar">N</div><span><strong>Northstar Support</strong><small>企业工作区</small></span><ChevronDown size={15} /></button>
      <button className="new-run" onClick={() => { setMessages(initialMessages); setActiveSession(null) }}><Plus size={16} /> 新建运行 <kbd>⌘ K</kbd></button>
      {navItems.map(group => <div className="nav-group" key={group.group}><div className="nav-label">{group.group}</div>{group.rows.map(item => <button key={item.name} onClick={() => { setSection(item.name); setDrawer(false) }} className={`nav-item ${section === item.name ? 'selected' : ''}`}><item.icon size={16} /><span>{item.name}</span>{item.count ? <b className="nav-count">{item.count}</b> : null}</button>)}</div>)}
      <div className="sessions-heading"><span>最近对话</span><button className="icon-button" aria-label="搜索会话"><Search size={14} /></button></div>
      <label className="session-search"><Search size={14} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索对话" /></label>
      <div className="session-list">{(visibleSessions.length ? visibleSessions : [{ id: 's-1', title: '退款申请 · 订单 #4381' }, { id: 's-2', title: '配送延迟问题排查' }, { id: 's-3', title: '整理本周升级工单' }]).map(session => <button className={`session-link ${activeSession === session.id ? 'active' : ''}`} key={session.id} onClick={() => setActiveSession(session.id)}><span className="session-dot" />{session.title || '新建对话'}</button>)}</div>
      <div className="sidebar-bottom"><div className="profile-avatar">LC</div><span><strong>Lin Chen</strong><small>平台管理员</small></span><MoreHorizontal size={17} /></div>
    </aside>
    {drawer && <button className="scrim" aria-label="关闭导航" onClick={() => setDrawer(false)} />}

    <main className="main-area">
      <header className="topbar"><button className="icon-button mobile-menu" aria-label="打开导航" onClick={() => setDrawer(true)}><Menu size={19} /></button><div className="breadcrumbs"><span>工作区</span><ArrowRight size={13} /><strong>{section}</strong></div><div className="top-actions"><span className={`connection ${online ? 'connected' : ''}`}><span />{online ? 'API 已连接' : '演示模式'}</span><button className="icon-button" title="帮助与文档"><CircleHelp size={17} /></button><button className="icon-button" title="设置"><Settings2 size={17} /></button></div></header>

      {section === '工作台' ? <div className="workspace">
        <section className="conversation-panel">
          <div className="conversation-head"><div><div className="eyebrow"><span className="live-pulse" />AGENT RUN · {activeSession?.slice(0, 12) || '新会话'}</div><h1>支持运营助手</h1></div><div className="head-controls"><button className="select-control"><Bot size={15} /> support-agent <ChevronDown size={13} /></button><button className="icon-button" title="更多操作"><MoreHorizontal size={18} /></button></div></div>
          <div className="run-mode"><span>运行模式</span><button className="mode-active">ReAct</button><button>Plan → Execute</button><span className="mode-separator" /><span className="model-label"><Radio size={13} /> openai-compatible <span className="model-dot" /> gpt-4o-mini</span></div>
          <div className="chat-scroll"><div className="date-divider"><span>今天 · 10:42</span></div>{messages.map((message, index) => <div key={`${message.role}-${index}`} className={`message-row ${message.role}`}><div className={`message-avatar ${message.role}`}>{message.role === 'assistant' ? <Sparkles size={15} /> : 'LC'}</div><div className="message-body"><div className="message-meta"><strong>{message.role === 'assistant' ? 'Support Agent' : '你'}</strong><span>{message.role === 'assistant' ? 'support-agent' : '10:42'}</span>{message.role === 'assistant' && <span className="safe-tag"><ShieldCheck size={12} /> 已检查</span>}</div><div className="message-content">{message.content}</div>{message.traces && <div className="inline-run"><span><Check size={13} /> {message.traces.length} 个步骤已完成</span><span>{message.traces.reduce((sum, trace) => sum + (trace.duration_ms || 0), 0)} ms</span><button onClick={() => setSection('运行记录')}>查看运行 <ArrowRight size={12} /></button></div>}</div></div>)}{busy && <div className="thinking"><span /><span /><span /> Agent 正在执行</div>}</div>
          <form className="composer" onSubmit={sendMessage}><div className="composer-tools"><button type="button" title="添加上下文"><Plus size={16} /></button><span><LockKeyhole size={13} /> 隔离上下文</span><button type="button" className="context-button"><Code2 size={14} /> 上下文 <ChevronDown size={12} /></button><button type="button" className="context-button"><Command size={14} /> 工具权限 <ChevronDown size={12} /></button></div><textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage(event as unknown as FormEvent) } }} placeholder="描述任务，或输入 / 调用工具…" rows={2} /><div className="composer-footer"><span>Enter 发送 · Shift + Enter 换行</span><div><button type="button" className="icon-button" title="运行选项"><Settings2 size={16} /></button><button className="send-button" type="submit" disabled={!input.trim() || busy} aria-label="发送消息"><Send size={15} /></button></div></div></form>
        </section>

        <aside className="inspector-panel"><div className="inspector-tabs"><button className="tab-active">运行详情</button><button onClick={() => setSection('工具中心')}>工具 <span>{tools.length}</span></button><button onClick={() => setSection('审批队列')}>审批 {approvals.length > 0 && <b>{approvals.length}</b>}</button></div><div className="inspector-content"><div className="run-summary"><div><span className="summary-label">当前运行</span><strong>run_8f3c2a</strong></div><span className="status-pill success"><span /> 成功</span></div><div className="summary-grid"><div><span>耗时</span><strong>1.24s</strong></div><div><span>Token</span><strong>842</strong></div><div><span>迭代</span><strong>{activeTrace.length || 3}</strong></div></div><div className="trace-title"><h2>执行轨迹</h2><button className="icon-button" title="筛选步骤"><Filter size={15} /></button></div><div className="trace-list">{activeTrace.map((trace, index) => <div className="trace-item" key={trace.id}><div className={`trace-icon ${trace.kind}`}>{trace.kind === 'tool' ? <Wrench size={14} /> : trace.kind === 'reflection' ? <ShieldCheck size={14} /> : <GitBranch size={14} />}</div><div className="trace-info"><div className="trace-name">{trace.title}<span className={`trace-state ${trace.status}`}>{trace.status === 'completed' ? '完成' : trace.status === 'running' ? '运行中' : trace.status}</span></div><p>{trace.detail || 'Agent 正在处理该步骤。'}</p><div className="trace-meta"><span>{trace.kind === 'tool' ? 'TOOL CALL' : trace.kind.toUpperCase()}</span>{trace.duration_ms && <span><Clock3 size={11} /> {trace.duration_ms} ms</span>}</div></div>{index < activeTrace.length - 1 && <div className="trace-connector" />}</div>)}</div><div className="guardrail-note"><div><ShieldCheck size={15} /><strong>安全策略已启用</strong></div><p>写入类工具需要人工审批 · PII 自动脱敏</p><button onClick={() => setSection('审批队列')}>查看策略 <ArrowRight size={12} /></button></div><div className="runtime-footer"><span><span className="tiny-online" />运行器正常</span><span>us-east-1 · worker-03</span></div></div></aside>
      </div> : <OperationalView section={section} tools={tools} approvals={approvals} metrics={metrics} onDecision={decideApproval} />}
    </main>
  </div>
}

function OperationalView({ section, tools, approvals, metrics, onDecision }: { section: string; tools: Tool[]; approvals: Approval[]; metrics: Metrics; onDecision: (id: string, decision: 'approve' | 'reject') => void }) {
  const [filter, setFilter] = useState('全部')
  const [search, setSearch] = useState('')
  const [showContext, setShowContext] = useState(false)
  const title = section
  if (section === '审批队列') return <section className="ops-page"><div className="ops-heading"><div><div className="eyebrow">GOVERNANCE / HUMAN REVIEW</div><h1>审批队列</h1><p>高风险工具调用需经授权人员复核后执行。</p></div><div className="ops-heading-actions"><button className="select-control"><Filter size={14} /> {filter} <ChevronDown size={13} /></button></div></div><div className="approval-banner"><ShieldAlert size={19} /><div><strong>{approvals.length || 0} 项待处理</strong><span>所有操作均关联租户、会话和审计事件。</span></div><LockKeyhole size={17} /></div><div className="ops-table"><div className="table-header"><span>工具 / 操作</span><span>请求来源</span><span>风险级别</span><span>时间</span><span>决策</span></div>{(approvals.length ? approvals : [{ id: 'demo-approval', tool_name: 'create_ticket', action: '创建工单 · #SUP-2841', reason: '将写入 CRM 工单系统', status: 'pending' }]).map(item => <div className="approval-row" key={item.id}><div className="approval-tool"><span className="tool-symbol"><Wrench size={15} /></span><span><strong>{item.tool_name || item.action || '工具调用'}</strong><small>{item.reason || '外部系统写入操作'}</small></span></div><span className="muted-cell">support-agent · run_8f3c</span><span><b className="risk-high">需复核</b></span><span className="muted-cell">刚刚</span><div className="decision-actions"><button className="reject-button" onClick={() => onDecision(item.id, 'reject')} title="拒绝"><X size={15} /></button><button className="approve-button" onClick={() => onDecision(item.id, 'approve')}><Check size={14} /> 批准</button></div></div>)}</div><div className="audit-caption"><FileClock size={14} /> 决策将写入不可变审计日志，并记录审批人、时间与请求摘要。</div></section>
  if (section === '工具中心') return <section className="ops-page"><div className="ops-heading"><div><div className="eyebrow">CAPABILITY REGISTRY</div><h1>工具中心</h1><p>管理 Agent 可发现的工具、权限范围和执行策略。</p></div><button className="primary-action"><Plus size={15} /> 注册工具</button></div><div className="toolbar"><label className="ops-search"><Search size={15} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索工具名称或描述" /></label><button className="select-control"><Filter size={14} /> 所有权限 <ChevronDown size={13} /></button><span className="result-count">{tools.length} 个工具</span></div><div className="tool-grid">{tools.filter(tool => `${tool.name} ${tool.description}`.toLowerCase().includes(search.toLowerCase())).map(tool => <article className="tool-card" key={tool.name}><div className="tool-card-head"><span className="tool-symbol"><Wrench size={16} /></span><span className={`permission-tag ${tool.permission || 'read'}`}>{tool.permission === 'approval' ? '需审批' : tool.permission === 'sandbox' ? '沙箱' : '只读'}</span><button className="icon-button" title="更多操作"><MoreHorizontal size={17} /></button></div><h3>{tool.name}</h3><p>{tool.description || '已注册的 Agent 工具'}</p><div className="tool-card-foot"><span><span className="tiny-online" />{tool.enabled === false ? '已停用' : '已启用'}</span><span>JSON Schema <ArrowRight size={11} /></span></div></article>)}</div><div className="protocol-strip"><div><Radio size={16} /><span><strong>MCP 连接器</strong><small>发现并调用外部 MCP Server 工具</small></span></div><span className="coming-state">连接管理 <ArrowRight size={13} /></span><div><GitBranch size={16} /><span><strong>A2A Agent</strong><small>委派任务至远程 Agent</small></span></div><span className="coming-state">Agent Directory <ArrowRight size={13} /></span></div></section>
  if (section === '评估指标') return <section className="ops-page"><div className="ops-heading"><div><div className="eyebrow">OBSERVABILITY / LAST 7 DAYS</div><h1>评估指标</h1><p>运行质量、工具可靠性与响应耗时。</p></div><button className="select-control"><Clock3 size={14} /> 最近 7 天 <ChevronDown size={13} /></button></div><div className="metric-cards"><MetricCard label="Agent 运行" value={(metrics.runs || 1284).toLocaleString()} change="+12.8%" icon={<Activity size={16} />} /><MetricCard label="任务成功率" value={`${metrics.success_rate || 96.4}%`} change="+2.1%" icon={<Check size={16} />} /><MetricCard label="工具失败" value={String(metrics.tool_failures || 23)} change="-8.4%" icon={<Wrench size={16} />} /><MetricCard label="平均耗时" value={`${((metrics.avg_latency_ms || 1840) / 1000).toFixed(2)}s`} change="-0.3s" icon={<Clock3 size={16} />} /></div><div className="chart-section"><div className="chart-heading"><div><h2>运行与成功率</h2><p>按日聚合 · UTC</p></div><div className="chart-legend"><span><i />成功运行</span><span><i />失败运行</span></div></div><div className="chart-bars">{[42, 58, 49, 74, 65, 90, 71, 85, 66, 96, 78, 88, 58, 79, 95, 68, 84, 73, 100, 82, 64, 93, 76, 87].map((height, i) => <div className="bar-wrap" key={i}><div className="bar-success" style={{ height: `${height}%` }}><span style={{ height: `${Math.max(5, height * 0.08)}%` }} /></div></div>)}</div><div className="chart-x"><span>11/18</span><span>11/20</span><span>11/22</span><span>11/24</span></div></div><div className="evaluation-row"><div><strong>离线评估集</strong><span>客服工单基准 · 240 条样本</span></div><span className="score">准确率 <b>92.1%</b></span><span className="score">工具选择 <b>96.7%</b></span><button className="text-action">查看评估 <ArrowRight size={13} /></button></div></section>
  if (section === '记忆库') return <section className="ops-page"><div className="ops-heading"><div><div className="eyebrow">MEMORY / TENANT SCOPED</div><h1>记忆库</h1><p>管理会话摘要和经过授权的长期业务记忆。</p></div><button className="select-control"><Database size={14} /> Northstar Support <ChevronDown size={13} /></button></div><div className="memory-stats"><div><span>短期会话</span><strong>18</strong><small>滑动窗口 · 最近 20 轮</small></div><div><span>长期记忆</span><strong>326</strong><small>向量召回 · 相似度阈值 0.78</small></div><div><span>自动过期</span><strong>30 天</strong><small>个人信息按策略提前遗忘</small></div></div><div className="memory-list"><div className="memory-head"><strong>最近更新</strong><button className="text-action" onClick={() => setShowContext(!showContext)}>筛选记忆 <Filter size={13} /></button></div>{['企业客户 Northstar 的退款政策为 30 天内可退。', '用户偏好在问题处理中优先提供订单状态。', 'SUP-2810 与配送承运商回传延迟相关。'].map((memory, i) => <div className="memory-row" key={memory}><span className="memory-type">{i === 0 ? '业务规则' : i === 1 ? '用户偏好' : '历史工单'}</span><p>{memory}</p><span>支持运营 · {i + 2} 天前</span><button className="icon-button" title="删除记忆"><X size={14} /></button></div>)}</div>{showContext && <div className="guardrail-note"><ShieldCheck size={15} /> 显示当前租户可访问的记忆；原始敏感字段已过滤。</div>}</section>
  return <section className="ops-page"><div className="ops-heading"><div><div className="eyebrow">AGENT STUDIO</div><h1>{title}</h1><p>查看和筛选 Agent 运行及审计轨迹。</p></div><button className="select-control"><Clock3 size={14} /> 最近 24 小时 <ChevronDown size={13} /></button></div><div className="toolbar"><label className="ops-search"><Search size={15} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索运行、会话或 Agent" /></label><button className="select-control"><Filter size={14} /> 所有状态 <ChevronDown size={13} /></button></div><div className="ops-table"><div className="table-header"><span>运行 / Agent</span><span>触发方式</span><span>状态</span><span>耗时</span><span>时间</span></div>{['支持运营助手', '退款政策问答', '配送异常分析'].filter(name => name.toLowerCase().includes(search.toLowerCase())).map((name, i) => <div className="history-row" key={name}><div><span className="tool-symbol"><Bot size={15} /></span><span><strong>{name}</strong><small>run_{['8f3c2a', '32a1dc', '91b7fe'][i]} · support-agent</small></span></div><span className="muted-cell">对话触发</span><span className="status-pill success"><span />成功</span><span className="muted-cell">{['1.24s', '2.08s', '0.94s'][i]}</span><span className="muted-cell">{['刚刚', '8 分钟前', '23 分钟前'][i]}</span></div>)}</div></section>
}

function MetricCard({ label, value, change, icon }: { label: string; value: string; change: string; icon: React.ReactNode }) { return <div className="metric-card"><div className="metric-label">{label}<span>{icon}</span></div><strong>{value}</strong><small><b>{change}</b> 对比上一周期</small></div> }

export default App
