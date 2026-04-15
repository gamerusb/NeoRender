import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type TaskRow = {
  id: number;
  original_video?: string;
  target_profile?: string;
  status?: string;
  error_message?: string;
  hash?: string;
  created_at?: string;
  priority?: number;
};

function statusBadgeClass(st?: string) {
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

function shortName(path?: string) {
  if (!path) return "—";
  return path.split(/[/\\]/).pop() || path;
}

type TabKey = "active" | "pending" | "done" | "all";

export function QueuePage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabKey>("active");

  const tasksQ = useQuery({
    queryKey: ["queue-tasks", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=200", { tenantId }),
    refetchInterval: 3000,
    staleTime: 2000,
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/tasks/${id}/cancel`, { method: "POST", tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["queue-tasks", tenantId] }),
  });

  const priorityMut = useMutation({
    mutationFn: ({ id, priority }: { id: number; priority: number }) =>
      apiFetch(`/api/tasks/${id}/priority`, {
        method: "POST",
        tenantId,
        body: JSON.stringify({ priority }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["queue-tasks", tenantId] }),
  });

  const stopMut = useMutation({
    mutationFn: () => apiFetch("/api/pipeline/stop", { method: "POST", tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["queue-tasks", tenantId] }),
  });

  const startMut = useMutation({
    mutationFn: () => apiFetch("/api/pipeline/start", { method: "POST", tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["queue-tasks", tenantId] }),
  });

  const allRows = useMemo(
    () => ((tasksQ.data?.tasks as TaskRow[] | undefined) ?? []).slice().reverse(),
    [tasksQ.data]
  );

  const activeRows = allRows.filter(
    (r) => r.status === "rendering" || r.status === "uploading"
  );
  const pendingRows = allRows.filter((r) => r.status === "pending");
  const doneRows = allRows.filter(
    (r) => r.status === "success" || r.status === "error"
  );

  const displayRows: TaskRow[] =
    tab === "active"
      ? activeRows
      : tab === "pending"
      ? pendingRows
      : tab === "done"
      ? doneRows
      : allRows;

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "active", label: "Активные", count: activeRows.length },
    { key: "pending", label: "Ожидают", count: pendingRows.length },
    { key: "done", label: "Завершённые", count: doneRows.length },
    { key: "all", label: "Все", count: allRows.length },
  ];

  return (
    <div className="page">
      {/* Stats */}
      <div className="stats-grid-4" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">Активных</div>
          <div className="stat-value cyan">{activeRows.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">В очереди</div>
          <div className="stat-value">{pendingRows.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Завершено</div>
          <div className="stat-value green">{doneRows.filter((r) => r.status === "success").length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Ошибок</div>
          <div className="stat-value red">{doneRows.filter((r) => r.status === "error").length}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header" style={{ gap: 12 }}>
          <span className="card-title">Очередь задач</span>
          <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            <button
              type="button"
              className="btn btn-sm"
              disabled={startMut.isPending}
              onClick={() => startMut.mutate()}
              title="Запустить конвейер"
            >
              ▶ Запустить
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={stopMut.isPending}
              onClick={() => stopMut.mutate()}
              title="Остановить конвейер"
            >
              ⏸ Пауза
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
              {t.count > 0 && (
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
        </div>

        <div className="card-body-flush">
          {tasksQ.isLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--text-tertiary)" }}>
              Загрузка…
            </div>
          ) : displayRows.length === 0 ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
              {tab === "active" ? "Нет активных задач" : tab === "pending" ? "Очередь пуста" : "Нет завершённых задач"}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 48 }}>ID</th>
                  <th>Файл</th>
                  <th>Профиль</th>
                  <th>Статус</th>
                  <th>Hash</th>
                  <th style={{ width: 140 }}>Действия</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((row) => {
                  const isActive = row.status === "rendering" || row.status === "uploading";
                  const isPending = row.status === "pending";
                  return (
                    <tr key={row.id}>
                      <td className="mono" style={{ color: "var(--text-tertiary)" }}>
                        {row.id}
                      </td>
                      <td style={{ maxWidth: 220 }}>
                        <div
                          style={{
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            fontSize: 12,
                          }}
                          title={row.original_video || ""}
                        >
                          {shortName(row.original_video)}
                        </div>
                      </td>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {row.target_profile || "—"}
                      </td>
                      <td>
                        <span className={`status-badge ${statusBadgeClass(row.status)}`}>
                          {statusLabel(row.status)}
                        </span>
                      </td>
                      <td
                        className="mono"
                        style={{
                          fontSize: 10,
                          color: "var(--text-tertiary)",
                          maxWidth: 80,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={row.hash || ""}
                      >
                        {row.hash ? row.hash.slice(0, 10) + "…" : "—"}
                      </td>
                      <td>
                        <div className="toolbar" style={{ gap: 4 }}>
                          {(isActive || isPending) && (
                            <button
                              type="button"
                              className="action-btn"
                              disabled={cancelMut.isPending}
                              onClick={() => cancelMut.mutate(row.id)}
                              title="Отменить"
                            >
                              Отмена
                            </button>
                          )}
                          {isPending && (
                            <button
                              type="button"
                              className="btn btn-sm"
                              disabled={priorityMut.isPending}
                              onClick={() => priorityMut.mutate({ id: row.id, priority: (row.priority ?? 0) + 1 })}
                              title="Повысить приоритет"
                            >
                              ↑ Приоритет
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
