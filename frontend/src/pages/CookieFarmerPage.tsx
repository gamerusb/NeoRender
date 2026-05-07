import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Cookie,
  Globe,
  Loader2,
  Play,
  PlayCircle,
  RefreshCw,
  Square,
  XCircle,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────────────

type FarmerStatus = {
  running: boolean;
  cycles: number;
  last_cycle_at: string | null;
  last_error: string | null;
  cfg: {
    interval_sec: number;
    batch_size: number;
    concurrency: number;
    warmup_intensity: string;
    niche: string;
  } | null;
};

type ProfileState = {
  profile_id: string;
  last_farmed_at: string | null;
  total_farmed: number;
  last_error: string | null;
  status: "ok" | "error" | "farming" | "pending";
};

type AdsProfile = {
  adspower_profile_id: string;
  name?: string;
  status?: string;
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}с назад`;
  if (diff < 3600) return `${Math.floor(diff / 60)}м назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}ч назад`;
  return `${Math.floor(diff / 86400)}д назад`;
}

function StatusBadge({ status }: { status: ProfileState["status"] }) {
  if (status === "ok")
    return (
      <span className="badge badge-success">
        <span className="badge-dot" />
        OK
      </span>
    );
  if (status === "error")
    return (
      <span className="badge badge-error">
        <span className="badge-dot" />
        Ошибка
      </span>
    );
  if (status === "farming")
    return (
      <span className="badge badge-info">
        <span className="badge-dot" />
        Фармится
      </span>
    );
  return (
    <span className="badge badge-neutral">
      <span className="badge-dot" />
      Ожидает
    </span>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function CookieFarmerPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();

  // Конфиг шедулера
  const [intervalSec, setIntervalSec] = useState(1800);
  const [batchSize, setBatchSize] = useState(5);
  const [concurrency, setConcurrency] = useState(2);
  const [intensity, setIntensity] = useState("light");
  const [niche, setNiche] = useState("general");

  // Статус шедулера
  const statusQ = useQuery({
    queryKey: ["cookie-farmer-status", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/cookie-farmer/status", { tenantId }),
    refetchInterval: 5000,
  });
  const farmer = (statusQ.data as any)?.state as FarmerStatus | undefined;
  const isRunning = farmer?.running ?? false;

  // Профили с историей фарминга
  const profilesQ = useQuery({
    queryKey: ["cookie-farmer-profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/cookie-farmer/profiles", { tenantId }),
    refetchInterval: 8000,
  });
  const farmProfiles: ProfileState[] = (profilesQ.data as any)?.profiles ?? [];

  // Все AdsPower-профили для таблицы
  const allProfilesQ = useQuery({
    queryKey: ["adspower-profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/adspower/profiles", { tenantId }),
    staleTime: 30_000,
  });
  const allProfiles: AdsProfile[] =
    ((allProfilesQ.data as any)?.profiles ?? []).filter(
      (p: AdsProfile) =>
        ["ready", "active", "new"].includes((p.status ?? "").toLowerCase())
    );

  // Merge: adspower list + farm history
  const merged = allProfiles.map((ap) => {
    const hist = farmProfiles.find((fp) => fp.profile_id === ap.adspower_profile_id);
    return {
      profile_id: ap.adspower_profile_id,
      name: ap.name || ap.adspower_profile_id,
      ap_status: ap.status ?? "",
      last_farmed_at: hist?.last_farmed_at ?? null,
      total_farmed: hist?.total_farmed ?? 0,
      last_error: hist?.last_error ?? null,
      farm_status: hist?.status ?? ("pending" as ProfileState["status"]),
    };
  });

  // Запуск/остановка шедулера
  const startMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/cookie-farmer/start", {
        tenantId,
        method: "POST",
        body: JSON.stringify({ interval_sec: intervalSec, batch_size: batchSize, concurrency, warmup_intensity: intensity, niche }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cookie-farmer-status", tenantId] }),
  });
  const stopMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/cookie-farmer/stop", { tenantId, method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cookie-farmer-status", tenantId] }),
  });

  // Ручной запуск одного профиля
  const [runningNow, setRunningNow] = useState<Set<string>>(new Set());

  const runNowMut = useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<ApiJson>("/api/cookie-farmer/run-now", {
        tenantId,
        method: "POST",
        body: JSON.stringify({ profile_id: profileId, warmup_intensity: intensity, niche }),
      }),
    onMutate: (pid) => setRunningNow((s) => new Set([...s, pid])),
    onSettled: (_, __, pid) => {
      setRunningNow((s) => { const n = new Set(s); n.delete(pid); return n; });
      qc.invalidateQueries({ queryKey: ["cookie-farmer-profiles", tenantId] });
    },
  });

  const okCount = merged.filter((p) => p.farm_status === "ok").length;
  const errCount = merged.filter((p) => p.last_error).length;
  const totalFarmed = merged.reduce((a, p) => a + p.total_farmed, 0);

  return (
    <div className="page">
      {/* ── Stat cards ── */}
      <div className="stats-grid-4">
        <div className={`stat-card ${isRunning ? "green-accent" : ""}`}>
          <div className="stat-label">Шедулер</div>
          <div className={`stat-value ${isRunning ? "green" : ""}`} style={!isRunning ? { color: "var(--text-tertiary)" } : undefined}>
            {isRunning ? "Активен" : "Остановлен"}
          </div>
          {isRunning && farmer?.last_cycle_at && (
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
              Цикл: {fmtRelative(farmer.last_cycle_at)}
            </div>
          )}
        </div>
        <div className="stat-card cyan-accent">
          <div className="stat-label">Циклов выполнено</div>
          <div className="stat-value cyan">{farmer?.cycles ?? 0}</div>
        </div>
        <div className="stat-card cyan-accent">
          <div className="stat-label">Профилей сфармлено</div>
          <div className="stat-value cyan">{okCount} <span style={{ fontSize: 14, color: "var(--text-tertiary)", fontWeight: 500 }}>/ {merged.length}</span></div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
            {totalFarmed} всего запусков
          </div>
        </div>
        <div className={`stat-card ${errCount > 0 ? "red-accent" : "green-accent"}`}>
          <div className="stat-label">Ошибки</div>
          <div className={`stat-value ${errCount > 0 ? "red" : "green"}`}>{errCount}</div>
        </div>
      </div>

      <div className="settings-grid">
        {/* ── Left: controls + profiles table ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Глобальная ошибка */}
          {farmer?.last_error && (
            <div className="alert alert-error" style={{ fontSize: 12 }}>
              <AlertTriangle size={14} />
              {farmer.last_error}
            </div>
          )}

          {/* Profiles table */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <Cookie size={14} style={{ marginRight: 6, opacity: 0.7 }} />
                Профили
              </span>
              <button
                className="btn btn-ghost btn-xs"
                onClick={() => {
                  qc.invalidateQueries({ queryKey: ["cookie-farmer-profiles", tenantId] });
                  qc.invalidateQueries({ queryKey: ["adspower-profiles", tenantId] });
                }}
              >
                <RefreshCw size={12} />
              </button>
            </div>
            <div className="card-body-flush">
              {allProfilesQ.isLoading ? (
                <table className="data-table">
                  <tbody>
                    {[1, 2, 3].map((i) => (
                      <tr key={i} className="skeleton-row">
                        <td><div className="skeleton skeleton-cell" style={{ width: 140 }} /></td>
                        <td><div className="skeleton skeleton-cell" style={{ width: 80 }} /></td>
                        <td><div className="skeleton skeleton-cell" style={{ width: 30 }} /></td>
                        <td><div className="skeleton skeleton-cell" style={{ width: 60 }} /></td>
                        <td><div className="skeleton skeleton-cell" style={{ width: 28 }} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : merged.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon">
                    <Cookie size={22} style={{ opacity: 0.6 }} />
                  </div>
                  <p className="empty-state-title">Нет активных профилей</p>
                  <p className="empty-state-sub">Добавьте профили AdsPower со статусом ready/active/new, затем запустите шедулер.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Профиль</th>
                      <th>Последний фарминг</th>
                      <th>Запусков</th>
                      <th>Статус</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {merged.map((p) => (
                      <tr key={p.profile_id}>
                        <td className="mono" style={{ fontSize: 12 }}>{p.name}</td>
                        <td className="mono" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                          {fmtRelative(p.last_farmed_at)}
                        </td>
                        <td className="mono" style={{ color: "var(--accent-cyan)" }}>{p.total_farmed}</td>
                        <td>
                          {p.last_error ? (
                            <span
                              className="badge badge-error"
                              title={p.last_error}
                              style={{ cursor: "help" }}
                            >
                              <XCircle size={10} style={{ marginRight: 3 }} />
                              Ошибка
                            </span>
                          ) : (
                            <StatusBadge status={p.farm_status} />
                          )}
                        </td>
                        <td>
                          <button
                            className="btn btn-ghost btn-xs"
                            disabled={runningNow.has(p.profile_id)}
                            onClick={() => runNowMut.mutate(p.profile_id)}
                            title="Запустить фарминг сейчас"
                            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                          >
                            {runningNow.has(p.profile_id) ? (
                              <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />
                            ) : (
                              <PlayCircle size={12} />
                            )}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        {/* ── Right: scheduler config ── */}
        <div>
          <div className="card">
            <div className="card-header">
              <span className="card-title">Настройки шедулера</span>
            </div>
            <div className="card-body">
              <div className="form-group">
                <label className="form-label">Интервал между циклами (сек)</label>
                <input
                  className="form-input"
                  type="number"
                  min={60}
                  value={intervalSec}
                  onChange={(e) => setIntervalSec(Number(e.target.value))}
                  style={{ fontFamily: "var(--font-mono)" }}
                />
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
                  Рекомендуется: 1800 (30 мин)
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Профилей за цикл</label>
                <input
                  className="form-input"
                  type="number"
                  min={1}
                  max={20}
                  value={batchSize}
                  onChange={(e) => setBatchSize(Number(e.target.value))}
                  style={{ fontFamily: "var(--font-mono)" }}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Параллельных браузеров</label>
                <input
                  className="form-input"
                  type="number"
                  min={1}
                  max={5}
                  value={concurrency}
                  onChange={(e) => setConcurrency(Number(e.target.value))}
                  style={{ fontFamily: "var(--font-mono)" }}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Интенсивность прогрева</label>
                <select
                  className="form-input"
                  value={intensity}
                  onChange={(e) => setIntensity(e.target.value)}
                >
                  <option value="light">Light (быстро, ~3 мин)</option>
                  <option value="medium">Medium (~8 мин)</option>
                  <option value="deep">Deep (~20 мин)</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Ниша (ключевые слова)</label>
                <input
                  className="form-input"
                  placeholder="general, gaming, lifestyle"
                  value={niche}
                  onChange={(e) => setNiche(e.target.value)}
                />
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                {!isRunning ? (
                  <button
                    disabled={startMut.isPending}
                    onClick={() => startMut.mutate()}
                    style={{
                      flex: 1,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 20px",
                      fontSize: 14,
                      fontWeight: 800,
                      border: "none",
                      borderRadius: 9,
                      cursor: startMut.isPending ? "not-allowed" : "pointer",
                      opacity: startMut.isPending ? 0.6 : 1,
                      background: "var(--accent-cyan)",
                      color: "#061a16",
                      boxShadow: "0 2px 16px rgba(94,234,212,0.35)",
                      transition: "all 0.18s",
                    }}
                  >
                    {startMut.isPending ? (
                      <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />
                    ) : (
                      <Play size={15} fill="currentColor" />
                    )}
                    Запустить шедулер
                  </button>
                ) : (
                  <button
                    disabled={stopMut.isPending}
                    onClick={() => stopMut.mutate()}
                    style={{
                      flex: 1,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 20px",
                      fontSize: 14,
                      fontWeight: 700,
                      borderRadius: 9,
                      cursor: stopMut.isPending ? "not-allowed" : "pointer",
                      opacity: stopMut.isPending ? 0.6 : 1,
                      background: "rgba(242,63,93,0.1)",
                      border: "1px solid rgba(242,63,93,0.35)",
                      color: "var(--accent-red)",
                      transition: "all 0.18s",
                    }}
                  >
                    {stopMut.isPending ? (
                      <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />
                    ) : (
                      <Square size={14} fill="currentColor" />
                    )}
                    Остановить
                  </button>
                )}
              </div>

              {isRunning && farmer?.cfg && (
                <div
                  style={{
                    marginTop: 12,
                    padding: "8px 10px",
                    background: "var(--bg-elevated)",
                    borderRadius: 6,
                    fontSize: 11,
                    color: "var(--text-secondary)",
                    lineHeight: 1.8,
                  }}
                >
                  <div>
                    <Clock size={10} style={{ marginRight: 4, opacity: 0.6 }} />
                    Интервал: <span className="mono">{farmer.cfg.interval_sec}с</span>
                  </div>
                  <div>
                    <Globe size={10} style={{ marginRight: 4, opacity: 0.6 }} />
                    Batch: <span className="mono">{farmer.cfg.batch_size}</span> ·
                    Concurrency: <span className="mono">{farmer.cfg.concurrency}</span>
                  </div>
                  <div>
                    Режим: <span className="mono">{farmer.cfg.warmup_intensity}</span> ·
                    Ниша: <span className="mono">{farmer.cfg.niche}</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Что делает фармер */}
          <div className="card" style={{ marginTop: 12 }}>
            <div className="card-header">
              <span className="card-title">Что делает за цикл</span>
            </div>
            <div className="card-body" style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.9 }}>
              {[
                "Открывает профиль AdsPower",
                "Посещает 5–9 новостных и lifestyle-сайтов",
                "Делает 2–3 Google-поиска",
                "Запускает YouTube-прогрев (light)",
                "Сохраняет бэкап cookies",
                "Закрывает браузер",
              ].map((step, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <CheckCircle
                    size={11}
                    style={{ color: "var(--accent-green)", flexShrink: 0 }}
                  />
                  {step}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
