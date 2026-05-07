import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

// ── Types ─────────────────────────────────────────────────────────────────────

type ProfileRow = {
  adspower_profile_id: string;
  profile_name?: string;
  group_name?: string;
  proxy_name?: string;
  geo?: string;
  status?: string;
  last_sync_at?: string;
  last_launch_at?: string;
  last_publish_at?: string;
};

type BrowserRow = {
  id: number;
  name: string;
  browser_type: string;
  api_url: string;
  api_key?: string;
  use_auth?: boolean;
  is_active?: boolean;
  notes?: string;
  created_at?: string;
  updated_at?: string;
};

type VerifyResult = Record<number, { ok: boolean; message: string }>;

const STATUSES = ["new", "warmup", "ready", "publishing", "cooldown", "paused", "error", "archived"];

const BROWSER_TYPES = [
  { value: "adspower",     label: "AdsPower",      color: "#22c55e" },
  { value: "dolphin",      label: "Dolphin{anty}",  color: "#3b82f6" },
  { value: "octo",         label: "Octo Browser",  color: "#a855f7" },
  { value: "multilogin",   label: "Multilogin",    color: "#f97316" },
  { value: "gologin",      label: "GoLogin",       color: "#06b6d4" },
  { value: "undetectable", label: "Undetectable",  color: "#ec4899" },
  { value: "morelogin",    label: "MoreLogin",     color: "#eab308" },
  { value: "custom",       label: "Custom",        color: "#6b7280" },
];

const DEFAULT_PORTS: Record<string, number> = {
  adspower: 50325, dolphin: 3001, octo: 58888,
  multilogin: 35000, gologin: 36912, undetectable: 25325, morelogin: 8888,
};

function browserLabel(type: string) {
  return BROWSER_TYPES.find((b) => b.value === type)?.label ?? type;
}
function browserColor(type: string) {
  return BROWSER_TYPES.find((b) => b.value === type)?.color ?? "#6b7280";
}

// ── Add/Edit Browser Form ─────────────────────────────────────────────────────

type BrowserFormProps = {
  initial?: Partial<BrowserRow>;
  onSave: (data: Omit<BrowserRow, "id" | "created_at" | "updated_at">) => void;
  onCancel: () => void;
  isPending: boolean;
};

function BrowserForm({ initial, onSave, onCancel, isPending }: BrowserFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [type, setType] = useState(initial?.browser_type ?? "adspower");
  const [url, setUrl] = useState(initial?.api_url ?? "");
  const [key, setKey] = useState(initial?.api_key ?? "");
  const [useAuth, setUseAuth] = useState(initial?.use_auth ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");

  const defaultUrl = `http://127.0.0.1:${DEFAULT_PORTS[type] ?? 50325}`;

  function handleTypeChange(t: string) {
    setType(t);
    if (!url || url.startsWith("http://127.0.0.1:")) {
      setUrl(`http://127.0.0.1:${DEFAULT_PORTS[t] ?? 50325}`);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSave({
      name: name.trim(),
      browser_type: type,
      api_url: url.trim() || defaultUrl,
      api_key: key.trim(),
      use_auth: useAuth,
      is_active: true,
      notes: notes.trim(),
    });
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12, padding: "16px 0" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Name</span>
          <input
            className="form-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My GoLogin"
            required
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Browser Type</span>
          <select className="form-input" value={type} onChange={(e) => handleTypeChange(e.target.value)}>
            {BROWSER_TYPES.map((b) => (
              <option key={b.value} value={b.value}>{b.label}</option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Local API URL</span>
          <input
            className="form-input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={defaultUrl}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>API Key (optional)</span>
          <input
            className="form-input"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="only for MoreLogin / Multilogin"
            type="password"
            autoComplete="new-password"
          />
        </label>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text)" }}>
        <input type="checkbox" checked={useAuth} onChange={(e) => setUseAuth(e.target.checked)} />
        Use Bearer auth header
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Notes</span>
        <input className="form-input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional comment" />
      </label>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="submit" className="btn btn-cyan" disabled={isPending || !name.trim()}>
          {isPending ? "Saving…" : initial?.name ? "Update" : "Add Browser"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function ProfilesPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingBrowser, setEditingBrowser] = useState<BrowserRow | null>(null);
  const [verifyResults, setVerifyResults] = useState<VerifyResult>({});
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [verifyingId, setVerifyingId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<"non_ready" | null>(null);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

  // ── Queries ──────────────────────────────────────────────────────────────────

  const profilesQ = useQuery({
    queryKey: ["adspower-profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/adspower/profiles", { tenantId }),
    refetchInterval: 20_000,
  });

  const syncStatusQ = useQuery({
    queryKey: ["adspower-sync-status", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/system/adspower-sync-status", { tenantId }),
  });

  const healthQ = useQuery({
    queryKey: ["profiles-health", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/system/profiles-health", { tenantId }),
  });

  const browsersQ = useQuery({
    queryKey: ["antidetect-browsers", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/antidetect", { tenantId }),
    refetchInterval: 30_000,
  });

  // ── Mutations ─────────────────────────────────────────────────────────────────

  const syncMut = useMutation({
    mutationFn: () => apiFetch<ApiJson>("/api/adspower/profiles/sync", { method: "POST", tenantId }),
    onSuccess: async (data) => {
      setToast({ msg: String(data.message || "Профили синхронизированы"), kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
      await qc.invalidateQueries({ queryKey: ["adspower-sync-status", tenantId] });
      await qc.invalidateQueries({ queryKey: ["profiles-health", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const syncAllMut = useMutation({
    mutationFn: () => apiFetch<ApiJson>("/api/antidetect/sync-all", { method: "POST", tenantId }),
    onSuccess: async (data) => {
      setToast({ msg: String(data.message || "Все браузеры синхронизированы"), kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
      await qc.invalidateQueries({ queryKey: ["profiles-health", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const statusMut = useMutation({
    mutationFn: ({ profileId, status }: { profileId: string; status: string }) =>
      apiFetch<ApiJson>(`/api/adspower/profiles/${encodeURIComponent(profileId)}`, {
        method: "PATCH",
        tenantId,
        body: JSON.stringify({ status }),
      }),
    onSuccess: async () => {
      setToast({ msg: "Статус обновлён", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
      await qc.invalidateQueries({ queryKey: ["profiles-health", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const pauseMut = useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<ApiJson>(`/api/adspower/profiles/${encodeURIComponent(profileId)}/pause`, { method: "POST", tenantId }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const resumeMut = useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<ApiJson>(`/api/adspower/profiles/${encodeURIComponent(profileId)}/resume`, { method: "POST", tenantId }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const launchMut = useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<ApiJson>(`/api/adspower/profiles/${encodeURIComponent(profileId)}/launch-test`, { method: "POST", tenantId }),
    onSuccess: async (data) => {
      setToast({ msg: String(data.message || "Тест запуска завершён"), kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const addBrowserMut = useMutation({
    mutationFn: (body: Omit<BrowserRow, "id" | "created_at" | "updated_at">) =>
      apiFetch<ApiJson>("/api/antidetect", { method: "POST", tenantId, body: JSON.stringify(body) }),
    onSuccess: async (data) => {
      setToast({ msg: String(data.message || `Браузер добавлен`), kind: "ok" });
      setShowAddForm(false);
      await qc.invalidateQueries({ queryKey: ["antidetect-browsers", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const updateBrowserMut = useMutation({
    mutationFn: ({ id, ...body }: BrowserRow) =>
      apiFetch<ApiJson>(`/api/antidetect/${id}`, { method: "PUT", tenantId, body: JSON.stringify(body) }),
    onSuccess: async () => {
      setToast({ msg: "Настройки браузера обновлены", kind: "ok" });
      setEditingBrowser(null);
      await qc.invalidateQueries({ queryKey: ["antidetect-browsers", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const deleteBrowserMut = useMutation({
    mutationFn: (id: number) =>
      apiFetch<ApiJson>(`/api/antidetect/${id}`, { method: "DELETE", tenantId }),
    onSuccess: async () => {
      setToast({ msg: "Браузер удалён", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["antidetect-browsers", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  // ── Per-browser actions ───────────────────────────────────────────────────────

  async function handleVerify(browserId: number) {
    setVerifyingId(browserId);
    try {
      const res = await apiFetch<ApiJson>(`/api/antidetect/${browserId}/verify`, { method: "POST", tenantId });
      setVerifyResults((prev) => ({
        ...prev,
        [browserId]: { ok: res.status === "ok", message: String(res.message ?? (res.status === "ok" ? "Connected" : "Failed")) },
      }));
    } catch (e) {
      setVerifyResults((prev) => ({
        ...prev,
        [browserId]: { ok: false, message: (e as Error).message },
      }));
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleSync(browserId: number) {
    setSyncingId(browserId);
    try {
      const res = await apiFetch<ApiJson>(`/api/antidetect/${browserId}/sync`, { method: "POST", tenantId });
      setToast({ msg: String(res.message ?? "Синхронизировано"), kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
    } catch (e) {
      setToast({ msg: (e as Error).message, kind: "err" });
    } finally {
      setSyncingId(null);
    }
  }

  // ── Derived data ──────────────────────────────────────────────────────────────

  const rows = useMemo(() => ((profilesQ.data?.profiles as ProfileRow[] | undefined) ?? []), [profilesQ.data]);
  const browsers = useMemo(() => ((browsersQ.data?.browsers as BrowserRow[] | undefined) ?? []), [browsersQ.data]);
  const byStatus = (healthQ.data?.by_status as Record<string, number> | undefined) ?? {};
  const filteredRows = useMemo(() =>
    statusFilter === "non_ready" ? rows.filter(r => r.status !== "ready") : rows,
    [rows, statusFilter]
  );

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

      {/* ── Stats ──────────────────────────────────────────────────────────── */}
      <div className="stats-grid">
        <div className="stat-card green-accent">
          <div className="stat-label">✅ Готовы</div>
          <div className="stat-value green">{byStatus.ready || 0}</div>
        </div>
        <div className="stat-card cyan-accent">
          <div className="stat-label">🔄 Прогрев</div>
          <div className="stat-value cyan">{(byStatus.new || 0) + (byStatus.warmup || 0)}</div>
        </div>
        <div className="stat-card amber-accent">
          <div className="stat-label">⏸ На паузе</div>
          <div className="stat-value amber">{(byStatus.cooldown || 0) + (byStatus.paused || 0)}</div>
        </div>
        <div className="stat-card red-accent">
          <div className="stat-label">⚠️ Ошибка</div>
          <div className="stat-value red">{byStatus.error || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">🚫 Бан/Архив</div>
          <div className="stat-value">{byStatus.archived || 0}</div>
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <button
          type="button"
          className={`btn${statusFilter === "non_ready" ? " btn-cyan" : ""}`}
          onClick={() => setStatusFilter(v => v === "non_ready" ? null : "non_ready")}
        >
          {statusFilter === "non_ready" ? "✓ Только не готовые" : "Подготовить профили"}
        </button>
      </div>

      {/* ── Antidetect Browsers ────────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <span className="card-title">Antidetect Browsers</span>
          <div className="btn-group">
            <button type="button" className="btn btn-cyan" onClick={() => { setShowAddForm((v) => !v); setEditingBrowser(null); }}>
              {showAddForm ? "Cancel" : "+ Add Browser"}
            </button>
            <button type="button" className="btn" onClick={() => syncAllMut.mutate()} disabled={syncAllMut.isPending}>
              {syncAllMut.isPending ? "Syncing…" : "Sync All"}
            </button>
          </div>
        </div>

        {showAddForm && (
          <div style={{ padding: "0 20px" }}>
            <BrowserForm
              onSave={(data) => addBrowserMut.mutate(data)}
              onCancel={() => setShowAddForm(false)}
              isPending={addBrowserMut.isPending}
            />
          </div>
        )}

        {editingBrowser && (
          <div style={{ padding: "0 20px" }}>
            <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 4 }}>Editing: {editingBrowser.name}</div>
            <BrowserForm
              initial={editingBrowser}
              onSave={(data) => updateBrowserMut.mutate({ ...editingBrowser, ...data })}
              onCancel={() => setEditingBrowser(null)}
              isPending={updateBrowserMut.isPending}
            />
          </div>
        )}

        <div className="card-body-flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>API URL</th>
                <th>Auth</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {browsers.map((b) => {
                const vr = verifyResults[b.id];
                return (
                  <tr key={b.id}>
                    <td style={{ fontWeight: 500 }}>{b.name}</td>
                    <td>
                      <span style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        background: browserColor(b.browser_type) + "22",
                        color: browserColor(b.browser_type),
                        border: `1px solid ${browserColor(b.browser_type)}44`,
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                      }}>
                        {browserLabel(b.browser_type)}
                      </span>
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>{b.api_url}</td>
                    <td style={{ fontSize: 12, color: b.use_auth ? "var(--cyan)" : "var(--muted)" }}>
                      {b.use_auth ? "Bearer" : "—"}
                    </td>
                    <td>
                      {vr ? (
                        <span style={{ color: vr.ok ? "var(--green)" : "var(--red)", fontSize: 12 }}>
                          {vr.ok ? "✓ " : "✗ "}{vr.message}
                        </span>
                      ) : (
                        <span style={{ color: "var(--muted)", fontSize: 12 }}>—</span>
                      )}
                    </td>
                    <td>
                      <div className="toolbar">
                        <button
                          type="button"
                          className="action-btn"
                          onClick={() => handleVerify(b.id)}
                          disabled={verifyingId === b.id}
                        >
                          {verifyingId === b.id ? "…" : "Verify"}
                        </button>
                        <button
                          type="button"
                          className="action-btn"
                          onClick={() => handleSync(b.id)}
                          disabled={syncingId === b.id}
                        >
                          {syncingId === b.id ? "…" : "Sync"}
                        </button>
                        <button type="button" className="action-btn" onClick={() => { setEditingBrowser(b); setShowAddForm(false); }}>Edit</button>
                        <button
                          type="button"
                          className="action-btn"
                          style={{ color: "var(--red)" }}
                          onClick={() => { if (window.confirm(`Remove ${b.name}?`)) deleteBrowserMut.mutate(b.id); }}
                        >
                          Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {browsers.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <div className="empty-state">
                      Нет зарегистрированных браузеров. Нажмите «+ Add Browser» чтобы добавить AdsPower, GoLogin, Dolphin или другой антидетект.
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Profiles Table ─────────────────────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Profiles</span>
          <div className="btn-group">
            <button type="button" className="btn btn-cyan" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
              {syncMut.isPending ? "Syncing…" : "Sync AdsPower"}
            </button>
          </div>
        </div>
        <div className="card-body-flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>Profile</th>
                <th>ID</th>
                <th>Group</th>
                <th>Proxy</th>
                <th>Geo</th>
                <th>Status</th>
                <th>Last Sync</th>
                <th>Last Launch</th>
                <th>Last Publish</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => (
                <tr key={row.adspower_profile_id}>
                  <td>{row.profile_name || "—"}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{row.adspower_profile_id}</td>
                  <td>{row.group_name || "—"}</td>
                  <td>{row.proxy_name || "—"}</td>
                  <td>{row.geo || "—"}</td>
                  <td>
                    <select
                      className="form-input"
                      value={row.status || "new"}
                      onChange={(e) => statusMut.mutate({ profileId: row.adspower_profile_id, status: e.target.value })}
                    >
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td style={{ fontSize: 12 }}>{row.last_sync_at || "—"}</td>
                  <td style={{ fontSize: 12 }}>{row.last_launch_at || "—"}</td>
                  <td style={{ fontSize: 12 }}>{row.last_publish_at || "—"}</td>
                  <td>
                    <div className="toolbar">
                      <button type="button" className="action-btn" onClick={() => launchMut.mutate(row.adspower_profile_id)}>Launch Test</button>
                      <button type="button" className="action-btn" onClick={() => pauseMut.mutate(row.adspower_profile_id)}>Pause</button>
                      <button type="button" className="action-btn" onClick={() => resumeMut.mutate(row.adspower_profile_id)}>Resume</button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty-state">Профилей нет. Добавьте антидетект-браузер и выполните Sync.</div>
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
