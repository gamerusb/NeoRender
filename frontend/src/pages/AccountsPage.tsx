import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

export function AccountsPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [useAuth, setUseAuth] = useState(false);
  const [toast, setToast] = useState("");

  const statusQ = useQuery({
    queryKey: ["adspower-status"],
    queryFn: () => apiFetch<ApiJson>("/api/adspower/status"),
  });
  const profilesQ = useQuery({
    queryKey: ["profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/profiles", { tenantId }),
    refetchInterval: 20_000,
  });

  useEffect(() => {
    if (!statusQ.data) return;
    setApiBase(String(statusQ.data.api_base || ""));
    setUseAuth(Boolean(statusQ.data.use_auth));
  }, [statusQ.data]);
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(id);
  }, [toast]);

  const saveMut = useMutation({
    mutationFn: () =>
      apiFetch("/api/adspower/settings", {
        method: "POST",
        body: JSON.stringify({ api_base: apiBase, api_key: apiKey, use_auth: useAuth }),
      }),
    onSuccess: async () => {
      setToast("Настройки AdsPower сохранены");
      setApiKey("");
      await qc.invalidateQueries({ queryKey: ["adspower-status"] });
    },
    onError: (e: Error) => setToast(e.message),
  });

  const verifyMut = useMutation({
    mutationFn: (sync: boolean) => apiFetch(`/api/adspower/verify${sync ? "?sync_db=true" : ""}`, { tenantId }),
    onSuccess: async (d: ApiJson) => {
      setToast(String(d.message || "Проверка завершена"));
      await qc.invalidateQueries({ queryKey: ["profiles", tenantId] });
    },
    onError: (e: Error) => setToast(e.message),
  });

  const syncMut = useMutation({
    mutationFn: () => apiFetch("/api/profiles/sync", { method: "POST", tenantId }),
    onSuccess: async (d: ApiJson) => {
      setToast(String(d.message || "Профили синхронизированы"));
      await qc.invalidateQueries({ queryKey: ["profiles", tenantId] });
    },
    onError: (e: Error) => setToast(e.message),
  });

  const rows = useMemo(() => ((profilesQ.data?.profiles as ApiJson[] | undefined) ?? []), [profilesQ.data]);

  return (
    <section className="page">
      {toast && <div className="toast show ok">{toast}</div>}
      <div className="two-col">
        <div>
          <div className="card section-gap">
            <div className="card-header"><span className="card-title">AdsPower API</span></div>
            <div className="card-body">
              <div className="settings-row">
                <div style={{ flex: 1 }}>
                  <label className="form-label">Адрес API</label>
                  <input className="form-input mono" value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="form-label">API Key</label>
                  <input className="form-input mono" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="••••••••••" />
                </div>
              </div>
              <div className="settings-row">
                <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Проверка API (Bearer)</span>
                <div className={`toggle-switch ${useAuth ? "on" : ""}`} onClick={() => setUseAuth((v) => !v)} />
              </div>
              <div className="btn-group">
                <button type="button" className="btn btn-primary" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>Сохранить</button>
                <button type="button" className="btn btn-cyan" onClick={() => verifyMut.mutate(false)} disabled={verifyMut.isPending}>Проверить связь</button>
                <button type="button" className="btn" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>Синхронизировать</button>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-header"><span className="card-title">Профили AdsPower</span><span className="badge badge-neutral">{rows.length}</span></div>
            <div className="card-body">
              {rows.length === 0 ? (
                <div className="queue-empty"><div className="queue-empty-icon">●</div>Нет профилей. Нажмите «Синхронизировать»</div>
              ) : (
                <table className="data-table"><tbody>
                  {rows.map((r, i) => (
                    <tr key={`${r.adspower_id || "row"}-${i}`}>
                      <td className="mono">{String(r.adspower_id || "—")}</td>
                      <td>{String(r.group_name || "—")}</td>
                      <td>{String(r.name || "—")}</td>
                    </tr>
                  ))}
                </tbody></table>
              )}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><span className="card-title">Статус связки</span></div>
          <div className="card-body">
            <div className="status-list">
              <div className="status-row"><span className="status-row-label">Текущий API</span><span className="badge badge-info">{apiBase || "—"}</span></div>
              <div className="status-row"><span className="status-row-label">API Key</span><span className={`badge ${apiKey ? "badge-success" : "badge-warning"}`}>{apiKey ? "Задан" : "Не задан"}</span></div>
              <div className="status-row"><span className="status-row-label">Проверка API</span><span className={`badge ${useAuth ? "badge-info" : "badge-error"}`}>{useAuth ? "Включена" : "Выключена"}</span></div>
              <div className="status-row"><span className="status-row-label">Профилей</span><span className="badge badge-neutral">{rows.length}</span></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
