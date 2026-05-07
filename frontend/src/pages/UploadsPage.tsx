import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, apiUrl, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type TaskRow = {
  id: number;
  original_video?: string;
  target_profile?: string;
  status?: string;
  error_message?: string;
  hash?: string;
  video_url?: string;
  created_at?: string;
};

type Screenshot = {
  filename: string;
  url: string;
  task_id?: number;
  created_at?: string;
};

type Profile = { adspower_profile_id: string; profile_name?: string };

function taskBadgeClass(st?: string) {
  if (st === "success") return "status-active";
  if (st === "error") return "status-banned";
  if (st === "rendering" || st === "uploading") return "status-shadow";
  if (st === "pending") return "status-frozen";
  return "status-frozen";
}

function statusLabel(st?: string) {
  if (st === "rendering") return "Рендер";
  if (st === "uploading") return "Залив";
  if (st === "pending") return "Ожидает";
  if (st === "success") return "Готово";
  if (st === "error") return "Ошибка";
  return st || "—";
}

type TabKey = "all" | "active" | "history";

export function UploadsPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [tab, setTab] = useState<TabKey>("all");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [publishTaskId, setPublishTaskId] = useState<number | null>(null);
  const [publishProfileId, setPublishProfileId] = useState("");
  const [publishTitle, setPublishTitle] = useState("");
  const [publishDescription, setPublishDescription] = useState("");
  const [publishTags, setPublishTags] = useState("");
  const [publishComment, setPublishComment] = useState("");
  const [publishBusy, setPublishBusy] = useState(false);

  const tasksQ = useQuery({
    queryKey: ["tasks", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=200", { tenantId }),
    refetchInterval: 5000,
  });

  const screenshotsQ = useQuery({
    queryKey: ["screenshots", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/screenshots", { tenantId }),
    staleTime: 30_000,
  });

  const profilesQ = useQuery({
    queryKey: ["adspower-profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/adspower/profiles", { tenantId }),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 3800);
    return () => window.clearTimeout(id);
  }, [toast]);

  const startMut = useMutation({
    mutationFn: () => apiFetch("/api/pipeline/start", { method: "POST", tenantId }),
    onSuccess: () => setToast({ msg: "Пайплайн запущен", kind: "ok" }),
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const enqueuePendingMut = useMutation({
    mutationFn: () => apiFetch("/api/pipeline/enqueue-pending", { method: "POST", tenantId }),
    onSuccess: async () => {
      setToast({ msg: "Pending задачи поставлены в очередь", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const cancelMut = useMutation({
    mutationFn: (taskId: number) => apiFetch(`/api/tasks/${taskId}/cancel`, { method: "POST", tenantId }),
    onSuccess: async (d: ApiJson) => {
      setToast({ msg: String(d.message || "Задача отменена"), kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const retryMut = useMutation({
    mutationFn: (taskId: number) => apiFetch(`/api/tasks/${taskId}/retry`, { method: "POST", tenantId }),
    onSuccess: async (d: ApiJson) => {
      setToast({ msg: String(d.message || "Задача перезапущена"), kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const publishMut = useMutation({
    mutationFn: (payload: {
      task_id: number;
      adspower_profile_id: string;
      title: string;
      description: string;
      comment: string;
      tags: string[];
      run_now: boolean;
    }) =>
      apiFetch<ApiJson>("/api/publish/jobs", {
        method: "POST",
        tenantId,
        body: JSON.stringify(payload),
      }),
    onSuccess: async () => {
      setToast({ msg: "Publish job создан и отправлен в работу", kind: "ok" });
      setPublishTaskId(null);
      await qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const allRows = useMemo(
    () => ((tasksQ.data?.tasks as TaskRow[] | undefined) ?? []).slice().reverse(),
    [tasksQ.data]
  );

  const profiles = useMemo(
    () => ((profilesQ.data?.profiles as Profile[] | undefined) ?? []),
    [profilesQ.data]
  );

  const screenshots = useMemo(
    () => (screenshotsQ.data?.screenshots as Screenshot[] | undefined) ?? [],
    [screenshotsQ.data]
  );

  const screenshotByTask = useMemo(() => {
    const map = new Map<number, Screenshot>();
    for (const s of screenshots) {
      if (s.task_id != null) map.set(s.task_id, s);
    }
    return map;
  }, [screenshots]);

  const filtered = useMemo(() => {
    let r = allRows;
    if (tab === "active") r = r.filter((t) => t.status === "rendering" || t.status === "uploading" || t.status === "pending");
    if (tab === "history") r = r.filter((t) => t.status === "success" || t.status === "error");
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      r = r.filter(
        (t) =>
          String(t.original_video || "").toLowerCase().includes(q) ||
          String(t.target_profile || "").toLowerCase().includes(q)
      );
    }
    return r;
  }, [allRows, tab, search]);

  const successCount = allRows.filter((r) => r.status === "success").length;
  const errorCount = allRows.filter((r) => r.status === "error").length;
  const activeCount = allRows.filter((r) => r.status === "rendering" || r.status === "uploading").length;
  const pendingCount = allRows.filter((r) => r.status === "pending").length;

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "all", label: "Все", count: allRows.length },
    { key: "active", label: "Активные", count: activeCount + pendingCount },
    { key: "history", label: "История", count: successCount + errorCount },
  ];

  useEffect(() => {
    if (!publishProfileId && profiles.length > 0) {
      setPublishProfileId(profiles[0].adspower_profile_id);
    }
  }, [profiles, publishProfileId]);

  function extractTagsFromText(text: string): string[] {
    const matches = text.match(/#[\p{L}\p{N}_-]+/gu) || [];
    const clean = matches
      .map((m) => m.replace(/^#+/, "").trim())
      .filter(Boolean);
    return Array.from(new Set(clean)).slice(0, 30);
  }

  async function openOneClickPublish(row: TaskRow) {
    if (!profiles.length) {
      setToast({ msg: "Сначала подключите AdsPower профиль в разделе Profiles.", kind: "err" });
      return;
    }
    setPublishTaskId(row.id);
    setPublishTitle("");
    setPublishDescription("");
    setPublishTags("");
    setPublishComment("");
    setPublishBusy(true);
    try {
      const fileName = (row.original_video || "").split(/[/\\]/).pop() || "YouTube Shorts";
      const niche = fileName.replace(/\.[a-z0-9]+$/i, "").slice(0, 80) || "YouTube Shorts";
      const ai = await apiFetch<ApiJson>("/api/ai/preview", {
        method: "POST",
        tenantId,
        body: JSON.stringify({ niche, hook_pattern: "auto", n_variants: 3 }),
      });
      const generatedTitle = String(ai.title || "").trim();
      const generatedDescription = String(ai.description || "").trim();
      const generatedComment = String(ai.comment || "").trim();
      setPublishTitle(generatedTitle);
      setPublishDescription(generatedDescription);
      setPublishComment(generatedComment);
      setPublishTags(extractTagsFromText(generatedDescription).join(", "));
    } catch {
      setToast({ msg: "Не удалось сгенерировать метаданные, заполните поля вручную.", kind: "err" });
    } finally {
      setPublishBusy(false);
    }
  }

  function submitOneClickPublish() {
    if (!publishTaskId) return;
    if (!publishProfileId) {
      setToast({ msg: "Выберите профиль для публикации.", kind: "err" });
      return;
    }
    const tags = publishTags
      .split(/[,\s]+/)
      .map((t) => t.trim().replace(/^#+/, ""))
      .filter(Boolean)
      .slice(0, 30);
    publishMut.mutate({
      task_id: publishTaskId,
      adspower_profile_id: publishProfileId,
      title: publishTitle.trim(),
      description: publishDescription.trim(),
      comment: publishComment.trim(),
      tags,
      run_now: true,
    });
  }

  return (
    <section className="page uploads-page">
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)} aria-label="Закрыть">✕</button>
          </div>
        </div>
      )}

      <div className="stats-grid-4" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">Всего задач</div>
          <div className="stat-value cyan">{allRows.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">В обработке</div>
          <div className="stat-value">{activeCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Успешно</div>
          <div className="stat-value green">{successCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Ошибки</div>
          <div className="stat-value red">{errorCount}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">История заливов</span>
          <div className="btn-group" style={{ marginLeft: "auto" }}>
            <button type="button" className="btn btn-sm" onClick={() => startMut.mutate()} disabled={startMut.isPending}>
              ▶ Запустить
            </button>
            <button type="button" className="btn btn-sm" onClick={() => enqueuePendingMut.mutate()} disabled={enqueuePendingMut.isPending}>
              Enqueue pending
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border-default)", padding: "0 16px" }}>
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              style={{
                background: "none",
                border: "none",
                borderBottom: tab === t.key ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: tab === t.key ? "var(--text-primary)" : "var(--text-tertiary)",
                padding: "10px 14px",
                fontSize: 13,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                marginBottom: -1,
                transition: "color 0.15s",
              }}
            >
              {t.label}
              {t.count != null && t.count > 0 && (
                <span
                  style={{
                    background: tab === t.key ? "var(--accent-cyan)" : "var(--border-default)",
                    color: tab === t.key ? "#000" : "var(--text-secondary)",
                    borderRadius: 10,
                    padding: "1px 6px",
                    fontSize: 11,
                    fontWeight: 600,
                  }}
                >
                  {t.count}
                </span>
              )}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <input
            className="form-input"
            placeholder="Поиск..."
            style={{ maxWidth: 220, padding: "5px 10px", fontSize: 12, margin: "6px 0" }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="card-body-flush">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>ID</th>
                <th>Файл</th>
                <th>Профиль</th>
                <th>Hash</th>
                <th>Статус</th>
                <th>Скрин</th>
                <th>Ссылка</th>
                <th style={{ width: 140 }}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const busy = row.status === "rendering" || row.status === "uploading";
                const isPending = row.status === "pending";
                const done = row.status === "success";
                const failed = row.status === "error";
                const screenshot = screenshotByTask.get(row.id);
                const isExpanded = expandedId === row.id;
                return [
                  <tr key={row.id} style={{ cursor: done ? "pointer" : undefined }} onClick={done ? () => setExpandedId(isExpanded ? null : row.id) : undefined}>
                    <td className="mono" style={{ color: "var(--text-tertiary)" }}>{row.id}</td>
                    <td className="task-title" title={row.original_video || ""}>
                      {(row.original_video || "—").split(/[/\\]/).pop() || "—"}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>{row.target_profile || "—"}</td>
                    <td
                      className="mono"
                      style={{ fontSize: 10, color: "var(--text-tertiary)", maxWidth: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      title={row.hash || ""}
                    >
                      {row.hash ? row.hash.slice(0, 12) + "…" : "—"}
                    </td>
                    <td>
                      <span className={`status-badge ${taskBadgeClass(row.status)}`}>
                        {statusLabel(row.status)}
                      </span>
                    </td>
                    <td>
                      {screenshot ? (
                        <a href={apiUrl(`/api/screenshots/${screenshot.filename}`)} target="_blank" rel="noreferrer" style={{ color: "var(--accent-cyan)", fontSize: 11 }}>
                          Скрин
                        </a>
                      ) : (
                        <span style={{ color: "var(--text-tertiary)", fontSize: 11 }}>—</span>
                      )}
                    </td>
                    <td>
                      {row.video_url ? (
                        <a href={row.video_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-cyan)", fontSize: 11, maxWidth: 80, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          YouTube ↗
                        </a>
                      ) : (
                        <span style={{ color: "var(--text-tertiary)", fontSize: 11 }}>—</span>
                      )}
                    </td>
                    <td>
                      <div className="toolbar" style={{ gap: 4 }}>
                        {(busy || isPending) && (
                          <button type="button" className="action-btn" disabled={cancelMut.isPending} onClick={(e) => { e.stopPropagation(); cancelMut.mutate(row.id); }}>
                            Отмена
                          </button>
                        )}
                        {failed && (
                          <button type="button" className="action-btn" disabled={retryMut.isPending} onClick={(e) => { e.stopPropagation(); retryMut.mutate(row.id); }}>
                            Повторить
                          </button>
                        )}
                        {done && (
                          <>
                            <button type="button" className="action-btn" onClick={(e) => { e.stopPropagation(); void openOneClickPublish(row); }}>
                              One-click publish
                            </button>
                            <button type="button" className="action-btn" onClick={(e) => { e.stopPropagation(); window.open(apiUrl(`/api/tasks/${row.id}/download`), "_blank"); }}>
                              Скачать
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>,
                  isExpanded && (
                    <tr key={`exp-${row.id}`} style={{ background: "rgba(94,234,212,0.03)" }}>
                      <td colSpan={8} style={{ padding: "12px 16px" }}>
                        <MetricsPanel taskId={row.id} videoUrl={row.video_url} tenantId={tenantId} />
                      </td>
                    </tr>
                  ),
                ];
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="empty-state">
                      {allRows.length === 0 ? "Задач пока нет" : "Нет задач по фильтру"}
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {publishTaskId != null && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-header">
            <span className="card-title">One-click publish · task #{publishTaskId}</span>
            <button type="button" className="btn btn-sm" onClick={() => setPublishTaskId(null)} style={{ marginLeft: "auto" }}>
              Закрыть
            </button>
          </div>
          <div className="card-body" style={{ display: "grid", gap: 10 }}>
            <select className="form-input" value={publishProfileId} onChange={(e) => setPublishProfileId(e.target.value)} disabled={publishBusy || publishMut.isPending}>
              {profiles.map((p) => (
                <option key={p.adspower_profile_id} value={p.adspower_profile_id}>
                  {p.profile_name || p.adspower_profile_id}
                </option>
              ))}
            </select>
            <input
              className="form-input"
              placeholder="Title"
              value={publishTitle}
              onChange={(e) => setPublishTitle(e.target.value)}
              disabled={publishBusy || publishMut.isPending}
            />
            <textarea
              className="form-input"
              rows={3}
              placeholder="Description"
              value={publishDescription}
              onChange={(e) => setPublishDescription(e.target.value)}
              disabled={publishBusy || publishMut.isPending}
            />
            <input
              className="form-input"
              placeholder="Tags: comma or space separated"
              value={publishTags}
              onChange={(e) => setPublishTags(e.target.value)}
              disabled={publishBusy || publishMut.isPending}
            />
            <input
              className="form-input"
              placeholder="Pinned comment (optional)"
              value={publishComment}
              onChange={(e) => setPublishComment(e.target.value)}
              disabled={publishBusy || publishMut.isPending}
            />
            <div className="btn-group">
              <button
                type="button"
                className="btn btn-sm"
                onClick={submitOneClickPublish}
                disabled={publishBusy || publishMut.isPending || !publishProfileId}
              >
                {publishBusy ? "Генерация..." : publishMut.isPending ? "Создание job..." : "Создать publish job"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function MetricsPanel({ taskId, videoUrl, tenantId }: { taskId: number; videoUrl?: string; tenantId: string }) {
  const checkQ = useQuery({
    queryKey: ["task-metrics", taskId, tenantId],
    queryFn: () =>
      videoUrl
        ? apiFetch<ApiJson>(`/api/analytics/check?url=${encodeURIComponent(videoUrl)}`, { tenantId })
        : Promise.resolve(null),
    enabled: Boolean(videoUrl),
    staleTime: 60_000,
  });

  const data = checkQ.data;

  return (
    <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
      <div>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>Метрики (live)</div>
        {checkQ.isLoading && <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>Загрузка…</span>}
        {!videoUrl && <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>Ссылка на YouTube не указана</span>}
        {data && (
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {[
              { label: "Просмотры", value: data.views },
              { label: "Лайки", value: data.likes },
              { label: "Комм.", value: data.comments },
              { label: "Статус", value: data.status },
            ].map((m) => (
              <div key={m.label} style={{ minWidth: 70 }}>
                <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{m.label}</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                  {m.value != null ? String(m.value) : "—"}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {videoUrl && (
        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>Временные метки</div>
          <div style={{ display: "flex", gap: 8 }}>
            {["1ч", "6ч", "24ч"].map((label) => (
              <div key={label} style={{ padding: "4px 10px", border: "1px solid var(--border-default)", borderRadius: 6, fontSize: 11, color: "var(--text-tertiary)" }}>
                {label}: <span style={{ color: "var(--text-secondary)" }}>—</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
