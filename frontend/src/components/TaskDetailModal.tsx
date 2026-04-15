import { useEffect, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X, Download, RefreshCw, XCircle, AlertTriangle, CheckCircle } from "lucide-react";
import { apiFetch, downloadTaskMp4, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type FullTask = {
  id: number;
  status?: string;
  original_video?: string;
  unique_video?: string;
  target_profile?: string;
  error_message?: string;
  error_type?: string;
  warning_message?: string;
  render_only?: number;
  subtitle?: string;
  template?: string;
  effects_json?: string;
  scheduled_at?: string;
  priority?: number;
  retry_count?: number;
  device_model?: string;
  geo_profile?: string;
  created_at?: string;
  updated_at?: string;
};

const STATUS_ICON: Record<string, JSX.Element> = {
  success: <CheckCircle size={15} style={{ color: "var(--accent-green, #2ed573)" }} />,
  error: <XCircle size={15} style={{ color: "var(--accent-red, #ff4757)" }} />,
  rendering: <RefreshCw size={15} style={{ color: "var(--accent-cyan, #00d4ff)", animation: "spin 1.2s linear infinite" }} />,
  uploading: <RefreshCw size={15} style={{ color: "var(--accent-cyan, #00d4ff)", animation: "spin 1.2s linear infinite" }} />,
  pending: <AlertTriangle size={15} style={{ color: "var(--accent-amber, #ffa502)" }} />,
};

function statusClass(st?: string) {
  if (st === "success") return "status-active";
  if (st === "error") return "status-banned";
  return "status-frozen";
}

function fileName(p?: string) {
  if (!p) return "—";
  return p.replace(/\\/g, "/").split("/").pop() || p;
}

function fmtDate(s?: string) {
  if (!s) return "—";
  try {
    return new Date(s.endsWith("Z") ? s : s + "Z").toLocaleString("ru-RU", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return s;
  }
}

function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "4px 12px", padding: "5px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
      <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 500, paddingTop: 1 }}>{label}</span>
      <span style={{ fontSize: 12, color: "var(--text-primary)", fontFamily: mono ? "var(--font-mono)" : undefined, wordBreak: "break-all" }}>{value}</span>
    </div>
  );
}

type Props = {
  taskId: number;
  onClose: () => void;
  onToast: (msg: string, kind: "ok" | "err") => void;
};

export function TaskDetailModal({ taskId, onClose, onToast }: Props) {
  const { tenantId } = useTenant();
  const qc = useQueryClient();

  const taskQ = useQuery({
    queryKey: ["task-detail", tenantId, taskId],
    queryFn: () => apiFetch<ApiJson>(`/api/tasks/${taskId}`, { tenantId }),
    staleTime: 5_000,
  });

  const task = taskQ.data?.task as FullTask | undefined;

  const retryMut = useMutation({
    mutationFn: () => apiFetch<ApiJson>(`/api/tasks/${taskId}/retry`, { method: "POST", tenantId }),
    onSuccess: () => {
      onToast("Задача поставлена в очередь повторно", "ok");
      void qc.invalidateQueries({ queryKey: ["dashboard-core", tenantId] });
      void qc.invalidateQueries({ queryKey: ["task-detail", tenantId, taskId] });
    },
    onError: (e: Error) => onToast(e.message, "err"),
  });

  const cancelMut = useMutation({
    mutationFn: () => apiFetch<ApiJson>(`/api/tasks/${taskId}/cancel`, { method: "POST", tenantId }),
    onSuccess: () => {
      onToast("Запрос на отмену отправлен", "ok");
      void qc.invalidateQueries({ queryKey: ["dashboard-core", tenantId] });
      void qc.invalidateQueries({ queryKey: ["task-detail", tenantId, taskId] });
    },
    onError: (e: Error) => onToast(e.message, "err"),
  });

  const handleDownload = useCallback(async () => {
    try {
      await downloadTaskMp4(taskId, tenantId);
    } catch (e) {
      onToast((e as Error).message, "err");
    }
  }, [taskId, tenantId, onToast]);

  // Закрытие по Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  // Блокировка скролла body
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  let effectsList: string[] = [];
  if (task?.effects_json) {
    try {
      const parsed = JSON.parse(task.effects_json) as Record<string, boolean>;
      effectsList = Object.entries(parsed).filter(([, v]) => v).map(([k]) => k);
    } catch { /* ignore */ }
  }

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "rgba(0,0,0,0.72)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: "16px",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Задача #${taskId}`}
        style={{
          background: "var(--bg-secondary, #16213e)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 12,
          width: "100%",
          maxWidth: 640,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.08)", flexShrink: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)" }}>
            Задача #{taskId}
          </span>
          {task?.status && (
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
              {STATUS_ICON[task.status] ?? null}
              <span className={`status-badge ${statusClass(task.status)}`} style={{ fontSize: 11 }}>
                {task.status}
              </span>
            </span>
          )}
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {task?.status === "success" && (
              <button type="button" className="action-btn" style={{ fontSize: 12, padding: "4px 12px", display: "flex", alignItems: "center", gap: 5 }} onClick={() => void handleDownload()}>
                <Download size={13} /> Скачать
              </button>
            )}
            {task?.status === "error" && (
              <button type="button" className="action-btn" style={{ fontSize: 12, padding: "4px 12px", color: "var(--accent-cyan)" }} disabled={retryMut.isPending} onClick={() => retryMut.mutate()}>
                <RefreshCw size={13} style={{ display: "inline", marginRight: 4 }} />
                Повторить
              </button>
            )}
            {(task?.status === "pending" || task?.status === "rendering" || task?.status === "uploading") && (
              <button type="button" className="action-btn" style={{ fontSize: 12, padding: "4px 12px", color: "var(--accent-red)" }} disabled={cancelMut.isPending} onClick={() => cancelMut.mutate()}>
                <XCircle size={13} style={{ display: "inline", marginRight: 4 }} />
                Отменить
              </button>
            )}
            <button type="button" className="action-btn" style={{ padding: "4px 8px" }} onClick={onClose} aria-label="Закрыть">
              <X size={15} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div style={{ overflowY: "auto", padding: "16px 20px", flex: 1 }}>
          {taskQ.isLoading && (
            <div style={{ textAlign: "center", padding: 40, color: "var(--text-muted)", fontSize: 13 }}>
              Загрузка…
            </div>
          )}
          {taskQ.isError && (
            <div style={{ textAlign: "center", padding: 40, color: "var(--accent-red)", fontSize: 13 }}>
              {(taskQ.error as Error).message}
            </div>
          )}
          {task && (
            <>
              {task.error_message && (
                <div style={{
                  padding: "10px 14px", borderRadius: 8, marginBottom: 14,
                  background: "rgba(255,71,87,0.12)", border: "1px solid rgba(255,71,87,0.3)",
                  fontSize: 12, color: "var(--accent-red, #ff4757)", fontFamily: "var(--font-mono)",
                  wordBreak: "break-word", whiteSpace: "pre-wrap",
                }}>
                  {task.error_message}
                </div>
              )}
              {task.warning_message && (
                <div style={{
                  padding: "10px 14px", borderRadius: 8, marginBottom: 14,
                  background: "rgba(255,165,2,0.1)", border: "1px solid rgba(255,165,2,0.25)",
                  fontSize: 12, color: "var(--accent-amber, #ffa502)",
                }}>
                  {task.warning_message}
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column" }}>
                <Row label="Исходное видео" value={fileName(task.original_video)} mono />
                <Row label="Рендер-файл" value={fileName(task.unique_video)} mono />
                <Row label="Профиль" value={task.target_profile || "—"} mono />
                <Row label="Шаблон" value={task.template || "default"} />
                <Row label="Только рендер" value={task.render_only ? "Да" : "Нет"} />
                <Row label="Субтитр" value={task.subtitle || "—"} />
                <Row label="Устройство" value={task.device_model || "—"} />
                <Row label="Гео-профиль" value={task.geo_profile || "—"} />
                <Row label="Приоритет" value={
                  task.priority && task.priority > 0 ? <span style={{ color: "var(--accent-amber)" }}>▲ высокий ({task.priority})</span>
                  : task.priority && task.priority < 0 ? <span style={{ color: "var(--text-tertiary)" }}>▼ низкий ({task.priority})</span>
                  : "обычный (0)"
                } />
                <Row label="Попытки" value={Number(task.retry_count ?? 0) > 0 ? <span style={{ color: "var(--accent-amber)" }}>×{task.retry_count}</span> : "0"} />
                <Row label="По расписанию" value={fmtDate(task.scheduled_at)} />
                <Row label="Создана" value={fmtDate(task.created_at)} />
                <Row label="Обновлена" value={fmtDate(task.updated_at)} />
                {effectsList.length > 0 && (
                  <Row label="Эффекты" value={
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {effectsList.map((ef) => (
                        <span key={ef} style={{ fontSize: 11, padding: "1px 7px", borderRadius: 4, background: "rgba(0,212,255,0.12)", color: "var(--accent-cyan)", fontFamily: "var(--font-mono)" }}>
                          {ef}
                        </span>
                      ))}
                    </div>
                  } />
                )}
                {task.error_type && (
                  <Row label="Тип ошибки" value={<span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{task.error_type}</span>} />
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
