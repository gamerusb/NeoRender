import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

function formatNumber(n: number) {
  return Number(n || 0).toLocaleString("ru-RU");
}

function escapeHtml(s: string) {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

type AnalyticsRow = {
  id: number;
  video_url?: string;
  views?: number;
  likes?: number;
  status?: string;
  published_at?: string;
};

type AnalyticsAdvice = {
  id?: number;
  diagnosis?: string[];
  next_steps?: string[];
  health_score?: number;
  like_rate?: number;
};

function statusBadgeClass(status?: string) {
  const st = String(status || "").toLowerCase();
  if (st === "active" || st === "ok") return "status-active";
  if (st === "shadowban") return "status-frozen";
  if (st === "banned") return "status-banned";
  return "status-frozen";
}

type SortCol = "id" | "views" | "likes" | "status" | "published_at";

export function AnalyticsPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [checkUrl, setCheckUrl] = useState("");
  const [refreshProgress, setRefreshProgress] = useState<{ done: number; total: number } | null>(null);
  const [sortCol, setSortCol] = useState<SortCol>("id");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("desc"); }
  }

  function sortIcon(col: SortCol) {
    if (col !== sortCol) return <span className="th-sort-icon">↕</span>;
    return <span className="th-sort-icon">{sortDir === "asc" ? "↑" : "↓"}</span>;
  }

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(t);
  }, [toast]);

  const analyticsQ = useQuery({
    queryKey: ["analytics", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/analytics?limit=200", { tenantId }),
    refetchInterval: 30_000,
  });
  const recQ = useQuery({
    queryKey: ["analytics-recommendations", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/analytics/recommendations?limit=200", { tenantId }),
    refetchInterval: 30_000,
  });

  const rows = (analyticsQ.data?.analytics as AnalyticsRow[] | undefined) ?? [];
  const recRows = (recQ.data?.recommendations as AnalyticsAdvice[] | undefined) ?? [];
  const recMap = new Map<number, AnalyticsAdvice>(recRows.map((r) => [Number(r.id || 0), r]));
  const totalViews = rows.reduce((s, r) => s + Number(r.views || 0), 0);
  const totalLikes = rows.reduce((s, r) => s + Number(r.likes || 0), 0);
  const shadow = rows.filter((r) => r.status === "shadowban").length;
  const banned = rows.filter((r) => r.status === "banned").length;
  const active = rows.filter((r) => r.status === "active").length;
  const likeRate = totalViews > 0 ? (totalLikes / totalViews) * 100 : 0;

  const sortedRows = [...rows].sort((a, b) => {
    let av: number | string = 0, bv: number | string = 0;
    if (sortCol === "id") { av = a.id; bv = b.id; }
    else if (sortCol === "views") { av = Number(a.views || 0); bv = Number(b.views || 0); }
    else if (sortCol === "likes") { av = Number(a.likes || 0); bv = Number(b.likes || 0); }
    else if (sortCol === "status") { av = a.status ?? ""; bv = b.status ?? ""; }
    else if (sortCol === "published_at") { av = a.published_at ?? ""; bv = b.published_at ?? ""; }
    if (av < bv) return sortDir === "asc" ? -1 : 1;
    if (av > bv) return sortDir === "asc" ? 1 : -1;
    return 0;
  });

  async function handleRefreshAll() {
    const urls = rows.map((r) => r.video_url).filter(Boolean) as string[];
    if (!urls.length) {
      setToast({ msg: "Нет URL для обновления.", kind: "err" });
      return;
    }
    const BATCH = 20;
    setRefreshProgress({ done: 0, total: urls.length });
    let done = 0;
    for (let i = 0; i < urls.length; i += BATCH) {
      const batch = urls.slice(i, i + BATCH);
      try {
        await apiFetch<ApiJson>("/api/analytics/check-all", {
          method: "POST",
          tenantId,
          body: JSON.stringify({ urls: batch, delay_sec: 1.0 }),
        });
      } catch {
        // продолжаем даже если один батч упал
      }
      done += batch.length;
      setRefreshProgress({ done, total: urls.length });
    }
    setRefreshProgress(null);
    setToast({ msg: `Обновлено ${done} видео.`, kind: "ok" });
    await qc.invalidateQueries({ queryKey: ["analytics", tenantId] });
    await qc.invalidateQueries({ queryKey: ["analytics-recommendations", tenantId] });
  }

  const checkMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/analytics/check", {
        method: "POST",
        tenantId,
        body: JSON.stringify({ url: checkUrl.trim() }),
      }),
    onSuccess: (result) => {
      const st = String(result.status || "");
      const msg =
        st === "active"
          ? `Видео активно. Просмотры: ${formatNumber(Number(result.views || 0))}`
          : st === "shadowban"
            ? "Возможен shadowban."
            : st === "banned"
              ? "Видео недоступно или заблокировано."
              : String(result.message || "Проверка завершена.");
      setToast({ msg, kind: st === "error" ? "err" : "ok" });
      void qc.invalidateQueries({ queryKey: ["analytics", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

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

      <div className="stats-grid-4">
        <div className="stat-card cyan-accent"><div className="stat-label">Всего видео</div><div className="stat-value cyan">{rows.length}</div></div>
        <div className="stat-card cyan-accent"><div className="stat-label">Просмотры</div><div className="stat-value cyan">{formatNumber(totalViews)}</div></div>
        <div className="stat-card green-accent"><div className="stat-label">Like rate</div><div className="stat-value green">{likeRate.toFixed(2)}%</div></div>
        <div className="stat-card red-accent"><div className="stat-label">Риски</div><div className="stat-value red">{shadow + banned}</div><div style={{ fontSize:11,color:"var(--text-tertiary)",marginTop:4 }}>shadowban: {shadow} · бан: {banned}</div></div>
      </div>

      <div className="settings-grid">
        <div>
          <div className="card section-gap">
            <div className="card-header">
              <span className="card-title">Записи аналитики</span>
              <button
                type="button"
                className="btn btn-sm"
                style={{ marginLeft: "auto" }}
                onClick={() => {
                  const a = document.createElement("a");
                  a.href = `/api/analytics/export?tenant_id=${encodeURIComponent(tenantId)}`;
                  a.download = "analytics.csv";
                  a.click();
                }}
                title="Скачать CSV"
              >
                ⬇ CSV
              </button>
            </div>
            <div style={{ padding: "12px 16px 0" }}>
              <div className="toolbar" style={{ marginBottom: 12 }}>
                <input
                  className="form-input mono"
                  placeholder="YouTube / TikTok / Instagram Reels — вставьте ссылку на ролик…"
                  style={{ flex: 1, minWidth: 320 }}
                  value={checkUrl}
                  onChange={(e) => setCheckUrl(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-cyan"
                  disabled={checkMut.isPending}
                  onClick={() => {
                    if (!checkUrl.trim()) {
                      setToast({ msg: "Введите ссылку на ролик (YouTube, TikTok или Instagram).", kind: "err" });
                      return;
                    }
                    checkMut.mutate();
                  }}
                >
                  Проверить ссылку
                </button>
                <button
                  type="button"
                  className="btn btn-cyan"
                  disabled={refreshProgress !== null}
                  onClick={() => void handleRefreshAll()}
                  title="Обновить статистику всех видео из списка"
                >
                  {refreshProgress
                    ? `Обновление ${refreshProgress.done}/${refreshProgress.total}…`
                    : "Обновить все"}
                </button>
              </div>
            </div>
            <div className="card-body-flush">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className={`th-sort${sortCol === "id" ? " active" : ""}`} onClick={() => handleSort("id")}>ID{sortIcon("id")}</th>
                    <th>Ссылка</th>
                    <th className={`th-sort${sortCol === "views" ? " active" : ""}`} onClick={() => handleSort("views")}>Просмотры{sortIcon("views")}</th>
                    <th className={`th-sort${sortCol === "likes" ? " active" : ""}`} onClick={() => handleSort("likes")}>Лайки{sortIcon("likes")}</th>
                    <th className={`th-sort${sortCol === "status" ? " active" : ""}`} onClick={() => handleSort("status")}>Статус{sortIcon("status")}</th>
                    <th className={`th-sort${sortCol === "published_at" ? " active" : ""}`} onClick={() => handleSort("published_at")}>Опубликовано{sortIcon("published_at")}</th>
                    <th>Пост-анализ</th>
                  </tr>
                </thead>
                <tbody>
                  {analyticsQ.isError && (
                    <tr>
                      <td colSpan={7}>
                        <div className="empty-state">{(analyticsQ.error as Error).message}</div>
                      </td>
                    </tr>
                  )}
                  {analyticsQ.isLoading && [1,2,3,4].map((i) => (
                    <tr key={i} className="skeleton-row">
                      <td><div className="skeleton skeleton-cell" style={{ width: 30 }} /></td>
                      <td><div className="skeleton skeleton-cell" style={{ width: 220 }} /></td>
                      <td><div className="skeleton skeleton-cell" style={{ width: 60 }} /></td>
                      <td><div className="skeleton skeleton-cell" style={{ width: 40 }} /></td>
                      <td><div className="skeleton skeleton-cell" style={{ width: 60 }} /></td>
                      <td><div className="skeleton skeleton-cell" style={{ width: 80 }} /></td>
                      <td><div className="skeleton skeleton-cell" style={{ width: 160 }} /></td>
                    </tr>
                  ))}
                  {!analyticsQ.isError && !analyticsQ.isLoading && rows.length === 0 && (
                    <tr>
                      <td colSpan={7}>
                        <div className="empty-state">Пока нет записей аналитики (после успешных заливов появятся URL).</div>
                      </td>
                    </tr>
                  )}
                  {!analyticsQ.isError && !analyticsQ.isLoading &&
                    sortedRows.map((row) => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td className="task-title" title={escapeHtml(row.video_url || "")}>
                          {escapeHtml(row.video_url || "—")}
                        </td>
                        <td className="mono" style={{ color: "var(--accent-cyan)" }}>{formatNumber(Number(row.views || 0))}</td>
                        <td className="mono" style={{ color: "var(--accent-red)" }}>{formatNumber(Number(row.likes || 0))}</td>
                        <td>
                          <span className={`status-badge ${statusBadgeClass(row.status)}`}>{escapeHtml(row.status || "—")}</span>
                        </td>
                        <td className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)", whiteSpace: "nowrap" }}>
                          {row.published_at
                            ? new Date(row.published_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" })
                            : "—"}
                        </td>
                        <td style={{ minWidth: 320 }}>
                          {(() => {
                            const rec = recMap.get(Number(row.id || 0));
                            if (!rec) return <span style={{ color: "var(--text-tertiary)" }}>Сбор рекомендаций…</span>;
                            return (
                              <div style={{ display: "grid", gap: 6, fontSize: 12.5, lineHeight: 1.45 }}>
                                <div>
                                  <span className="mono">score:</span>{" "}
                                  <strong>{Number(rec.health_score || 0)}</strong>{" "}
                                  <span style={{ color: "var(--text-tertiary)" }}>| like-rate: {Number(rec.like_rate || 0).toFixed(2)}%</span>
                                </div>
                                <div style={{ color: "var(--text-secondary)" }}>
                                  {(rec.diagnosis || []).slice(0, 2).join(" ")}
                                </div>
                                <div style={{ color: "var(--text-primary)" }}>
                                  {(rec.next_steps || []).slice(0, 2).map((s, i) => (
                                    <div key={`${row.id}-step-${i}`}>- {s}</div>
                                  ))}
                                </div>
                              </div>
                            );
                          })()}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div>
          <div className="card section-gap">
            <div className="card-header"><span className="card-title">Сводка статусов</span></div>
            <div className="card-body" style={{ fontSize: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <span style={{ color: "var(--text-secondary)" }}>Активные</span>
                <span className="mono" style={{ color: "var(--accent-green)" }}>{active}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <span style={{ color: "var(--text-secondary)" }}>Shadowban</span>
                <span className="mono" style={{ color: "var(--accent-amber)" }}>{shadow}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
                <span style={{ color: "var(--text-secondary)" }}>Бан</span>
                <span className="mono" style={{ color: "var(--accent-red)" }}>{banned}</span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header"><span className="card-title">История действий</span></div>
            <div className="card-body" style={{ fontSize: 12 }}>
              <div style={{ padding: "8px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <span className="mono" style={{ color: "var(--text-tertiary)" }}>
                  {new Date().toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}
                </span>
                {" "}— ручная проверка и обновление статистики
              </div>
              <div style={{ padding: "8px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <span className="mono" style={{ color: "var(--text-tertiary)" }}>авто</span>
                {" "}— рекомендации пересчитываются каждые 30с
              </div>
              <div style={{ padding: "8px 0" }}>
                <span className="mono" style={{ color: "var(--text-tertiary)" }}>экспорт</span>
                {" "}— CSV для внешнего анализа
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
