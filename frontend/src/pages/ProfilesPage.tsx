import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

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

const STATUSES = ["new", "warmup", "ready", "publishing", "cooldown", "paused", "error", "archived"];

export function ProfilesPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

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

  const statusMut = useMutation({
    mutationFn: ({ profileId, status }: { profileId: string; status: string }) =>
      apiFetch<ApiJson>(`/api/adspower/profiles/${encodeURIComponent(profileId)}`, {
        method: "PATCH",
        tenantId,
        body: JSON.stringify({ status }),
      }),
    onSuccess: async () => {
      setToast({ msg: "Статус профиля обновлён", kind: "ok" });
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
      await qc.invalidateQueries({ queryKey: ["profiles-health", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const resumeMut = useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<ApiJson>(`/api/adspower/profiles/${encodeURIComponent(profileId)}/resume`, { method: "POST", tenantId }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
      await qc.invalidateQueries({ queryKey: ["profiles-health", tenantId] });
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

  const rows = useMemo(() => ((profilesQ.data?.profiles as ProfileRow[] | undefined) ?? []), [profilesQ.data]);
  const byStatus = (healthQ.data?.by_status as Record<string, number> | undefined) ?? {};

  return (
    <section className="page">
      {toast && <div className={`toast show ${toast.kind === "ok" ? "ok" : "err"}`}>{toast.msg}</div>}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Профилей</div>
          <div className="stat-value cyan">{rows.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Последний sync</div>
          <div className="stat-value" style={{ fontSize: 14 }}>{String(syncStatusQ.data?.last_sync_at || "—")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Ready</div>
          <div className="stat-value green">{byStatus.ready || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Warmup</div>
          <div className="stat-value amber">{byStatus.warmup || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Cooldown</div>
          <div className="stat-value red">{byStatus.cooldown || 0}</div>
        </div>
      </div>
      <div className="card">
        <div className="card-header">
          <span className="card-title">AdsPower Profiles</span>
          <div className="btn-group">
            <button type="button" className="btn btn-cyan" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>Sync Profiles</button>
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
              {rows.map((row) => (
                <tr key={row.adspower_profile_id}>
                  <td>{row.profile_name || "—"}</td>
                  <td className="mono">{row.adspower_profile_id}</td>
                  <td>{row.group_name || "—"}</td>
                  <td>{row.proxy_name || "—"}</td>
                  <td>{row.geo || "—"}</td>
                  <td>
                    <select className="form-input" value={row.status || "new"} onChange={(e) => statusMut.mutate({ profileId: row.adspower_profile_id, status: e.target.value })}>
                      {STATUSES.map((status) => (
                        <option key={status} value={status}>{status}</option>
                      ))}
                    </select>
                  </td>
                  <td>{row.last_sync_at || "—"}</td>
                  <td>{row.last_launch_at || "—"}</td>
                  <td>{row.last_publish_at || "—"}</td>
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
                  <td colSpan={10}><div className="empty-state">Профилей пока нет. Выполните sync из AdsPower.</div></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
