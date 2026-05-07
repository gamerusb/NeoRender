import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

// ── Types ─────────────────────────────────────────────────────────────────────

type ProxyRow = {
  id: number;
  name: string;
  protocol: string;
  host: string;
  port: number;
  username?: string;
  group_name?: string;
  geo?: string;
  geo_city?: string;
  detected_ip?: string;
  status: "alive" | "slow" | "dead" | "unchecked";
  latency_ms?: number;
  last_checked_at?: string;
  notes?: string;
};

const PROTOCOLS = ["http", "https", "socks5"] as const;

const STATUS_COLOR: Record<string, string> = {
  alive:     "var(--green)",
  slow:      "var(--amber)",
  dead:      "var(--red)",
  unchecked: "var(--muted)",
};
const STATUS_LABEL: Record<string, string> = {
  alive:     "alive",
  slow:      "slow",
  dead:      "dead",
  unchecked: "—",
};

// ── Add Proxy Form ────────────────────────────────────────────────────────────

type AddFormProps = { onClose: () => void; isPending: boolean; onSave: (v: AddPayload) => void };
type AddPayload = { host: string; port: number; protocol: string; username: string; password: string; name: string; group_name: string; notes: string };

function AddProxyForm({ onClose, isPending, onSave }: AddFormProps) {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("8080");
  const [protocol, setProtocol] = useState("http");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [group, setGroup] = useState("");
  const [notes, setNotes] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSave({ host: host.trim(), port: parseInt(port, 10), protocol, username, password, name, group_name: group, notes });
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 0" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 120px", gap: 10 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Host</span>
          <input className="form-input" value={host} onChange={e => setHost(e.target.value)} placeholder="103.152.34.12" required />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Port</span>
          <input className="form-input" value={port} onChange={e => setPort(e.target.value)} placeholder="8080" type="number" min={1} max={65535} required />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Protocol</span>
          <select className="form-input" value={protocol} onChange={e => setProtocol(e.target.value)}>
            {PROTOCOLS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Login</span>
          <input className="form-input" value={username} onChange={e => setUsername(e.target.value)} placeholder="user (opt.)" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Password</span>
          <input className="form-input" value={password} onChange={e => setPassword(e.target.value)} placeholder="pass (opt.)" type="password" autoComplete="new-password" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Name</span>
          <input className="form-input" value={name} onChange={e => setName(e.target.value)} placeholder="KR_main_01 (opt.)" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase" }}>Group</span>
          <input className="form-input" value={group} onChange={e => setGroup(e.target.value)} placeholder="KR_shorts (opt.)" />
        </label>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="submit" className="btn btn-cyan" disabled={isPending || !host.trim()}>
          {isPending ? "Saving…" : "Add Proxy"}
        </button>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
      </div>
    </form>
  );
}

// ── Bulk Import Form ──────────────────────────────────────────────────────────

function BulkImportForm({ onClose, onSave, isPending }: { onClose: () => void; onSave: (lines: string, group: string) => void; isPending: boolean }) {
  const [lines, setLines] = useState("");
  const [group, setGroup] = useState("");

  return (
    <div style={{ padding: "12px 0" }}>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>
        Один прокси на строку. Форматы:<br />
        <code>host:port</code> · <code>host:port:user:pass</code> · <code>socks5://user:pass@host:port</code>
      </div>
      <textarea
        className="form-input"
        rows={8}
        value={lines}
        onChange={e => setLines(e.target.value)}
        placeholder={"103.152.34.12:8080\n103.152.34.15:8080:user:pass\nsocks5://u:p@45.77.88.102:1080"}
        style={{ fontFamily: "var(--font-mono)", fontSize: 12, resize: "vertical", width: "100%" }}
      />
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input className="form-input" style={{ maxWidth: 180 }} value={group} onChange={e => setGroup(e.target.value)} placeholder="Group name (opt.)" />
        <button className="btn btn-cyan" disabled={isPending || !lines.trim()} onClick={() => onSave(lines, group)}>
          {isPending ? "Importing…" : "Import"}
        </button>
        <button className="btn" onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function ProxyPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [filterGroup, setFilterGroup] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const checkingAll = useRef(false);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(id);
  }, [toast]);

  // ── Queries ───────────────────────────────────────────────────────────────

  const proxiesQ = useQuery({
    queryKey: ["proxies", tenantId, filterGroup, filterStatus],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filterGroup) params.set("group", filterGroup);
      if (filterStatus) params.set("status", filterStatus);
      return apiFetch<ApiJson>(`/api/proxies?${params}`, { tenantId });
    },
    refetchInterval: 30_000,
  });

  const rows = useMemo(() => (proxiesQ.data?.proxies as ProxyRow[] | undefined) ?? [], [proxiesQ.data]);

  const groups = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) if (r.group_name) s.add(r.group_name);
    return [...s].sort();
  }, [rows]);

  const stats = proxiesQ.data ?? {};

  // ── Mutations ─────────────────────────────────────────────────────────────

  const addMut = useMutation({
    mutationFn: (body: AddPayload) => apiFetch<ApiJson>("/api/proxies", { method: "POST", tenantId, body: JSON.stringify(body) }),
    onSuccess: async (d) => {
      setToast({ msg: String(d.message ?? "Прокси добавлен"), kind: "ok" });
      setShowAdd(false);
      await qc.invalidateQueries({ queryKey: ["proxies", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const bulkMut = useMutation({
    mutationFn: ({ lines, group }: { lines: string; group: string }) =>
      apiFetch<ApiJson>("/api/proxies/bulk", { method: "POST", tenantId, body: JSON.stringify({ lines, group_name: group }) }),
    onSuccess: async (d) => {
      setToast({ msg: `Импортировано: ${d.added ?? 0}`, kind: "ok" });
      setShowBulk(false);
      await qc.invalidateQueries({ queryKey: ["proxies", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => apiFetch<ApiJson>(`/api/proxies/${id}`, { method: "DELETE", tenantId }),
    onSuccess: async () => {
      setToast({ msg: "Прокси удалён", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["proxies", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  async function handleCheckOne(row: ProxyRow) {
    setCheckingId(row.id);
    try {
      const res = await apiFetch<ApiJson>(`/api/proxies/${row.id}/check`, { method: "POST", tenantId });
      const s = res.status === "ok" ? (res.status as string) : "dead";
      setToast({ msg: `${row.host}:${row.port} → ${res.status ?? s} (${res.latency_ms ?? "?"}ms)`, kind: res.status === "ok" ? "ok" : "err" });
      await qc.invalidateQueries({ queryKey: ["proxies", tenantId] });
    } catch (e) {
      setToast({ msg: (e as Error).message, kind: "err" });
    } finally {
      setCheckingId(null);
    }
  }

  async function handleCheckAll() {
    if (checkingAll.current) return;
    checkingAll.current = true;
    try {
      const res = await apiFetch<ApiJson>("/api/proxies/check-all", { method: "POST", tenantId });
      setToast({ msg: `Проверено: ${res.checked ?? 0} — alive ${res.alive ?? 0} / slow ${res.slow ?? 0} / dead ${res.dead ?? 0}`, kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["proxies", tenantId] });
    } catch (e) {
      setToast({ msg: (e as Error).message, kind: "err" });
    } finally {
      checkingAll.current = false;
    }
  }

  // ── Alerts ────────────────────────────────────────────────────────────────

  const alerts = useMemo(() => {
    const out: string[] = [];
    for (const r of rows) {
      if (r.status === "dead") out.push(`${r.host}:${r.port} — timeout (мёртвый)`);
      else if (r.status === "slow" && (r.latency_ms ?? 0) > 2000) out.push(`${r.host}:${r.port} — latency ${r.latency_ms}ms`);
    }
    return out;
  }, [rows]);

  return (
    <section className="page">
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)} aria-label="Закрыть">✕</button>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="stats-grid">
        {[
          { label: "Всего",       value: stats.count ?? rows.length,                              cls: "cyan",  accent: "cyan-accent" },
          { label: "Alive",       value: stats.alive ?? rows.filter(r => r.status === "alive").length, cls: "green", accent: "green-accent" },
          { label: "Slow",        value: stats.slow  ?? rows.filter(r => r.status === "slow").length,  cls: "amber", accent: "amber-accent" },
          { label: "Dead",        value: stats.dead  ?? rows.filter(r => r.status === "dead").length,  cls: "red",   accent: "red-accent" },
          { label: "Не проверено", value: rows.filter(r => r.status === "unchecked").length,           cls: "",      accent: "" },
        ].map(s => (
          <div key={s.label} className={`stat-card ${s.accent}`}>
            <div className="stat-label">{s.label}</div>
            <div className={`stat-value ${s.cls}`}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--red)" }}>
          <div className="card-header"><span className="card-title" style={{ color: "var(--red)" }}>Alerts</span></div>
          <div className="card-body" style={{ fontSize: 12 }}>
            {alerts.map((a, i) => (
              <div key={i} style={{ padding: "4px 0", color: "var(--red)", borderBottom: i < alerts.length - 1 ? "1px solid var(--border-subtle)" : "none" }}>
                {a}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Proxy List */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Proxy Pool</span>
          <div className="btn-group">
            {/* Filters */}
            <select className="form-input" style={{ minWidth: 120, height: 32, fontSize: 12 }} value={filterGroup} onChange={e => setFilterGroup(e.target.value)}>
              <option value="">All groups</option>
              {groups.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
            <select className="form-input" style={{ minWidth: 110, height: 32, fontSize: 12 }} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
              <option value="">All status</option>
              <option value="alive">alive</option>
              <option value="slow">slow</option>
              <option value="dead">dead</option>
              <option value="unchecked">unchecked</option>
            </select>
            <button className="btn" onClick={handleCheckAll}>Check All</button>
            <button className="btn" onClick={() => { setShowBulk(v => !v); setShowAdd(false); }}>Bulk Import</button>
            <button className="btn btn-cyan" onClick={() => { setShowAdd(v => !v); setShowBulk(false); }}>+ Add</button>
          </div>
        </div>

        {showAdd && (
          <div style={{ padding: "0 20px" }}>
            <AddProxyForm onClose={() => setShowAdd(false)} isPending={addMut.isPending} onSave={addMut.mutate} />
          </div>
        )}
        {showBulk && (
          <div style={{ padding: "0 20px" }}>
            <BulkImportForm onClose={() => setShowBulk(false)} onSave={(lines, group) => bulkMut.mutate({ lines, group })} isPending={bulkMut.isPending} />
          </div>
        )}

        <div className="card-body-flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Proxy</th>
                <th>Protocol</th>
                <th>Group</th>
                <th>Geo</th>
                <th>Real IP</th>
                <th>Latency</th>
                <th>Last Check</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.id}>
                  <td>
                    <span style={{
                      display: "inline-block",
                      width: 8, height: 8,
                      borderRadius: "50%",
                      background: STATUS_COLOR[row.status] ?? "var(--muted)",
                      marginRight: 6,
                      boxShadow: row.status === "alive" ? `0 0 4px ${STATUS_COLOR[row.status]}` : undefined,
                    }} />
                    <span style={{ fontSize: 12, color: STATUS_COLOR[row.status] }}>
                      {STATUS_LABEL[row.status]}
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: 12 }}>{row.host}:{row.port}</td>
                  <td style={{ fontSize: 12 }}>{row.protocol}</td>
                  <td style={{ fontSize: 12 }}>{row.group_name || "—"}</td>
                  <td style={{ fontSize: 12 }}>{row.geo ? `${row.geo}${row.geo_city ? ` · ${row.geo_city}` : ""}` : "—"}</td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{row.detected_ip || "—"}</td>
                  <td style={{ fontSize: 12, color: row.latency_ms ? (row.latency_ms > 2000 ? "var(--amber)" : "var(--green)") : "var(--muted)" }}>
                    {row.latency_ms != null ? `${row.latency_ms}ms` : "—"}
                  </td>
                  <td style={{ fontSize: 11, color: "var(--muted)" }}>
                    {row.last_checked_at ? row.last_checked_at.slice(0, 16).replace("T", " ") : "—"}
                  </td>
                  <td>
                    <div className="toolbar">
                      <button
                        className="action-btn"
                        onClick={() => handleCheckOne(row)}
                        disabled={checkingId === row.id}
                      >
                        {checkingId === row.id ? "…" : "Check"}
                      </button>
                      <button
                        className="action-btn"
                        style={{ color: "var(--red)" }}
                        onClick={() => { if (window.confirm(`Delete ${row.host}:${row.port}?`)) deleteMut.mutate(row.id); }}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty-state">
                      Нет прокси. Добавьте через «+ Add» или «Bulk Import» (одна строка = один прокси).
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
