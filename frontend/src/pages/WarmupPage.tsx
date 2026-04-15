import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import {
  Activity,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Heart,
  Play,
  Search,
  ThumbsUp,
  UserCheck,
  Zap,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────────────

type Profile = { user_id: string; name: string };

type WarmupStats = {
  videos_watched: number;
  shorts_watched: number;
  searches_done: number;
  likes_given: number;
  subscriptions: number;
  started_at: string;
  finished_at: string | null;
};

type WarmupResult = {
  status: string;
  message?: string;
  profile_id?: string;
  intensity?: string;
  stats?: WarmupStats;
  actions_log?: string[];
};

type IntensityOption = { key: string; label: string; desc: string };

// ── Вспомогалки ─────────────────────────────────────────────────────────────

function durationLabel(started: string, finished: string | null): string {
  if (!finished) return "—";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec} сек`;
  return `${Math.floor(sec / 60)} мин ${sec % 60} сек`;
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

// ── StatCard ─────────────────────────────────────────────────────────────────

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
        background: "var(--bg-card, #1a2744)",
        border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: 10,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ color: color ?? "var(--accent-cyan)", display: "flex", alignItems: "center", gap: 6 }}>
        {icon}
        <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 500 }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)" }}>{value}</div>
    </div>
  );
}

// ── Основной компонент ───────────────────────────────────────────────────────

export function WarmupPage() {
  const { tenantId } = useTenant();

  const [selectedProfile, setSelectedProfile] = useState("");
  const [intensity, setIntensity] = useState("medium");
  const [kwInput, setKwInput] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [result, setResult] = useState<WarmupResult | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);

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

  // Запуск прогрева
  const warmupMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/warmup/run", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          profile_id: selectedProfile,
          intensity,
          niche_keywords: keywords,
        }),
      }),
    onSuccess: (d: ApiJson) => {
      setResult(d as unknown as WarmupResult);
      if (d.status === "ok") {
        setToast({ msg: "Сессия прогрева завершена", kind: "ok" });
      } else {
        setToast({ msg: String(d.message || "Ошибка прогрева"), kind: "err" });
      }
    },
    onError: (e: Error) => {
      setToast({ msg: e.message, kind: "err" });
    },
  });

  // Добавление ключевого слова
  function addKeyword(raw: string) {
    const kw = raw.trim();
    if (kw && !keywords.includes(kw)) {
      setKeywords((prev) => [...prev, kw]);
    }
    setKwInput("");
  }

  const canRun = selectedProfile && !warmupMut.isPending;
  const selectedIntensity = intensities.find((i) => i.key === intensity);

  return (
    <section className="page">
      {toast && (
        <div className={`toast show ${toast.kind === "ok" ? "ok" : "err"}`}>
          {toast.msg}
        </div>
      )}

      <div className="two-col">
        {/* ── Левая колонка: настройки ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Профиль */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Профиль AdsPower</span>
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
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {profiles.map((p) => (
                    <label
                      key={p.user_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "8px 12px",
                        borderRadius: 8,
                        border: `1px solid ${selectedProfile === p.user_id ? "rgba(0,212,255,0.5)" : "rgba(255,255,255,0.07)"}`,
                        background: selectedProfile === p.user_id ? "rgba(0,212,255,0.07)" : "transparent",
                        cursor: "pointer",
                        transition: "all 0.15s",
                      }}
                    >
                      <input
                        type="radio"
                        name="profile"
                        value={p.user_id}
                        checked={selectedProfile === p.user_id}
                        onChange={() => setSelectedProfile(p.user_id)}
                        style={{ accentColor: "var(--accent-cyan)" }}
                      />
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>
                          {p.name}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "var(--font-mono)" }}>
                          {p.user_id}
                        </div>
                      </div>
                    </label>
                  ))}
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
              ]).map((opt) => (
                <label
                  key={opt.key}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    padding: "10px 12px",
                    borderRadius: 8,
                    border: `1px solid ${intensity === opt.key ? "rgba(0,212,255,0.5)" : "rgba(255,255,255,0.07)"}`,
                    background: intensity === opt.key ? "rgba(0,212,255,0.07)" : "transparent",
                    cursor: "pointer",
                    transition: "all 0.15s",
                  }}
                >
                  <input
                    type="radio"
                    name="intensity"
                    value={opt.key}
                    checked={intensity === opt.key}
                    onChange={() => setIntensity(opt.key)}
                    style={{ accentColor: "var(--accent-cyan)", marginTop: 2 }}
                  />
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                      {opt.label}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
                      {opt.desc}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Ключевые слова ниши */}
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
                      onRemove={() => setKeywords((prev) => prev.filter((k) => k !== kw))}
                    />
                  ))}
                </div>
              )}
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Бот будет искать эти слова на YouTube. Смешиваются с общими запросами для естественного поведения.
              </div>
            </div>
          </div>

          {/* Кнопка запуска */}
          <button
            type="button"
            className="action-btn"
            disabled={!canRun}
            onClick={() => {
              setResult(null);
              setLogOpen(false);
              warmupMut.mutate();
            }}
            style={{
              width: "100%",
              padding: "12px",
              fontSize: 14,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              opacity: canRun ? 1 : 0.5,
            }}
          >
            {warmupMut.isPending ? (
              <>
                <Activity size={16} style={{ animation: "spin 1.2s linear infinite" }} />
                Прогрев идёт… ({selectedIntensity?.desc ?? ""})
              </>
            ) : (
              <>
                <Play size={16} />
                Запустить прогрев
              </>
            )}
          </button>

          {warmupMut.isPending && (
            <div
              style={{
                padding: "10px 14px",
                borderRadius: 8,
                background: "rgba(0,212,255,0.07)",
                border: "1px solid rgba(0,212,255,0.2)",
                fontSize: 12,
                color: "var(--text-secondary)",
              }}
            >
              Браузер AdsPower открыт и выполняет действия. Не закрывайте его вручную. Дождитесь завершения.
            </div>
          )}
        </div>

        {/* ── Правая колонка: результат ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Что делает прогрев */}
          {!result && !warmupMut.isPending && (
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

          {/* Ошибка */}
          {result?.status === "error" && (
            <div
              style={{
                padding: "14px 16px",
                borderRadius: 10,
                background: "rgba(255,71,87,0.10)",
                border: "1px solid rgba(255,71,87,0.3)",
                fontSize: 13,
                color: "var(--accent-red)",
              }}
            >
              {result.message}
            </div>
          )}

          {/* Результат */}
          {result?.status === "ok" && result.stats && (
            <>
              <div className="card">
                <div className="card-header">
                  <span className="card-title">Результат сессии</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    профиль {result.profile_id} · {result.intensity}
                  </span>
                </div>
                <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {/* Время */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-secondary)" }}>
                    <Clock size={14} style={{ color: "var(--accent-cyan)" }} />
                    Длительность:&nbsp;
                    <strong style={{ color: "var(--text-primary)" }}>
                      {durationLabel(result.stats.started_at, result.stats.finished_at)}
                    </strong>
                  </div>

                  {/* Статистика */}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    <StatCard
                      icon={<Play size={14} />}
                      label="Видео"
                      value={result.stats.videos_watched}
                    />
                    <StatCard
                      icon={<Zap size={14} />}
                      label="Shorts"
                      value={result.stats.shorts_watched}
                    />
                    <StatCard
                      icon={<Search size={14} />}
                      label="Поисков"
                      value={result.stats.searches_done}
                    />
                    <StatCard
                      icon={<Heart size={14} />}
                      label="Лайков"
                      value={result.stats.likes_given}
                      color="var(--accent-red)"
                    />
                    <StatCard
                      icon={<UserCheck size={14} />}
                      label="Подписок"
                      value={result.stats.subscriptions}
                      color="var(--accent-green)"
                    />
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 8, background: "rgba(46,213,115,0.08)", border: "1px solid rgba(46,213,115,0.2)" }}>
                    <CheckCircle size={14} style={{ color: "var(--accent-green)" }} />
                    <span style={{ fontSize: 13, color: "var(--accent-green)" }}>
                      Сессия прогрева успешно завершена
                    </span>
                  </div>
                </div>
              </div>

              {/* Лог действий */}
              {result.actions_log && result.actions_log.length > 0 && (
                <div className="card">
                  <button
                    type="button"
                    className="card-header"
                    style={{ width: "100%", cursor: "pointer", background: "none", border: "none", textAlign: "left" }}
                    onClick={() => setLogOpen((o) => !o)}
                  >
                    <span className="card-title">Лог действий</span>
                    <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-tertiary)" }}>
                      {result.actions_log.length} действий
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
                        {result.actions_log.map((action, i) => (
                          <div
                            key={i}
                            style={{
                              fontSize: 12,
                              fontFamily: "var(--font-mono)",
                              color: "var(--text-secondary)",
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

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </section>
  );
}
