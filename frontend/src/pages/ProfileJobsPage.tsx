import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type Profile = { adspower_profile_id: string; profile_name?: string };
type JobRow = {
  id: number;
  adspower_profile_id: string;
  job_type: string;
  status: string;
  scheduled_at?: string;
  error_type?: string;
  error_message?: string;
  retry_count?: number;
};

export function ProfileJobsPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [jobType, setJobType] = useState("all");
  const [status, setStatus] = useState("all");
  const [profileId, setProfileId] = useState("");
  const [newJob, setNewJob] = useState({
    adspower_profile_id: "",
    job_type: "warmup",
    scheduled_at: "",
    payloadText: "{\n  \"intensity\": \"medium\"\n}",
  });

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(id);
  }, [toast]);

  const profilesQ = useQuery({
    queryKey: ["adspower-profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/adspower/profiles", { tenantId }),
  });

  const jobsQ = useQuery({
    queryKey: ["profile-jobs", tenantId, jobType, status, profileId],
    queryFn: () => {
      const params = new URLSearchParams();
      if (jobType !== "all") params.set("job_type", jobType);
      if (status !== "all") params.set("status", status);
      if (profileId) params.set("adspower_profile_id", profileId);
      return apiFetch<ApiJson>(`/api/adspower/profile-jobs?${params.toString()}`, { tenantId });
    },
    refetchInterval: 5000,
  });

  const createMut = useMutation({
    mutationFn: async () => {
      let payload = {};
      try {
        payload = JSON.parse(newJob.payloadText || "{}");
      } catch {
        throw new Error("Payload должен быть валидным JSON.");
      }
      return apiFetch<ApiJson>("/api/adspower/profile-jobs", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          adspower_profile_id: newJob.adspower_profile_id,
          job_type: newJob.job_type,
          scheduled_at: newJob.scheduled_at || null,
          payload,
          run_now: !newJob.scheduled_at,
        }),
      });
    },
    onSuccess: async () => {
      setToast({ msg: "Profile job создан", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["profile-jobs", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const retryMut = useMutation({
    mutationFn: (id: number) => apiFetch<ApiJson>(`/api/adspower/profile-jobs/${id}/retry`, { method: "POST", tenantId }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["profile-jobs", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => apiFetch<ApiJson>(`/api/adspower/profile-jobs/${id}/cancel`, { method: "POST", tenantId }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["profile-jobs", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const profiles = useMemo(() => ((profilesQ.data?.profiles as Profile[] | undefined) ?? []), [profilesQ.data]);
  const rows = useMemo(() => ((jobsQ.data?.jobs as JobRow[] | undefined) ?? []), [jobsQ.data]);

  useEffect(() => {
    if (!newJob.adspower_profile_id && profiles.length > 0) {
      setNewJob((prev) => ({ ...prev, adspower_profile_id: profiles[0].adspower_profile_id }));
    }
  }, [profiles, newJob.adspower_profile_id]);

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
      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <span className="card-title">Создать Profile Job</span>
          </div>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <select className="form-input" value={newJob.adspower_profile_id} onChange={(e) => setNewJob((prev) => ({ ...prev, adspower_profile_id: e.target.value }))}>
              {profiles.map((profile) => (
                <option key={profile.adspower_profile_id} value={profile.adspower_profile_id}>
                  {profile.profile_name || profile.adspower_profile_id}
                </option>
              ))}
            </select>
            <select className="form-input" value={newJob.job_type} onChange={(e) => setNewJob((prev) => ({ ...prev, job_type: e.target.value }))}>
              <option value="warmup">warmup</option>
              <option value="publish">publish</option>
              <option value="verify">verify</option>
              <option value="stats_sync">stats_sync</option>
            </select>
            <input className="form-input" placeholder="scheduled_at (optional ISO)" value={newJob.scheduled_at} onChange={(e) => setNewJob((prev) => ({ ...prev, scheduled_at: e.target.value }))} />
            <textarea className="form-input mono" rows={8} value={newJob.payloadText} onChange={(e) => setNewJob((prev) => ({ ...prev, payloadText: e.target.value }))} />
            <button type="button" className="action-btn" onClick={() => createMut.mutate()} disabled={createMut.isPending || !newJob.adspower_profile_id}>Create Job</button>
          </div>
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Фильтры</span>
          </div>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <select className="form-input" value={jobType} onChange={(e) => setJobType(e.target.value)}>
              <option value="all">all</option>
              <option value="warmup">warmup</option>
              <option value="publish">publish</option>
              <option value="verify">verify</option>
              <option value="stats_sync">stats_sync</option>
            </select>
            <select className="form-input" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">all</option>
              <option value="pending">pending</option>
              <option value="scheduled">scheduled</option>
              <option value="running">running</option>
              <option value="success">success</option>
              <option value="error">error</option>
              <option value="cancelled">cancelled</option>
              <option value="cooldown">cooldown</option>
            </select>
            <select className="form-input" value={profileId} onChange={(e) => setProfileId(e.target.value)}>
              <option value="">all profiles</option>
              {profiles.map((profile) => (
                <option key={profile.adspower_profile_id} value={profile.adspower_profile_id}>
                  {profile.profile_name || profile.adspower_profile_id}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      <div className="card">
        <div className="card-header">
          <span className="card-title">Profile Jobs</span>
        </div>
        <div className="card-body-flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Profile</th>
                <th>Type</th>
                <th>Status</th>
                <th>Scheduled</th>
                <th>Retry</th>
                <th>Error</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td className="mono">{row.adspower_profile_id}</td>
                  <td>{row.job_type}</td>
                  <td>{row.status}</td>
                  <td>{row.scheduled_at || "—"}</td>
                  <td>{row.retry_count || 0}</td>
                  <td title={row.error_message || ""}>{row.error_type || row.error_message || "—"}</td>
                  <td>
                    <div className="toolbar">
                      <button type="button" className="action-btn" onClick={() => retryMut.mutate(row.id)}>Retry</button>
                      <button type="button" className="action-btn" onClick={() => cancelMut.mutate(row.id)}>Cancel</button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8}><div className="empty-state">По выбранным фильтрам задач нет.</div></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
