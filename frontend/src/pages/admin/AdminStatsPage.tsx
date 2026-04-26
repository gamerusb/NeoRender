import { useQuery } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import { EmptyState } from "@/components/EmptyState";
import { SkeletonStatGrid, SkeletonTable } from "@/components/Skeleton";
import { AreaChart, BarChart3, TrendingUp, Upload, Users, Zap } from "lucide-react";

type DashSummary = {
  total_tasks?: number;
  tasks_success?: number;
  tasks_error?: number;
  tasks_pending?: number;
  total_uploads?: number;
  total_profiles?: number;
  total_views?: number;
  top_videos?: { title?: string; views?: number; status?: string; published_at?: string }[];
};

function StatBox({
  label,
  value,
  sub,
  icon,
  color,
  bg,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
}) {
  return (
    <div className="stat-card" style={{ display: "flex", flexDirection: "column", gap: 8, padding: "18px 16px" }}>
      <div style={{ width: 36, height: 36, borderRadius: "var(--radius-md)", display: "flex", alignItems: "center", justifyContent: "center", background: bg }}>
        <span style={{ color }}>{icon}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.5px" }}>{value}</div>
      <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-disabled)", fontFamily: "var(--font-mono)" }}>{sub}</div>}
    </div>
  );
}

export function AdminStatsPage() {
  const { tenantId } = useTenant();

  const summaryQ = useQuery({
    queryKey: ["admin-dashboard-summary", tenantId],
    queryFn: () => apiFetch<DashSummary>("/api/dashboard/summary", { tenantId }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const analyticsQ = useQuery({
    queryKey: ["admin-analytics-all", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/analytics?limit=500", { tenantId }),
    staleTime: 60_000,
  });

  const tasksQ = useQuery({
    queryKey: ["admin-tasks-all", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=500", { tenantId }),
    staleTime: 30_000,
  });

  const isLoading = summaryQ.isLoading || analyticsQ.isLoading || tasksQ.isLoading;

  const d = summaryQ.data ?? {};
  const analytics = (analyticsQ.data?.analytics as Record<string, unknown>[] | undefined) ?? [];
  const tasks = (tasksQ.data?.tasks as Record<string, unknown>[] | undefined) ?? [];

  const totalViews = analytics.reduce((acc, r) => acc + Number(r.views ?? 0), 0);
  const totalLikes = analytics.reduce((acc, r) => acc + Number(r.likes ?? 0), 0);
  const shadowbanned = analytics.filter((r) => r.status === "shadowban" || r.status === "banned").length;

  const successRate = tasks.length > 0
    ? Math.round((tasks.filter((t) => t.status === "success").length / tasks.length) * 100)
    : 0;

  const topVideos = [...analytics]
    .sort((a, b) => Number(b.views ?? 0) - Number(a.views ?? 0))
    .slice(0, 8);

  const statusGroups: Record<string, number> = {};
  for (const t of tasks) {
    const st = String(t.status ?? "unknown");
    statusGroups[st] = (statusGroups[st] ?? 0) + 1;
  }

  const STATUS_COLOR: Record<string, string> = {
    success:   "var(--accent-green)",
    error:     "var(--accent-red)",
    rendering: "var(--accent-cyan)",
    pending:   "var(--accent-amber)",
    uploading: "var(--accent-purple)",
    cancelled: "var(--text-disabled)",
  };

  const statBoxes = [
    { label: "Всего задач",  value: tasks.length,              sub: `${successRate}% success rate`, icon: <Zap size={18} />,       color: "var(--accent-cyan)",   bg: "var(--accent-cyan-dim)" },
    { label: "Загрузок в YT", value: Number(d.total_uploads ?? 0),                                   icon: <Upload size={18} />,    color: "var(--accent-purple)", bg: "var(--accent-purple-dim)" },
    { label: "Профилей",     value: Number(d.total_profiles ?? 0),                                   icon: <Users size={18} />,     color: "var(--accent-amber)",  bg: "var(--accent-amber-dim)" },
    { label: "Просмотров",   value: totalViews.toLocaleString(),                                      icon: <TrendingUp size={18} />,color: "var(--accent-green)",  bg: "var(--accent-green-dim)" },
    { label: "Лайков",       value: totalLikes.toLocaleString(),                                      icon: <AreaChart size={18} />, color: "var(--accent-pink)",   bg: "var(--accent-pink-dim)" },
    { label: "Shadowban",    value: shadowbanned, sub: shadowbanned > 0 ? "Требует внимания" : "Всё OK", icon: <BarChart3 size={18} />, color: shadowbanned > 0 ? "var(--accent-red)" : "var(--accent-green)", bg: shadowbanned > 0 ? "var(--accent-red-dim)" : "var(--accent-green-dim)" },
  ];

  return (
    <div className="page-root">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">
            <BarChart3 size={20} color="var(--accent-cyan)" />
            Общая статистика платформы
          </h1>
          <p className="page-subtitle">Данные тенанта: <b>{tenantId}</b></p>
        </div>
      </div>

      {/* KPI row */}
      {isLoading ? (
        <SkeletonStatGrid count={6} />
      ) : (
        <div className="stats-grid-6" style={{ marginBottom: 20 }}>
          {statBoxes.map((b) => <StatBox key={b.label} {...b} />)}
        </div>
      )}

      <div className="stats-grid-2c">
        {/* Tasks by status */}
        <div className="content-card-nm">
          <div className="content-card-title">Задачи по статусам</div>
          {isLoading ? (
            <SkeletonTable rows={4} cols={2} />
          ) : Object.keys(statusGroups).length === 0 ? (
            <EmptyState title="Нет данных" />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {Object.entries(statusGroups).map(([status, count]) => {
                const pct = tasks.length > 0 ? (count / tasks.length) * 100 : 0;
                const color = STATUS_COLOR[status] ?? "var(--text-tertiary)";
                return (
                  <div key={status}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}>
                      <span style={{ color, fontFamily: "var(--font-mono)", fontWeight: 600 }}>{status}</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>
                        {count} ({pct.toFixed(0)}%)
                      </span>
                    </div>
                    <div style={{ background: "var(--bg-elevated)", borderRadius: 4, height: 6, overflow: "hidden" }}>
                      <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 4, transition: "width 0.5s" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Top videos */}
        <div className="content-card-nm">
          <div className="content-card-title">Топ видео по просмотрам</div>
          {isLoading ? (
            <SkeletonTable rows={5} cols={4} />
          ) : topVideos.length === 0 ? (
            <EmptyState title="Нет данных" />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Видео</th>
                  <th>Просмотры</th>
                  <th>Лайки</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {topVideos.map((v, i) => {
                  const status = String(v.status ?? "");
                  const sc = status === "shadowban" || status === "banned" ? "var(--accent-red)" : status === "ok" ? "var(--accent-green)" : "var(--text-tertiary)";
                  return (
                    <tr key={i}>
                      <td className="mono" style={{ color: "var(--text-disabled)" }}>{i + 1}</td>
                      <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 12 }}>
                        {String(v.video_id ?? v.title ?? "—")}
                      </td>
                      <td className="mono" style={{ color: "var(--accent-cyan)" }}>
                        {Number(v.views ?? 0).toLocaleString()}
                      </td>
                      <td className="mono" style={{ color: "var(--accent-purple)" }}>
                        {Number(v.likes ?? 0).toLocaleString()}
                      </td>
                      <td>
                        <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: sc }}>{status || "—"}</span>
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
