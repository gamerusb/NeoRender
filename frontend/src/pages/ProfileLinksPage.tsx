import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type Profile = { adspower_profile_id: string; profile_name?: string };
type LinkRow = {
  id: number;
  adspower_profile_id: string;
  youtube_channel_id?: string;
  youtube_channel_handle?: string;
  geo?: string;
  offer_name?: string;
  operator_label?: string;
  is_active?: number;
};

export function ProfileLinksPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [form, setForm] = useState({
    adspower_profile_id: "",
    youtube_channel_id: "",
    youtube_channel_handle: "",
    geo: "KR",
    offer_name: "",
    operator_label: "",
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

  const linksQ = useQuery({
    queryKey: ["profile-links", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/adspower/profile-links", { tenantId }),
    refetchInterval: 20_000,
  });

  const createMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/adspower/profile-links", {
        method: "POST",
        tenantId,
        body: JSON.stringify(form),
      }),
    onSuccess: async () => {
      setToast({ msg: "Привязка создана", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["profile-links", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const patchMut = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      apiFetch<ApiJson>(`/api/adspower/profile-links/${id}`, {
        method: "PATCH",
        tenantId,
        body: JSON.stringify({ is_active }),
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["profile-links", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const profiles = useMemo(() => ((profilesQ.data?.profiles as Profile[] | undefined) ?? []), [profilesQ.data]);
  const rows = useMemo(() => ((linksQ.data?.links as LinkRow[] | undefined) ?? []), [linksQ.data]);

  useEffect(() => {
    if (!form.adspower_profile_id && profiles.length > 0) {
      setForm((prev) => ({ ...prev, adspower_profile_id: profiles[0].adspower_profile_id }));
    }
  }, [profiles, form.adspower_profile_id]);

  return (
    <section className="page">
      {toast && <div className={`toast show ${toast.kind === "ok" ? "ok" : "err"}`}>{toast.msg}</div>}
      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <span className="card-title">Новая привязка профиля</span>
          </div>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <select className="form-input" value={form.adspower_profile_id} onChange={(e) => setForm((prev) => ({ ...prev, adspower_profile_id: e.target.value }))}>
              {profiles.map((profile) => (
                <option key={profile.adspower_profile_id} value={profile.adspower_profile_id}>
                  {profile.profile_name || profile.adspower_profile_id}
                </option>
              ))}
            </select>
            <input className="form-input" placeholder="YouTube Channel ID" value={form.youtube_channel_id} onChange={(e) => setForm((prev) => ({ ...prev, youtube_channel_id: e.target.value }))} />
            <input className="form-input" placeholder="@handle" value={form.youtube_channel_handle} onChange={(e) => setForm((prev) => ({ ...prev, youtube_channel_handle: e.target.value }))} />
            <input className="form-input" placeholder="Geo" value={form.geo} onChange={(e) => setForm((prev) => ({ ...prev, geo: e.target.value }))} />
            <input className="form-input" placeholder="Offer" value={form.offer_name} onChange={(e) => setForm((prev) => ({ ...prev, offer_name: e.target.value }))} />
            <input className="form-input" placeholder="Operator Label" value={form.operator_label} onChange={(e) => setForm((prev) => ({ ...prev, operator_label: e.target.value }))} />
            <button type="button" className="action-btn" onClick={() => createMut.mutate()} disabled={createMut.isPending || !form.adspower_profile_id}>Создать Link</button>
          </div>
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Список привязок</span>
          </div>
          <div className="card-body-flush">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Profile</th>
                  <th>Channel ID</th>
                  <th>Handle</th>
                  <th>Geo</th>
                  <th>Offer</th>
                  <th>Operator</th>
                  <th>Active</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.adspower_profile_id}</td>
                    <td>{row.youtube_channel_id || "—"}</td>
                    <td>{row.youtube_channel_handle || "—"}</td>
                    <td>{row.geo || "—"}</td>
                    <td>{row.offer_name || "—"}</td>
                    <td>{row.operator_label || "—"}</td>
                    <td>
                      <input type="checkbox" checked={Boolean(row.is_active)} onChange={(e) => patchMut.mutate({ id: row.id, is_active: e.target.checked })} />
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7}><div className="empty-state">Привязок пока нет.</div></td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
