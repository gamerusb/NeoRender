import { useAuth } from "@/auth/AuthContext";
import { useQuery } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import { EmptyState } from "@/components/EmptyState";
import { SkeletonStatGrid, SkeletonTable } from "@/components/Skeleton";
import {
  Activity,
  BarChart3,
  Clapperboard,
  HardDrive,
  ListOrdered,
  Megaphone,
  TrendingUp,
  Upload,
  Users2,
} from "lucide-react";

type StatCard = {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
};

const STATUS_COLOR: Record<string, string> = {
  success:   "var(--accent-green)",
  error:     "var(--accent-red)",
  rendering: "var(--accent-cyan)",
  uploading: "var(--accent-purple)",
  pending:   "var(--accent-amber)",
};

function StatCardBlock({ card }: { card: StatCard }) {
  return (
    <div className="stat-card" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 20 }}>
      <div style={{ width: 36, height: 36, borderRadius: "var(--radius-md)", display: "flex", alignItems: "center", justifyContent: "center", background: card.bg }}>
        <span style={{ color: card.color }}>{card.icon}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>{card.value}</div>
      <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{card.label}</div>
      {card.sub && <div style={{ fontSize: 11, color: "var(--text-disabled)", fontFamily: "var(--font-mono)" }}>{card.sub}</div>}
    </div>
  );
}

export function UsagePage() {
  const { user } = useAuth();
  const { tenantId } = useTenant();

  const summaryQ = useQuery({
    queryKey: ["dashboard-summary", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/dashboard/summary", { tenantId }),
    staleTime: 30_000,
  });

  const tasksQ = useQuery({
    queryKey: ["tasks-usage", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=200", { tenantId }),
    staleTime: 15_000,
  });

  if (!user) return null;

  const isLoading = summaryQ.isLoading || tasksQ.isLoading;
  const tasks = (tasksQ.data?.tasks as Record<string, unknown>[] | undefined) ?? [];

  const totalTasks = tasks.length;
  const successTasks = tasks.filter((t) => t.status === "success").length;
  const errorTasks = tasks.filter((t) => t.status === "error").length;
  const pendingTasks = tasks.filter((t) => t.status === "pending" || t.status === "rendering").length;
  const successRate = totalTasks > 0 ? Math.round((successTasks / totalTasks) * 100) : 0;

  const { usage, plan_limits } = user;

  const quotaCards: StatCard[] = [
    { label: "Задач сегодня",   value: usage.tasks_today,     sub: `из ${plan_limits.tasks_per_day} по тарифу`, icon: <Clapperboard size={18} />, color: "var(--accent-cyan)",   bg: "var(--accent-cyan-dim)" },
    { label: "Профилей активно", value: usage.profiles_used,  sub: `из ${plan_limits.profiles} по тарифу`,     icon: <Users2 size={18} />,       color: "var(--accent-purple)", bg: "var(--accent-purple-dim)" },
    { label: "Кампаний",        value: usage.campaigns_used,  sub: `из ${plan_limits.campaigns} по тарифу`,    icon: <Megaphone size={18} />,     color: "var(--accent-amber)",  bg: "var(--accent-amber-dim)" },
    { label: "Хранилище",       value: `${usage.storage_used_gb} GB`, sub: `из ${plan_limits.storage_gb} GB по тарифу`, icon: <HardDrive size={18} />, color: "var(--accent-green)", bg: "var(--accent-green-dim)" },
  ];

  const taskCards: StatCard[] = [
    { label: "Всего задач",   value: totalTasks,    icon: <Activity size={18} />,    color: "var(--accent-blue)",  bg: "var(--accent-blue-dim)" },
    { label: "Успешных",      value: successTasks,  sub: `${successRate}% success rate`, icon: <TrendingUp size={18} />, color: "var(--accent-green)", bg: "var(--accent-green-dim)" },
    { label: "В очереди",     value: pendingTasks,  icon: <BarChart3 size={18} />,   color: "var(--accent-cyan)",  bg: "var(--accent-cyan-dim)" },
    { label: "Ошибок",        value: errorTasks,    icon: <Upload size={18} />,      color: errorTasks > 0 ? "var(--accent-red)" : "var(--text-tertiary)", bg: errorTasks > 0 ? "var(--accent-red-dim)" : "var(--bg-elevated)" },
  ];

  const recentTasks = tasks.slice(0, 10);

  return (
    <div className="page-root">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Статистика использования</h1>
          <p className="page-subtitle">Реальные данные по вашему тенанту — {user.tenant_id}</p>
        </div>
      </div>

      {/* Quota cards */}
      <div className="page-section-label">Лимиты тарифа</div>
      {isLoading ? (
        <SkeletonStatGrid count={4} />
      ) : (
        <div className="stats-grid-4c">
          {quotaCards.map((c) => <StatCardBlock key={c.label} card={c} />)}
        </div>
      )}

      {/* Tasks stats */}
      <div className="page-section-label" style={{ marginTop: 28 }}>Задачи</div>
      {isLoading ? (
        <SkeletonStatGrid count={4} />
      ) : (
        <div className="stats-grid-4c">
          {taskCards.map((c) => <StatCardBlock key={c.label} card={c} />)}
        </div>
      )}

      {/* Recent tasks table */}
      <div className="content-card" style={{ marginTop: 8 }}>
        <div className="content-card-title">
          <ListOrdered size={16} color="var(--accent-cyan)" />
          Последние задачи
        </div>
        {isLoading ? (
          <SkeletonTable rows={5} cols={4} />
        ) : recentTasks.length === 0 ? (
          <EmptyState title="Задач пока нет" body="Запустите рендер или добавьте задачу в очередь" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Файл</th>
                <th>Статус</th>
                <th>Создана</th>
              </tr>
            </thead>
            <tbody>
              {recentTasks.map((task) => {
                const status = String(task.status ?? "");
                const statusColor = STATUS_COLOR[status] ?? "var(--text-tertiary)";
                return (
                  <tr key={String(task.id)}>
                    <td className="mono">#{String(task.id)}</td>
                    <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {String(task.original_video ?? "—")}
                    </td>
                    <td>
                      <span style={{ color: statusColor, fontFamily: "var(--font-mono)", fontSize: 11 }}>{status}</span>
                    </td>
                    <td style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                      {task.created_at ? new Date(String(task.created_at)).toLocaleDateString("ru-RU") : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
