import { useQuery } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import { SkeletonStatGrid } from "@/components/Skeleton";
import {
  Activity,
  CheckCircle2,
  Cpu,
  HardDrive,
  RefreshCw,
  Server,
  Wifi,
  XCircle,
  Zap,
} from "lucide-react";

type WorkerHealth = {
  pipeline_running?: boolean;
  queue_size?: number;
  metrics?: {
    tasks_done?: number;
    tasks_error?: number;
    tasks_active?: number;
  };
  workers?: Record<string, { alive?: boolean; busy?: boolean; name?: string }>;
};

type SystemStatus = {
  disk?: { free_gb?: number; total_gb?: number; used_pct?: number };
  memory?: { used_mb?: number; total_mb?: number; used_pct?: number };
  cpu?: { percent?: number };
  ffmpeg?: { available?: boolean; version?: string };
};

function GaugeBar({ pct, color }: { pct: number; color: string }) {
  const warn = pct >= 90 ? "var(--accent-red)" : pct >= 70 ? "var(--accent-amber)" : color;
  return (
    <div style={{ background: "var(--bg-elevated)", borderRadius: 4, height: 8, overflow: "hidden", marginTop: 6 }}>
      <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: warn, borderRadius: 4, transition: "width 0.5s ease" }} />
    </div>
  );
}

export function AdminSystemPage() {
  const { tenantId } = useTenant();

  const healthQ = useQuery({
    queryKey: ["admin-worker-health", tenantId],
    queryFn: () => apiFetch<WorkerHealth>("/api/health/workers", { tenantId }),
    refetchInterval: 4_000,
    staleTime: 2_000,
    retry: false,
  });

  const statusQ = useQuery({
    queryKey: ["admin-system-status", tenantId],
    queryFn: () => apiFetch<SystemStatus>("/api/system/status", { tenantId }),
    refetchInterval: 10_000,
    staleTime: 5_000,
    retry: false,
  });

  const ffmpegQ = useQuery({
    queryKey: ["admin-ffmpeg-config", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/system/ffmpeg-config", { tenantId }),
    staleTime: 60_000,
    retry: false,
  });

  const integrationsQ = useQuery({
    queryKey: ["admin-integrations-ping", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/integrations/ping", { tenantId }),
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: false,
  });

  const health = healthQ.data;
  const sys = statusQ.data;
  const ffmpeg = ffmpegQ.data;
  const integrations = integrationsQ.data;

  const workers = health?.workers ?? {};
  const workerList = Object.entries(workers);

  const diskUsed = Number(sys?.disk?.used_pct ?? 0);
  const memUsed = Number(sys?.memory?.used_pct ?? 0);
  const cpuUsed = Number(sys?.cpu?.percent ?? 0);

  const isLoading = healthQ.isLoading || statusQ.isLoading;

  return (
    <div className="page-root" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">
            <Server size={20} color="var(--accent-amber)" />
            Системный мониторинг
          </h1>
          <p className="page-subtitle">Состояние воркеров, ресурсов и интеграций</p>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => { void healthQ.refetch(); void statusQ.refetch(); }}
        >
          <RefreshCw size={14} />
          Обновить
        </button>
      </div>
      {isLoading && <SkeletonStatGrid count={3} />}

      {/* Pipeline pill */}
      <div style={s.pipelineCard}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 10, height: 10, borderRadius: "50%",
            background: health?.pipeline_running ? "var(--accent-green)" : "var(--text-disabled)",
            boxShadow: health?.pipeline_running ? "0 0 8px var(--accent-green)" : "none",
          }} />
          <span style={{ fontWeight: 600, fontSize: 14 }}>
            Pipeline: {health?.pipeline_running ? "RUNNING" : "STOPPED"}
          </span>
        </div>
        <div style={s.pipelineStats}>
          <span>Очередь: <b>{health?.queue_size ?? 0}</b></span>
          <span>Активных: <b>{health?.metrics?.tasks_active ?? 0}</b></span>
          <span>Выполнено: <b>{health?.metrics?.tasks_done ?? 0}</b></span>
          <span style={{ color: "var(--accent-red)" }}>Ошибок: <b>{health?.metrics?.tasks_error ?? 0}</b></span>
        </div>
      </div>

      <div style={s.grid3}>
        {/* Resources */}
        <div style={s.card}>
          <div style={s.cardTitle}>
            <Cpu size={15} style={{ marginRight: 8, color: "var(--accent-cyan)" }} />
            Ресурсы сервера
          </div>

          <div style={s.resourceItem}>
            <div style={s.resourceTop}>
              <span>CPU</span>
              <span style={s.pctLabel}>{cpuUsed.toFixed(1)}%</span>
            </div>
            <GaugeBar pct={cpuUsed} color="var(--accent-cyan)" />
          </div>

          <div style={s.resourceItem}>
            <div style={s.resourceTop}>
              <span>RAM</span>
              <span style={s.pctLabel}>
                {((sys?.memory?.used_mb ?? 0) / 1024).toFixed(1)} / {((sys?.memory?.total_mb ?? 0) / 1024).toFixed(1)} GB
                <span style={{ color: "var(--text-disabled)", marginLeft: 4 }}>({memUsed.toFixed(0)}%)</span>
              </span>
            </div>
            <GaugeBar pct={memUsed} color="var(--accent-purple)" />
          </div>

          <div style={s.resourceItem}>
            <div style={s.resourceTop}>
              <span>Диск</span>
              <span style={s.pctLabel}>
                свободно {(sys?.disk?.free_gb ?? 0).toFixed(1)} / {(sys?.disk?.total_gb ?? 0).toFixed(1)} GB
                <span style={{ color: "var(--text-disabled)", marginLeft: 4 }}>({diskUsed.toFixed(0)}%)</span>
              </span>
            </div>
            <GaugeBar pct={diskUsed} color="var(--accent-amber)" />
          </div>

          {statusQ.isLoading && <div style={s.loading}>Загрузка...</div>}
          {statusQ.isError && <div style={s.errText}>Не удалось получить данные</div>}
        </div>

        {/* Workers */}
        <div style={s.card}>
          <div style={s.cardTitle}>
            <Activity size={15} style={{ marginRight: 8, color: "var(--accent-purple)" }} />
            Воркеры ({workerList.length})
          </div>
          {workerList.length === 0 ? (
            <div style={s.loading}>{healthQ.isLoading ? "Загрузка..." : "Нет данных о воркерах"}</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {workerList.map(([key, w]) => (
                <div key={key} style={s.workerRow}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {w.alive ? (
                      <CheckCircle2 size={14} style={{ color: "var(--accent-green)", flexShrink: 0 }} />
                    ) : (
                      <XCircle size={14} style={{ color: "var(--accent-red)", flexShrink: 0 }} />
                    )}
                    <span style={{ fontSize: 13 }}>{w.name ?? key}</span>
                  </div>
                  <span style={{ ...s.workerStatus, color: w.busy ? "var(--accent-amber)" : w.alive ? "var(--accent-green)" : "var(--accent-red)" }}>
                    {w.busy ? "busy" : w.alive ? "idle" : "dead"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Integrations */}
        <div style={s.card}>
          <div style={s.cardTitle}>
            <Wifi size={15} style={{ marginRight: 8, color: "var(--accent-green)" }} />
            Интеграции
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { key: "groq", label: "Groq AI", value: integrations?.groq_ok },
              { key: "adspower", label: "AdsPower", value: integrations?.adspower_ok },
              { key: "ffmpeg", label: "FFmpeg", value: ffmpeg?.available ?? (ffmpegQ.isLoading ? null : false) },
              { key: "ffmpeg_gpu", label: "NVENC (GPU)", value: ffmpeg?.nvenc_available },
            ].map((item) => (
              <div key={item.key} style={s.integRow}>
                <span style={{ fontSize: 13 }}>{item.label}</span>
                {item.value === null || item.value === undefined ? (
                  <span style={{ ...s.integBadge, color: "var(--text-disabled)", background: "var(--bg-elevated)" }}>—</span>
                ) : item.value ? (
                  <span style={{ ...s.integBadge, color: "var(--accent-green)", background: "var(--accent-green-dim)" }}>
                    <CheckCircle2 size={11} style={{ marginRight: 4 }} />
                    OK
                  </span>
                ) : (
                  <span style={{ ...s.integBadge, color: "var(--accent-red)", background: "var(--accent-red-dim)" }}>
                    <XCircle size={11} style={{ marginRight: 4 }} />
                    Error
                  </span>
                )}
              </div>
            ))}

            {Boolean(ffmpeg?.version) && (
              <div style={{ marginTop: 8, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-disabled)" }}>
                {String(ffmpeg?.version ?? "")}
              </div>
            )}
          </div>

          {/* FFmpeg config summary */}
          {ffmpeg && (
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border-subtle)" }}>
              <div style={s.cardTitle}>
                <Zap size={13} style={{ marginRight: 6, color: "var(--accent-amber)" }} />
                Энкодер
              </div>
              <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                {String(ffmpeg.video_codec ?? "?")} / {String(ffmpeg.audio_codec ?? "?")}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* HardDrive */}
      <div style={{ ...s.card, marginTop: 0 }}>
        <div style={s.cardTitle}>
          <HardDrive size={15} style={{ marginRight: 8, color: "var(--accent-amber)" }} />
          Хранилище
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {[
            { label: "Загрузки", path: "data/uploads" },
            { label: "Рендер", path: "data/rendered" },
            { label: "Скриншоты", path: "data/screenshots" },
          ].map((item) => (
            <div key={item.path} style={{ background: "var(--bg-elevated)", borderRadius: "var(--radius-md)", padding: "12px 16px" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>{item.path}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  page: { padding: "0 0 40px", display: "flex", flexDirection: "column", gap: 16 },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start" },
  title: { display: "flex", alignItems: "center", fontSize: 22, fontWeight: 700, letterSpacing: "-0.3px", marginBottom: 6 },
  subtitle: { fontSize: 14, color: "var(--text-secondary)" },
  refreshBtn: {
    display: "flex", alignItems: "center", padding: "8px 14px",
    background: "var(--bg-elevated)", border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-md)", color: "var(--text-secondary)", fontSize: 13, cursor: "pointer", fontWeight: 500,
  },
  pipelineCard: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    background: "var(--bg-surface)", border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-lg)", padding: "16px 24px",
  },
  pipelineStats: { display: "flex", gap: 24, fontSize: 13, color: "var(--text-secondary)" },
  grid3: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 },
  card: {
    background: "var(--bg-surface)", border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-lg)", padding: 24,
  },
  cardTitle: { display: "flex", alignItems: "center", fontWeight: 600, fontSize: 13, marginBottom: 16, color: "var(--text-primary)" },
  resourceItem: { marginBottom: 14 },
  resourceTop: { display: "flex", justifyContent: "space-between", fontSize: 13, color: "var(--text-secondary)", marginBottom: 4 },
  pctLabel: { fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-tertiary)" },
  workerRow: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)" },
  workerStatus: { fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 600 },
  integRow: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  integBadge: { display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)", padding: "2px 9px", borderRadius: 20 },
  loading: { fontSize: 12, color: "var(--text-disabled)" },
  errText: { fontSize: 12, color: "var(--accent-red)" },
};
