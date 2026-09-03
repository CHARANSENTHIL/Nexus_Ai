'use client';
import { useEffect, useState, useRef, useCallback } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Types ─────────────────────────────────────────────────────────────────────
interface Metrics {
  cpu_percent: number;
  ram_percent: number;
  ram_available_gb: number;
  disk_percent: number;
  battery_percent: number | null;
  battery_plugged: boolean | null;
  network_connected: boolean;
  process_count: number;
  timestamp: string;
}

interface PendingApproval {
  approval_id: string;
  action_type: string;
  user_id: string;
}

interface AuditEntry {
  id: string;
  timestamp: string;
  user_id: string;
  action_type: string;
  outcome: string;
  execution_duration_seconds: number;
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ active, setActive }: { active: string; setActive: (s: string) => void }) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'approvals', label: 'Approvals', icon: '✅' },
    { id: 'audit', label: 'Audit Log', icon: '📋' },
    { id: 'workflows', label: 'Workflows', icon: '⚙️' },
    { id: 'agents', label: 'Agents', icon: '🤖' },
  ];
  return (
    <nav className="sidebar">
      <div className="logo">
        <div className="logo-icon">⚡</div>
        <span className="logo-text">Nexus AI</span>
      </div>
      {navItems.map(item => (
        <button
          key={item.id}
          id={`nav-${item.id}`}
          className={`nav-item ${active === item.id ? 'active' : ''}`}
          onClick={() => setActive(item.id)}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}

// ── Stat Card ─────────────────────────────────────────────────────────────────
function StatCard({ title, value, unit, color, fillClass, icon }:
  { title: string; value: number | null; unit: string; color: string; fillClass: string; icon: string }) {
  const pct = value ?? 0;
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">{title}</span>
        <span style={{ fontSize: 20 }}>{icon}</span>
      </div>
      <div className={`stat-value stat-${color}`}>
        {value !== null ? `${value.toFixed(1)}` : '—'}
        <span style={{ fontSize: 16, fontWeight: 400 }}>{unit}</span>
      </div>
      <div className="progress-bar">
        <div className={`progress-fill ${fillClass}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  );
}

// ── Dashboard Tab ─────────────────────────────────────────────────────────────
function DashboardTab({ metrics, history }: { metrics: Metrics | null; history: Metrics[] }) {
  const chartData = history.slice(-20).map((m, i) => ({
    t: i,
    cpu: m.cpu_percent,
    ram: m.ram_percent,
    disk: m.disk_percent,
  }));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">System Dashboard</h1>
        <p className="page-subtitle">
          <span className="live-dot" />
          Live metrics updated every 3 seconds
        </p>
      </div>

      <div className="grid grid-4" style={{ marginBottom: 24 }}>
        <StatCard title="CPU Usage" value={metrics?.cpu_percent ?? null} unit="%" color="blue" fillClass="fill-blue" icon="⚡" />
        <StatCard title="RAM Usage" value={metrics?.ram_percent ?? null} unit="%" color="purple" fillClass="fill-blue" icon="🧠" />
        <StatCard title="Disk Usage" value={metrics?.disk_percent ?? null} unit="%" color="yellow" fillClass="fill-yellow" icon="💾" />
        <StatCard title="Battery" value={metrics?.battery_percent ?? null} unit="%" color="green" fillClass="fill-green" icon="🔋" />
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-header">
            <span className="card-title">CPU + RAM History</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3a" />
              <XAxis dataKey="t" hide />
              <YAxis domain={[0, 100]} stroke="#555572" fontSize={11} />
              <Tooltip
                contentStyle={{ background: '#16161f', border: '1px solid #2a2a3a', borderRadius: 8, fontSize: 12 }}
              />
              <Line type="monotone" dataKey="cpu" stroke="#3b82f6" dot={false} strokeWidth={2} name="CPU %" />
              <Line type="monotone" dataKey="ram" stroke="#7c3aed" dot={false} strokeWidth={2} name="RAM %" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">System Status</span>
          </div>
          <table className="table">
            <tbody>
              <tr>
                <td>Network</td>
                <td>
                  <span className={`badge ${metrics?.network_connected ? 'badge-green' : 'badge-red'}`}>
                    {metrics?.network_connected ? '✓ Connected' : '✗ Offline'}
                  </span>
                </td>
              </tr>
              <tr>
                <td>Battery</td>
                <td>
                  <span className={`badge ${metrics?.battery_plugged ? 'badge-green' : 'badge-yellow'}`}>
                    {metrics?.battery_plugged ? '⚡ Charging' : '🔋 On Battery'}
                  </span>
                </td>
              </tr>
              <tr>
                <td>Processes</td>
                <td><span className="mono badge badge-blue">{metrics?.process_count ?? '—'}</span></td>
              </tr>
              <tr>
                <td>RAM Free</td>
                <td><span className="mono badge badge-purple">{metrics?.ram_available_gb?.toFixed(2) ?? '—'} GB</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Approvals Tab ─────────────────────────────────────────────────────────────
function ApprovalsTab({ pending, onResolve }: {
  pending: PendingApproval[];
  onResolve: (id: string, approved: boolean) => void;
}) {
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Approval Center</h1>
        <p className="page-subtitle">Dangerous actions awaiting your approval</p>
      </div>
      {pending.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>
          ✅ No pending approvals
        </div>
      ) : (
        pending.map(p => (
          <div key={p.approval_id} className="approval-card">
            <div className="card-title" style={{ marginBottom: 8 }}>Approval Required</div>
            <div className="approval-action">Action: {p.action_type}</div>
            <div className="mono" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
              User: {p.user_id} | ID: {p.approval_id}
            </div>
            <div className="approval-buttons">
              <button id={`approve-${p.approval_id}`} className="btn btn-success"
                onClick={() => onResolve(p.approval_id, true)}>✅ Approve</button>
              <button id={`reject-${p.approval_id}`} className="btn btn-danger"
                onClick={() => onResolve(p.approval_id, false)}>❌ Reject</button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ── Audit Log Tab ─────────────────────────────────────────────────────────────
function AuditTab({ entries }: { entries: AuditEntry[] }) {
  const outcomeColor: Record<string, string> = {
    executed: 'badge-green',
    approved: 'badge-green',
    rejected: 'badge-red',
    failed: 'badge-red',
    retried: 'badge-yellow',
  };
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Audit Log</h1>
        <p className="page-subtitle">Complete history of all agent actions</p>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Action</th>
              <th>Outcome</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No audit entries yet</td></tr>
            ) : entries.map(e => (
              <tr key={e.id}>
                <td className="mono">{new Date(e.timestamp).toLocaleTimeString()}</td>
                <td>{e.user_id}</td>
                <td>{e.action_type}</td>
                <td><span className={`badge ${outcomeColor[e.outcome] || 'badge-blue'}`}>{e.outcome}</span></td>
                <td className="mono">{e.execution_duration_seconds.toFixed(2)}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Workflows Tab ─────────────────────────────────────────────────────────────
function WorkflowsTab() {
  const workflows = [
    { name: 'Morning Brief', schedule: 'Daily at 8:00 AM', status: 'active', icon: '☀️' },
    { name: 'Automatic Backup', schedule: 'Daily at 11:00 PM', status: 'active', icon: '💾' },
    { name: 'Coding Workspace', schedule: 'Webhook trigger', status: 'active', icon: '💻' },
    { name: 'Download Organizer', schedule: 'Weekly on Sunday', status: 'active', icon: '📁' },
    { name: 'Security Monitor', schedule: 'Every 30 minutes', status: 'active', icon: '🔒' },
  ];
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">n8n Workflows</h1>
        <p className="page-subtitle">Automated workflow integrations via n8n</p>
      </div>
      <div className="grid grid-2">
        {workflows.map(w => (
          <div key={w.name} className="card">
            <div className="card-header">
              <span style={{ fontSize: 24 }}>{w.icon}</span>
              <span className="badge badge-green">● Active</span>
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{w.name}</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{w.schedule}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Agents Tab ────────────────────────────────────────────────────────────────
function AgentsTab() {
  const agents = [
    { name: 'Planner Agent', role: 'Goal decomposition + task graph generation', model: 'Llama 3 via Ollama', tools: 'LangChain + CrewAI', status: 'ready' },
    { name: 'System Agent', role: 'OS monitoring, processes, power control', model: 'Llama 3 via Ollama', tools: 'psutil, Digital Twin API', status: 'ready' },
    { name: 'Application Agent', role: 'Open/close apps, browser, shell commands', model: 'Llama 3 via Ollama', tools: 'subprocess, pywin32', status: 'ready' },
    { name: 'File Agent', role: 'Search, move, compress, organize files', model: 'Llama 3 via Ollama', tools: 'pathlib, shutil, zipfile', status: 'ready' },
  ];
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">AI Agents</h1>
        <p className="page-subtitle">LangChain + CrewAI specialized agents</p>
      </div>
      <div className="grid grid-2">
        {agents.map(a => (
          <div key={a.name} className="card">
            <div className="card-header">
              <span className="card-title">🤖 {a.name}</span>
              <span className="badge badge-green">Ready</span>
            </div>
            <div style={{ marginBottom: 8, color: 'var(--text-primary)', fontSize: 13 }}>{a.role}</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span className="badge badge-purple">🦙 {a.model}</span>
              <span className="badge badge-blue">🔧 {a.tools}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function Home() {
  const [active, setActive] = useState('dashboard');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [history, setHistory] = useState<Metrics[]>([]);
  const [pending, setPending] = useState<PendingApproval[]>([]);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const sseRef = useRef<EventSource | null>(null);

  // SSE metrics stream
  useEffect(() => {
    const es = new EventSource(`${API}/api/v1/metrics/stream`);
    sseRef.current = es;
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as Metrics;
        setMetrics(data);
        setHistory(prev => [...prev.slice(-99), data]);
      } catch {}
    };
    return () => es.close();
  }, []);

  // Poll pending approvals every 5s
  useEffect(() => {
    const poll = () => {
      fetch(`${API}/api/v1/planner/pending-approvals`)
        .then(r => r.json())
        .then(d => setPending(d.pending || []))
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  // Poll audit log every 10s
  useEffect(() => {
    const poll = () => {
      fetch(`${API}/api/v1/planner/audit-log?limit=50`)
        .then(r => r.json())
        .then(d => setAuditLog((d.audit_log || []).reverse()))
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 10000);
    return () => clearInterval(id);
  }, []);

  const resolveApproval = useCallback(async (approvalId: string, approved: boolean) => {
    await fetch(`${API}/api/v1/planner/resolve-approval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_id: approvalId, approved }),
    });
    setPending(prev => prev.filter(p => p.approval_id !== approvalId));
  }, []);

  return (
    <div className="layout">
      <Sidebar active={active} setActive={setActive} />
      <main className="main-content">
        {active === 'dashboard' && <DashboardTab metrics={metrics} history={history} />}
        {active === 'approvals' && <ApprovalsTab pending={pending} onResolve={resolveApproval} />}
        {active === 'audit' && <AuditTab entries={auditLog} />}
        {active === 'workflows' && <WorkflowsTab />}
        {active === 'agents' && <AgentsTab />}
      </main>
    </div>
  );
}
