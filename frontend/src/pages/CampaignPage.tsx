import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type Campaign = {
  id: number;
  name: string;
  niche: string;
  profile_ids: string;
  preset: string;
  template: string;
  effects_json: string;
  proxy_group: string;
  created_at: string;
};

type CampaignStats = {
  total_tasks: number;
  success_tasks: number;
  profile_count: number;
};

function parseJson<T>(str: string, fallback: T): T {
  try {
    return JSON.parse(str) as T;
  } catch {
    return fallback;
  }
}

export function CampaignPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);

  const [form, setForm] = useState({
    name: "",
    niche: "",
    profile_ids: "",
    preset: "",
    template: "",
    proxy_group: "",
  });

  const campaignsQ = useQuery({
    queryKey: ["campaigns", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/campaigns", { tenantId }),
    staleTime: 15_000,
  });

  const createMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/campaigns", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          name: form.name.trim(),
          niche: form.niche.trim(),
          profile_ids: form.profile_ids.split(",").map((s) => s.trim()).filter(Boolean),
          preset: form.preset.trim(),
          template: form.template.trim(),
          proxy_group: form.proxy_group.trim(),
        }),
      }),
    onSuccess: async () => {
      showToast("Кампания создана", "ok");
      setShowForm(false);
      resetForm();
      await qc.invalidateQueries({ queryKey: ["campaigns", tenantId] });
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, unknown> }) =>
      apiFetch<ApiJson>(`/api/campaigns/${id}`, {
        method: "PATCH",
        tenantId,
        body: JSON.stringify(patch),
      }),
    onSuccess: async () => {
      showToast("Кампания обновлена", "ok");
      setEditingId(null);
      resetForm();
      await qc.invalidateQueries({ queryKey: ["campaigns", tenantId] });
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      apiFetch<ApiJson>(`/api/campaigns/${id}`, { method: "DELETE", tenantId }),
    onSuccess: async () => {
      showToast("Кампания удалена", "ok");
      await qc.invalidateQueries({ queryKey: ["campaigns", tenantId] });
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  function showToast(msg: string, kind: "ok" | "err") {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  }

  function resetForm() {
    setForm({ name: "", niche: "", profile_ids: "", preset: "", template: "", proxy_group: "" });
  }

  function startEdit(c: Campaign) {
    const ids = parseJson<string[]>(c.profile_ids, []).join(", ");
    setForm({
      name: c.name,
      niche: c.niche,
      profile_ids: ids,
      preset: c.preset,
      template: c.template,
      proxy_group: c.proxy_group,
    });
    setEditingId(c.id);
    setShowForm(true);
  }

  function handleSubmit() {
    if (!form.name.trim()) {
      showToast("Укажите название кампании", "err");
      return;
    }
    if (editingId != null) {
      updateMut.mutate({
        id: editingId,
        patch: {
          name: form.name.trim(),
          niche: form.niche.trim(),
          profile_ids: form.profile_ids.split(",").map((s) => s.trim()).filter(Boolean),
          preset: form.preset.trim(),
          template: form.template.trim(),
          proxy_group: form.proxy_group.trim(),
        },
      });
    } else {
      createMut.mutate();
    }
  }

  const campaigns = (campaignsQ.data?.campaigns as Campaign[] | undefined) ?? [];

  return (
    <div className="page">
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)} aria-label="Закрыть">✕</button>
          </div>
        </div>
      )}

      <div className="settings-grid">
        {/* Left: campaign list */}
        <div>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Кампании</span>
              <button
                type="button"
                className="btn btn-sm btn-cyan"
                style={{ marginLeft: "auto" }}
                onClick={() => {
                  resetForm();
                  setEditingId(null);
                  setShowForm(true);
                }}
              >
                + Создать
              </button>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              {campaignsQ.isLoading ? (
                <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
                  Загрузка…
                </div>
              ) : campaigns.length === 0 ? (
                <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
                  Кампаний пока нет. Создайте первую.
                </div>
              ) : (
                campaigns.map((c) => (
                  <CampaignCard
                    key={c.id}
                    campaign={c}
                    tenantId={tenantId}
                    onEdit={() => startEdit(c)}
                    onDelete={() => {
                      if (window.confirm(`Удалить кампанию «${c.name}»?`)) {
                        deleteMut.mutate(c.id);
                      }
                    }}
                    isDeleting={deleteMut.isPending}
                  />
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right: create/edit form */}
        <div>
          {showForm && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">{editingId != null ? "Редактировать кампанию" : "Новая кампания"}</span>
                <button
                  type="button"
                  style={{ marginLeft: "auto", background: "none", border: "none", color: "var(--text-tertiary)", cursor: "pointer", fontSize: 16 }}
                  onClick={() => { setShowForm(false); resetForm(); setEditingId(null); }}
                >
                  ✕
                </button>
              </div>
              <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div className="form-group">
                  <label className="form-label">Название кампании *</label>
                  <input
                    className="form-input"
                    placeholder="Корейские казино Shorts"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Ниша</label>
                  <input
                    className="form-input"
                    placeholder="korean casino shorts"
                    value={form.niche}
                    onChange={(e) => setForm((f) => ({ ...f, niche: e.target.value }))}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Профили AdsPower</label>
                  <input
                    className="form-input mono"
                    placeholder="KR_shorts_01, KR_shorts_02"
                    value={form.profile_ids}
                    onChange={(e) => setForm((f) => ({ ...f, profile_ids: e.target.value }))}
                  />
                  <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
                    Через запятую. ID профилей из AdsPower.
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Пресет уникализации</label>
                  <input
                    className="form-input"
                    placeholder="aggressive / balanced / subtle"
                    value={form.preset}
                    onChange={(e) => setForm((f) => ({ ...f, preset: e.target.value }))}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Шаблон заголовка</label>
                  <input
                    className="form-input"
                    placeholder="{{title}} #shorts #korea"
                    value={form.template}
                    onChange={(e) => setForm((f) => ({ ...f, template: e.target.value }))}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Прокси-группа</label>
                  <input
                    className="form-input mono"
                    placeholder="kr_proxies"
                    value={form.proxy_group}
                    onChange={(e) => setForm((f) => ({ ...f, proxy_group: e.target.value }))}
                  />
                </div>

                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-cyan"
                    style={{ flex: 1 }}
                    disabled={createMut.isPending || updateMut.isPending}
                    onClick={handleSubmit}
                  >
                    {createMut.isPending || updateMut.isPending
                      ? "Сохранение…"
                      : editingId != null
                      ? "Сохранить изменения"
                      : "Создать кампанию"}
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => { setShowForm(false); resetForm(); setEditingId(null); }}
                  >
                    Отмена
                  </button>
                </div>
              </div>
            </div>
          )}

          {!showForm && campaigns.length > 0 && (
            <div className="card">
              <div className="card-header"><span className="card-title">Сводка</span></div>
              <div className="card-body" style={{ fontSize: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                  <span style={{ color: "var(--text-secondary)" }}>Всего кампаний</span>
                  <span className="mono" style={{ color: "var(--accent-cyan)" }}>{campaigns.length}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                  <span style={{ color: "var(--text-secondary)" }}>С профилями</span>
                  <span className="mono">{campaigns.filter((c) => parseJson<string[]>(c.profile_ids, []).length > 0).length}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
                  <span style={{ color: "var(--text-secondary)" }}>С нишей</span>
                  <span className="mono">{campaigns.filter((c) => c.niche?.trim()).length}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CampaignCard({
  campaign,
  tenantId,
  onEdit,
  onDelete,
  isDeleting,
}: {
  campaign: Campaign;
  tenantId: string;
  onEdit: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const statsQ = useQuery({
    queryKey: ["campaign-stats", campaign.id, tenantId],
    queryFn: () => apiFetch<ApiJson>(`/api/campaigns/${campaign.id}/stats`, { tenantId }),
    staleTime: 30_000,
  });
  const stats = statsQ.data?.stats as CampaignStats | undefined;
  const profileIds = parseJson<string[]>(campaign.profile_ids, []);

  return (
    <div
      style={{
        padding: "14px 16px",
        borderBottom: "1px solid var(--border-subtle)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            background: "rgba(94,234,212,0.1)",
            border: "1px solid rgba(94,234,212,0.2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            fontSize: 16,
          }}
        >
          
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {campaign.name}
          </div>
          {campaign.niche && (
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
              Ниша: {campaign.niche}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button type="button" className="action-btn" onClick={onEdit} style={{ fontSize: 11 }}>
            Редактировать
          </button>
          <button type="button" className="action-btn" onClick={onDelete} disabled={isDeleting} style={{ fontSize: 11, color: "var(--accent-red)" }}>
            Удалить
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--text-tertiary)", paddingLeft: 48 }}>
        <span>
          <span className="mono" style={{ color: "var(--text-secondary)" }}>{profileIds.length}</span> профилей
        </span>
        {stats && (
          <>
            <span>
              <span className="mono" style={{ color: "var(--accent-cyan)" }}>{stats.total_tasks}</span> задач
            </span>
            <span>
              <span className="mono" style={{ color: "var(--accent-green)" }}>{stats.success_tasks}</span> успешно
            </span>
          </>
        )}
        {campaign.proxy_group && (
          <span>прокси: <span style={{ color: "var(--text-secondary)" }}>{campaign.proxy_group}</span></span>
        )}
        {campaign.preset && (
          <span>пресет: <span style={{ color: "var(--text-secondary)" }}>{campaign.preset}</span></span>
        )}
      </div>
    </div>
  );
}
