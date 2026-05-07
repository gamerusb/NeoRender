import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import {
  Activity,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Heart,
  History,
  Play,
  Search,
  ThumbsUp,
  UserCheck,
  X,
  Zap,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────────────

type Profile = { user_id: string; name: string };

type WarmupStats = {
  videos_watched?: number;
  shorts_watched?: number;
  searches_done?: number;
  likes_given?: number;
  subscriptions?: number;
  logged_in?: number;
};

type JobStatus =
  | "running"
  | "cancelling"
  | "cancelled"
  | "ok"
  | "success"
  | "error";

type WarmupJob = {
  job_id: string;
  status: JobStatus;
  profile_id: string;
  intensity: string;
  stats: WarmupStats;
  actions_log: string[];
  message?: string | null;
  started_at: number;
  finished_at?: number | null;
};

type HistoryRow = {
  id: number;
  profile_id: string;
  intensity: string;
  status: string;
  logged_in: number;
  videos_watched: number;
  shorts_watched: number;
  searches_done: number;
  likes_given: number;
  subscriptions: number;
  comments_left: number;
  actions_count: number;
  warnings_count: number;
  error_message?: string | null;
  started_at: string;
  finished_at?: string | null;
};

type IntensityOption = { key: string; label: string; desc: string };

// ── Вспомогалки ─────────────────────────────────────────────────────────────

function elapsedLabel(startedAt: number, finishedAt?: number | null): string {
  const end = finishedAt ? finishedAt * 1000 : Date.now();
  const sec = Math.round((end - startedAt * 1000) / 1000);
  if (sec < 60) return `${sec} сек`;
  return `${Math.floor(sec / 60)} мин ${sec % 60} сек`;
}

function isTerminal(s: JobStatus): boolean {
  return s === "ok" || s === "success" || s === "error" || s === "cancelled";
}

function statusBadge(s: string) {
  const map: Record<string, [string, string]> = {
    ok:         ["#2ed573", "rgba(46,213,115,0.12)"],
    success:    ["#2ed573", "rgba(46,213,115,0.12)"],
    error:      ["#ff4757", "rgba(255,71,87,0.12)"],
    cancelled:  ["#a8b2c8", "rgba(168,178,200,0.12)"],
    cancelling: ["#ffa502", "rgba(255,165,2,0.12)"],
    running:    ["#00d4ff", "rgba(0,212,255,0.12)"],
  };
  const [color, bg] = map[s] ?? ["#a8b2c8", "rgba(168,178,200,0.12)"];
  return (
    <span
      style={{
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 4,
        background: bg,
        color,
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
      }}
    >
      {s}
    </span>
  );
}

function KeywordTag({
  value,
  onRemove,
}: {
  value: string;
  onRemove: () => void;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 4,
        background: "rgba(0,212,255,0.12)",
        border: "1px solid rgba(0,212,255,0.25)",
        fontSize: 12,
        color: "var(--accent-cyan)",
        fontFamily: "var(--font-mono)",
      }}
    >
      {value}
      <button
        type="button"
        onClick={onRemove}
        style={{
          background: "none",
          border: "none",
          color: "var(--accent-cyan)",
          cursor: "pointer",
          padding: "0 1px",
          fontSize: 13,
          lineHeight: 1,
        }}
        aria-label={`Удалить ${value}`}
      >
        ×
      </button>
    </span>
  );
}

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 100,
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: 10,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
        transition: "all 0.16s",
      }}
    >
      <div style={{ color: color ?? "var(--accent-cyan)", display: "flex", alignItems: "center", gap: 6 }}>
        {icon}
        <span style={{ fontSize: 10.5, color: "var(--text-tertiary)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px" }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", fontFamily: "var(--font-mono)", letterSpacing: "-0.5px" }}>{value}</div>
    </div>
  );
}

// ── Основной компонент ───────────────────────────────────────────────────────

export function WarmupPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();

  const [tab, setTab] = useState<"run" | "history">("run");
  const [selectedProfile, setSelectedProfile] = useState("");
  const [intensity, setIntensity] = useState("medium");
  const [shortsRetentionMode, setShortsRetentionMode] = useState("mixed");
  const [kwInput, setKwInput] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [tick, setTick] = useState(0); // для перерисовки таймера
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Тост авто-скрытие
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

  // Профили
  const profilesQ = useQuery({
    queryKey: ["profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/profiles", { tenantId }),
    staleTime: 30_000,
  });
  const profiles = useMemo(
    () => ((profilesQ.data?.profiles as Profile[] | undefined) ?? []),
    [profilesQ.data],
  );

  // Уровни интенсивности
  const intensitiesQ = useQuery({
    queryKey: ["warmup-intensities"],
    queryFn: () => apiFetch<ApiJson>("/api/warmup/intensities"),
    staleTime: Infinity,
  });
  const intensities: IntensityOption[] = useMemo(
    () => ((intensitiesQ.data?.intensities as IntensityOption[] | undefined) ?? []),
    [intensitiesQ.data],
  );

  // Опрос статуса задачи
  const jobQ = useQuery({
    queryKey: ["warmup-job", jobId, tenantId],
    queryFn: () =>
      apiFetch<ApiJson>(`/api/warmup/status/${jobId}`, { tenantId }),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const data = query.state.data as ApiJson | undefined;
      const status = data?.status as JobStatus | undefined;
      if (!status || !isTerminal(status)) return 3000;
      return false;
    },
    staleTime: 0,
  });
  const job = jobId !== null ? (jobQ.data as unknown as WarmupJob | null) : null;
  const isRunning = job !== null && !isTerminal(job.status as JobStatus);

  // Секундный тик только пока задача идёт
  useEffect(() => {
    if (isRunning) {
      tickRef.current = setInterval(() => setTick((t) => t + 1), 1000);
    } else {
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    }
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [isRunning]);

  // Тост при завершении
  useEffect(() => {
    if (!job) return;
    if (job.status === "ok" || job.status === "success") {
      setToast({ msg: "Сессия прогрева завершена", kind: "ok" });
      qc.invalidateQueries({ queryKey: ["warmup-history", tenantId] });
    } else if (job.status === "error") {
      setToast({ msg: job.message ?? "Ошибка прогрева", kind: "err" });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  // История
  const historyQ = useQuery({
    queryKey: ["warmup-history", tenantId],
    queryFn: () =>
      apiFetch<ApiJson>("/api/warmup/history", { tenantId }),
    enabled: tab === "history",
    staleTime: 15_000,
  });
  const historyRows: HistoryRow[] = useMemo(
    () => ((historyQ.data?.sessions as HistoryRow[] | undefined) ?? []),
    [historyQ.data],
  );

  // Запуск прогрева
  const startMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/warmup/start", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          profile_id: selectedProfile,
          intensity,
          niche_keywords: keywords,
          shorts_retention_mode: shortsRetentionMode,
        }),
      }),
    onSuccess: (d: ApiJson) => {
      if (d.status === "ok" || d.status === "running") {
        setJobId(d.job_id as string);
        setLogOpen(false);
      } else {
        setToast({ msg: String(d.message || "Ошибка запуска"), kind: "err" });
      }
    },
    onError: (e: Error) => {
      setToast({ msg: e.message, kind: "err" });
    },
  });

  // Отмена задачи
  const cancelMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>(`/api/warmup/cancel/${jobId}`, {
        method: "DELETE",
        tenantId,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warmup-job", jobId, tenantId] });
    },
  });

  function addKeyword(raw: string) {
    const kw = raw.trim();
    if (kw && !keywords.includes(kw)) {
      setKeywords((prev) => [...prev, kw]);
    }
    setKwInput("");
  }

  const canStart = selectedProfile && !isRunning && !startMut.isPending;
  const selectedIntensity = intensities.find((i) => i.key === intensity);
  const stats = job?.stats ?? {};
  const actionsLog = job?.actions_log ?? [];
  const isSuccess = job?.status === "ok" || job?.status === "success";
  const isError = job?.status === "error";
  const isCancelled = job?.status === "cancelled";

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

      {/* Табы */}
      <div style={{ display: "flex", gap: 0, marginBottom: 20, borderBottom: "1px solid var(--border-subtle)" }}>
        {(["run", "history"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            style={{
              background: "none",
              border: "none",
              borderBottom: `2px solid ${tab === t ? "var(--accent-cyan)" : "transparent"}`,
              color: tab === t ? "var(--accent-cyan)" : "var(--text-tertiary)",
              textShadow: tab === t ? "0 0 20px rgba(94,234,212,0.45)" : "none",
              padding: "9px 20px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 7,
              marginBottom: -1,
              transition: "color 0.15s, text-shadow 0.15s",
            }}
          >
            {t === "run" ? <Play size={14} /> : <History size={14} />}
            {t === "run" ? "Запуск" : "История"}
          </button>
        ))}
      </div>

      {/* ── Таб: Запуск ── */}
      {tab === "run" && (
        <div className="two-col">
          {/* Левая колонка */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Профиль */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Профиль</span>
              </div>
              <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {profilesQ.isLoading && (
                  <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Загрузка профилей…</div>
                )}
                {!profilesQ.isLoading && profiles.length === 0 && (
                  <div style={{ fontSize: 13, color: "var(--accent-amber)" }}>
                    Нет синхронизированных профилей. Перейдите в Аккаунты и нажмите «Синхронизировать».
                  </div>
                )}
                {profiles.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                    {profiles.map((p) => {
                      const isActive = selectedProfile === p.user_id;
                      return (
                      <label
                        key={p.user_id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: "9px 13px",
                          borderRadius: 8,
                          border: `1px solid ${isActive ? "rgba(94,234,212,0.45)" : "var(--border-default)"}`,
                          background: isActive ? "rgba(94,234,212,0.07)" : "var(--bg-elevated)",
                          cursor: isRunning ? "not-allowed" : "pointer",
                          opacity: isRunning ? 0.6 : 1,
                          transition: "all 0.16s",
                          boxShadow: isActive ? "0 0 10px rgba(94,234,212,0.12)" : "none",
                        }}
                      >
                        <div style={{
                          width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                          background: isActive ? "var(--accent-cyan)" : "var(--text-disabled)",
                          boxShadow: isActive ? "0 0 6px rgba(94,234,212,0.6)" : "none",
                          transition: "all 0.16s",
                        }} />
                        <input
                          type="radio"
                          name="profile"
                          value={p.user_id}
                          checked={isActive}
                          onChange={() => !isRunning && setSelectedProfile(p.user_id)}
                          disabled={isRunning}
                          style={{ display: "none" }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: isActive ? "var(--accent-cyan)" : "var(--text-primary)" }}>
                            {p.name}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "var(--font-mono)", marginTop: 1 }}>
                            {p.user_id}
                          </div>
                        </div>
                        {isActive && <UserCheck size={14} style={{ color: "var(--accent-cyan)", opacity: 0.7, flexShrink: 0 }} />}
                      </label>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Интенсивность */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Интенсивность</span>
              </div>
              <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(intensities.length > 0 ? intensities : [
                  { key: "light",  label: "Лёгкий",  desc: "2–4 видео, 1–2 поиска, ~15 мин" },
                  { key: "medium", label: "Средний",  desc: "4–7 видео, 2–4 поиска, ~30 мин" },
                  { key: "deep",   label: "Глубокий", desc: "8–14 видео, 4–7 поисков, ~60 мин" },
                ]).map((opt) => {
                  const intensityColors: Record<string, string> = { light: "#4ADE80", medium: "#FBBF24", deep: "#F23F5D" };
                  const accent = intensityColors[opt.key] ?? "var(--accent-cyan)";
                  const isActive = intensity === opt.key;
                  return (
                  <label
                    key={opt.key}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 12,
                      padding: "11px 14px",
                      borderRadius: 9,
                      border: `1px solid ${isActive ? `${accent}55` : "var(--border-default)"}`,
                      background: isActive ? `${accent}10` : "var(--bg-elevated)",
                      cursor: isRunning ? "not-allowed" : "pointer",
                      opacity: isRunning ? 0.6 : 1,
                      transition: "all 0.18s",
                      boxShadow: isActive ? `0 0 12px ${accent}20` : "none",
                    }}
                  >
                    <div style={{
                      width: 18, height: 18, borderRadius: "50%", flexShrink: 0, marginTop: 1,
                      border: `2px solid ${isActive ? accent : "var(--border-strong)"}`,
                      background: isActive ? accent : "transparent",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      transition: "all 0.18s",
                    }}>
                      {isActive && <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#0a1a18" }} />}
                    </div>
                    <input
                      type="radio"
                      name="intensity"
                      value={opt.key}
                      checked={isActive}
                      onChange={() => !isRunning && setIntensity(opt.key)}
                      disabled={isRunning}
                      style={{ display: "none" }}
                    />
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: isActive ? accent : "var(--text-primary)" }}>
                        {opt.label}
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginTop: 3, lineHeight: 1.4 }}>
                        {opt.desc}
                      </div>
                    </div>
                  </label>
                  );
                })}
              </div>
            </div>

            {/* Ключевые слова */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Ключевые слова ниши</span>
                <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>необязательно</span>
              </div>
              <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    className="form-input mono"
                    style={{ flex: 1, fontSize: 13 }}
                    placeholder="korean street food"
                    value={kwInput}
                    onChange={(e) => setKwInput(e.target.value)}
                    disabled={isRunning}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === ",") {
                        e.preventDefault();
                        addKeyword(kwInput);
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="action-btn secondary"
                    onClick={() => addKeyword(kwInput)}
                    disabled={isRunning}
                    style={{ fontSize: 12, padding: "6px 14px", whiteSpace: "nowrap" }}
                  >
                    + Добавить
                  </button>
                </div>
                {keywords.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {keywords.map((kw) => (
                      <KeywordTag
                        key={kw}
                        value={kw}
                        onRemove={() => !isRunning && setKeywords((prev) => prev.filter((k) => k !== kw))}
                      />
                    ))}
                  </div>
                )}
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  Бот будет искать эти слова на YouTube. Смешиваются с общими запросами.
                </div>
              </div>
            </div>

            {/* Shorts retention mode */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Режим просмотра Shorts</span>
                <span style={{ fontSize: 11, color: "var(--accent-cyan)", background: "rgba(94,234,212,0.08)", padding: "2px 7px", borderRadius: 4 }}>алгоритм</span>
              </div>
              <div className="card-body">
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                  {([
                    { key: "mixed",   label: "Mixed",   desc: "Реалистичная смесь профилей (рекомендуется)" },
                    { key: "looper",  label: "Looper",  desc: "2–4 реплея на Short — максимальный сигнал" },
                    { key: "engaged", label: "Engaged", desc: "Полный просмотр + лайки" },
                    { key: "casual",  label: "Casual",  desc: "35–70% длины, нейтрально" },
                  ] as const).map((opt) => {
                    const isActive = shortsRetentionMode === opt.key;
                    return (
                      <button
                        key={opt.key}
                        type="button"
                        disabled={isRunning}
                        onClick={() => setShortsRetentionMode(opt.key)}
                        style={{
                          padding: "8px 10px",
                          borderRadius: 7,
                          border: `1px solid ${isActive ? "rgba(94,234,212,0.5)" : "var(--border-default)"}`,
                          background: isActive ? "rgba(94,234,212,0.08)" : "var(--bg-elevated)",
                          color: isActive ? "var(--accent-cyan)" : "var(--text-secondary)",
                          textAlign: "left",
                          cursor: isRunning ? "not-allowed" : "pointer",
                          opacity: isRunning ? 0.6 : 1,
                          transition: "all 0.15s",
                        }}
                      >
                        <div style={{ fontSize: 12, fontWeight: 700 }}>{opt.label}</div>
                        <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 2, lineHeight: 1.35 }}>{opt.desc}</div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Кнопки */}
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                disabled={!canStart}
                onClick={() => {
                  setJobId(null);
                  startMut.mutate();
                }}
                style={{
                  flex: 1,
                  padding: "13px 20px",
                  fontSize: 14,
                  fontWeight: 800,
                  letterSpacing: "0.02em",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  borderRadius: 9,
                  cursor: canStart ? "pointer" : "not-allowed",
                  opacity: canStart ? 1 : 0.45,
                  background: isRunning
                    ? "rgba(94,234,212,0.08)"
                    : "var(--accent-cyan)",
                  color: isRunning ? "var(--accent-cyan)" : "#061a16",
                  border: isRunning ? "1px solid rgba(94,234,212,0.3)" : "none",
                  boxShadow: canStart && !isRunning
                    ? "0 2px 16px rgba(94,234,212,0.35)"
                    : isRunning
                    ? "0 0 20px rgba(94,234,212,0.12)"
                    : "none",
                  transition: "all 0.18s",
                }}
              >
                {isRunning ? (
                  <>
                    <Activity size={16} style={{ animation: "spin 1.2s linear infinite" }} />
                    Прогрев идёт…
                  </>
                ) : (
                  <>
                    <Play size={16} fill="currentColor" />
                    Запустить прогрев
                  </>
                )}
              </button>

              {isRunning && (
                <button
                  type="button"
                  onClick={() => cancelMut.mutate()}
                  disabled={cancelMut.isPending || job?.status === "cancelling"}
                  style={{
                    padding: "13px 18px",
                    fontSize: 13,
                    fontWeight: 700,
                    background: "rgba(242,63,93,0.1)",
                    border: "1px solid rgba(242,63,93,0.35)",
                    borderRadius: 9,
                    color: "var(--accent-red)",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    transition: "all 0.15s",
                    opacity: cancelMut.isPending || job?.status === "cancelling" ? 0.5 : 1,
                  }}
                >
                  <X size={15} />
                  Отменить
                </button>
              )}
            </div>
          </div>

          {/* Правая колонка: статус / результат */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Описание прогрева (пока не запущен) */}
            {!job && !isRunning && (
              <div className="card">
                <div className="card-header">
                  <span className="card-title">Что делает прогрев</span>
                </div>
                <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {[
                    { icon: <Search size={14} />, text: "Ищет по ключевым словам ниши и общим запросам" },
                    { icon: <Play size={14} />, text: "Смотрит видео и Shorts с реальными паузами" },
                    { icon: <ThumbsUp size={14} />, text: "Редко ставит лайки (5–15% видео)" },
                    { icon: <UserCheck size={14} />, text: "Иногда подписывается на каналы (1–5%)" },
                    { icon: <Activity size={14} />, text: "Случайные скроллы, движения мыши, паузы" },
                    { icon: <Zap size={14} />, text: "Заходит в Тренды и Подписки (medium/deep)" },
                  ].map(({ icon, text }) => (
                    <div key={text} style={{ display: "flex", alignItems: "flex-start", gap: 10, fontSize: 13, color: "var(--text-secondary)" }}>
                      <span style={{ color: "var(--accent-cyan)", marginTop: 1, flexShrink: 0 }}>{icon}</span>
                      {text}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Активная задача */}
            {job && (
              <>
                <div className="card">
                  <div className="card-header">
                    <span className="card-title">
                      {isRunning ? "Прогрев выполняется…" : "Результат сессии"}
                    </span>
                    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {statusBadge(job.status)}
                    </span>
                  </div>
                  <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {/* Таймер */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-secondary)" }}>
                      <Clock size={14} style={{ color: "var(--accent-cyan)" }} />
                      {isRunning ? "Прошло:" : "Длительность:"}&nbsp;
                      {/* tick используется для принудительной перерисовки каждую секунду */}
                      <strong style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                        {elapsedLabel(job.started_at, job.finished_at)}
                        {tick >= 0 ? "" : ""}
                      </strong>
                    </div>

                    {/* Промежуточная/итоговая статистика */}
                    {Object.keys(stats).length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        <StatCard icon={<Play size={14} />}     label="Видео"   value={stats.videos_watched   ?? 0} />
                        <StatCard icon={<Zap size={14} />}      label="Shorts"  value={stats.shorts_watched   ?? 0} />
                        <StatCard icon={<Search size={14} />}   label="Поисков" value={stats.searches_done    ?? 0} />
                        <StatCard icon={<Heart size={14} />}    label="Лайков"  value={stats.likes_given      ?? 0} color="var(--accent-red)" />
                        <StatCard icon={<UserCheck size={14} />} label="Подписок" value={stats.subscriptions ?? 0} color="var(--accent-green)" />
                      </div>
                    )}

                    {isSuccess && (
                      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 8, background: "rgba(46,213,115,0.08)", border: "1px solid rgba(46,213,115,0.2)" }}>
                        <CheckCircle size={14} style={{ color: "var(--accent-green)" }} />
                        <span style={{ fontSize: 13, color: "var(--accent-green)" }}>
                          Сессия успешно завершена · профиль переведён в статус «ready»
                        </span>
                      </div>
                    )}

                    {isError && (
                      <div style={{ padding: "8px 12px", borderRadius: 8, background: "rgba(255,71,87,0.10)", border: "1px solid rgba(255,71,87,0.3)", fontSize: 13, color: "var(--accent-red)" }}>
                        {job.message ?? "Ошибка прогрева"}
                      </div>
                    )}

                    {isCancelled && (
                      <div style={{ padding: "8px 12px", borderRadius: 8, background: "rgba(168,178,200,0.08)", border: "1px solid rgba(168,178,200,0.2)", fontSize: 13, color: "var(--text-tertiary)" }}>
                        Сессия отменена пользователем
                      </div>
                    )}

                    {isRunning && (
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        Браузер выполняет действия. Не закрывайте его вручную.
                      </div>
                    )}
                  </div>
                </div>

                {/* Лог действий */}
                {actionsLog.length > 0 && (
                  <div className="card">
                    <button
                      type="button"
                      className="card-header"
                      style={{ width: "100%", cursor: "pointer", background: "none", border: "none", textAlign: "left" }}
                      onClick={() => setLogOpen((o) => !o)}
                    >
                      <span className="card-title">Лог действий</span>
                      <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-tertiary)" }}>
                        {actionsLog.length} {isRunning ? "(обновляется)" : ""}
                        {logOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </span>
                    </button>
                    {logOpen && (
                      <div className="card-body">
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 4,
                            maxHeight: 260,
                            overflowY: "auto",
                          }}
                        >
                          {actionsLog.map((action, i) => (
                            <div
                              key={i}
                              style={{
                                fontSize: 12,
                                fontFamily: "var(--font-mono)",
                                color: action.includes("failed") || action.includes("error")
                                  ? "var(--accent-amber)"
                                  : "var(--text-secondary)",
                                padding: "3px 0",
                                borderBottom: "1px solid rgba(255,255,255,0.04)",
                                display: "flex",
                                gap: 10,
                              }}
                            >
                              <span style={{ color: "var(--text-muted)", minWidth: 24 }}>{i + 1}.</span>
                              <span>{action}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Таб: История ── */}
      {tab === "history" && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">История сессий прогрева</span>
            <button
              type="button"
              className="action-btn secondary"
              style={{ fontSize: 12, padding: "4px 12px" }}
              onClick={() => qc.invalidateQueries({ queryKey: ["warmup-history", tenantId] })}
            >
              Обновить
            </button>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {historyQ.isLoading && (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table">
                  <tbody>
                    {[1, 2, 3].map((i) => (
                      <tr key={i} className="skeleton-row">
                        {[140, 60, 60, 40, 40, 40, 40, 40, 90].map((w, j) => (
                          <td key={j}><div className="skeleton skeleton-cell" style={{ width: w }} /></td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!historyQ.isLoading && historyRows.length === 0 && (
              <div className="empty-state">
                <div className="empty-state-icon"><History size={22} style={{ opacity: 0.6 }} /></div>
                <p className="empty-state-title">История пуста</p>
                <p className="empty-state-sub">Запустите первую сессию прогрева — результаты появятся здесь.</p>
              </div>
            )}
            {historyRows.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      {["Профиль", "Интенс.", "Статус", "Видео", "Shorts", "Поисков", "Лайков", "Подписок", "Дата"].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {historyRows.map((row) => (
                      <tr key={row.id}>
                        <td className="mono" style={{ fontSize: 11 }}>{row.profile_id}</td>
                        <td>
                          <span style={{
                            fontSize: 11,
                            padding: "2px 7px",
                            borderRadius: 4,
                            background: row.intensity === "deep" ? "rgba(242,63,93,0.1)" : row.intensity === "light" ? "rgba(74,222,128,0.1)" : "rgba(251,191,36,0.1)",
                            color: row.intensity === "deep" ? "var(--accent-red)" : row.intensity === "light" ? "var(--accent-green)" : "var(--accent-amber)",
                            fontWeight: 600,
                            fontFamily: "var(--font-mono)",
                          }}>{row.intensity}</span>
                        </td>
                        <td>{statusBadge(row.status)}</td>
                        <td className="mono" style={{ color: "var(--accent-cyan)" }}>{row.videos_watched}</td>
                        <td className="mono" style={{ color: "var(--accent-cyan)" }}>{row.shorts_watched}</td>
                        <td className="mono">{row.searches_done}</td>
                        <td className="mono" style={{ color: "var(--accent-red)" }}>{row.likes_given}</td>
                        <td className="mono" style={{ color: "var(--accent-green)" }}>{row.subscriptions}</td>
                        <td className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)", whiteSpace: "nowrap" }}>
                          {row.started_at?.replace("T", " ").slice(0, 16) ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </section>
  );
}
