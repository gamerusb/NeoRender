import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api";
import { EmptyState } from "@/components/EmptyState";
import { SkeletonStatGrid, SkeletonTable } from "@/components/Skeleton";
import {
  Ban,
  CheckCircle2,
  ChevronDown,
  Crown,
  Loader2,
  RefreshCw,
  Search,
  Shield,
  UserCheck,
  Users,
} from "lucide-react";

type MockUser = {
  id: number;
  email: string;
  name: string;
  role: "admin" | "user";
  plan: string;
  tenant_id: string;
  status: "active" | "banned" | "pending";
  tasks_total?: number;
  profiles_used?: number;
  created_at: string;
  updated_at?: string;
};

function normalizeAdminUser(raw: unknown): MockUser {
  const u = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const usage =
    u.usage && typeof u.usage === "object" ? (u.usage as Record<string, unknown>) : {};
  const email = String(u.email ?? "").trim();
  const nameRaw = String(u.name ?? "").trim();
  const name = nameRaw || (email.includes("@") ? email.split("@")[0]! : email) || "—";
  const tenant_id = String(u.tenant_id ?? "default").trim() || "default";
  const id = typeof u.id === "number" && Number.isFinite(u.id) ? u.id : Number(u.id);
  const role: MockUser["role"] = u.role === "admin" ? "admin" : "user";
  const planStr = String(u.plan ?? "free");
  const plan: MockUser["plan"] =
    planStr === "starter" || planStr === "pro" || planStr === "enterprise" || planStr === "free"
      ? planStr
      : "free";
  const st = String(u.status ?? "active");
  const status: MockUser["status"] =
    st === "banned" || st === "pending" || st === "active" ? st : "active";
  const tasksFromUsage = usage.tasks_today;
  const profilesFromUsage = usage.profiles_used;
  const tasks_total =
    typeof u.tasks_total === "number" && Number.isFinite(u.tasks_total)
      ? u.tasks_total
      : Number(tasksFromUsage) || 0;
  const profiles_used =
    typeof u.profiles_used === "number" && Number.isFinite(u.profiles_used)
      ? u.profiles_used
      : Number(profilesFromUsage) || 0;
  return {
    id: Number.isFinite(id) ? id : 0,
    email,
    name,
    role,
    plan,
    tenant_id,
    status,
    tasks_total,
    profiles_used,
    created_at: String(u.created_at ?? ""),
    updated_at: u.updated_at != null ? String(u.updated_at) : undefined,
  };
}

const PLAN_COLOR: Record<string, { color: string; bg: string }> = {
  free:       { color: "var(--text-secondary)",  bg: "var(--bg-elevated)" },
  starter:    { color: "var(--accent-cyan)",     bg: "var(--accent-cyan-dim)" },
  pro:        { color: "var(--accent-purple)",   bg: "var(--accent-purple-dim)" },
  enterprise: { color: "var(--accent-amber)",    bg: "var(--accent-amber-dim)" },
};

const STATUS_COLOR: Record<string, { color: string; bg: string; label: string }> = {
  active:  { color: "var(--accent-green)",  bg: "var(--accent-green-dim)", label: "Активен" },
  banned:  { color: "var(--accent-red)",    bg: "var(--accent-red-dim)",   label: "Забанен" },
  pending: { color: "var(--accent-amber)",  bg: "var(--accent-amber-dim)", label: "Ожидает" },
};

export function AdminUsersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [planFilter, setPlanFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const usersQ = useQuery({
    queryKey: ["admin-users"],
    queryFn: async () => {
      const data = await apiFetch<{ users?: unknown }>("/api/admin/users?limit=500");
      const raw = data.users;
      const list = Array.isArray(raw) ? raw : [];
      return { users: list.map(normalizeAdminUser) };
    },
    staleTime: 15_000,
  });

  const banMut = useMutation({
    mutationFn: ({ id, banned }: { id: number; banned: boolean }) =>
      apiFetch(`/api/admin/users/${id}/${banned ? "ban" : "unban"}`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const planMut = useMutation({
    mutationFn: ({ id, plan }: { id: number; plan: string }) =>
      apiFetch(`/api/admin/users/${id}/plan`, {
        method: "POST",
        body: JSON.stringify({ plan }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const users = usersQ.data?.users ?? [];

  if (usersQ.isError) {
    return (
      <div className="page-root">
        <div className="page-header">
          <div className="page-header-text">
            <h1 className="page-title">
              <Shield size={20} color="var(--accent-red)" />
              Управление пользователями
            </h1>
            <p className="page-subtitle" style={{ color: "var(--accent-red)" }}>
              {usersQ.error instanceof Error ? usersQ.error.message : "Не удалось загрузить список"}
            </p>
          </div>
          <button type="button" className="btn" onClick={() => void usersQ.refetch()}>
            Повторить
          </button>
        </div>
      </div>
    );
  }

  const filtered = users.filter((u) => {
    const matchSearch =
      !search ||
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      u.name.toLowerCase().includes(search.toLowerCase()) ||
      u.tenant_id.toLowerCase().includes(search.toLowerCase());
    const matchPlan = planFilter === "all" || u.plan === planFilter;
    const matchStatus = statusFilter === "all" || u.status === statusFilter;
    return matchSearch && matchPlan && matchStatus;
  });

  function toggleBan(id: number, currentStatus: string) {
    banMut.mutate({ id, banned: currentStatus !== "banned" });
  }

  function changePlan(id: number, plan: string) {
    planMut.mutate({ id, plan });
  }

  const totalActive = users.filter((u) => u.status === "active").length;
  const totalBanned = users.filter((u) => u.status === "banned").length;
  const totalTasks = users.reduce((a, u) => a + (u.tasks_total ?? 0), 0);

  return (
    <div className="page-root">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">
            <Shield size={20} color="var(--accent-red)" />
            Управление пользователями
          </h1>
          <p className="page-subtitle">Просмотр, блокировка и изменение тарифов</p>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => void usersQ.refetch()}
          title="Обновить"
        >
          {usersQ.isFetching ? (
            <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
          ) : (
            <RefreshCw size={14} />
          )}
          Обновить
        </button>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>

      {/* Summary */}
      {usersQ.isLoading ? (
        <SkeletonStatGrid count={4} />
      ) : (
        <div className="stats-grid-4c">
          {[
            { label: "Всего пользователей", value: users.length,             icon: <Users size={18} />,     color: "var(--accent-blue)",  bg: "var(--accent-blue-dim)" },
            { label: "Активных",            value: totalActive,              icon: <UserCheck size={18} />, color: "var(--accent-green)", bg: "var(--accent-green-dim)" },
            { label: "Забаненных",          value: totalBanned,              icon: <Ban size={18} />,       color: "var(--accent-red)",   bg: "var(--accent-red-dim)" },
            { label: "Всего задач",         value: totalTasks.toLocaleString(), icon: <Crown size={18} />, color: "var(--accent-amber)", bg: "var(--accent-amber-dim)" },
          ].map((item) => (
            <div key={item.label} className="stat-card" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 20 }}>
              <div style={{ width: 36, height: 36, borderRadius: "var(--radius-md)", display: "flex", alignItems: "center", justifyContent: "center", background: item.bg }}>
                <span style={{ color: item.color }}>{item.icon}</span>
              </div>
              <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>{item.value}</div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{item.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
          <Search size={14} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-tertiary)", pointerEvents: "none" }} />
          <input
            className="form-input"
            style={{ paddingLeft: 34 }}
            placeholder="Поиск по email, имени, tenant..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {[
          { value: planFilter, setter: setPlanFilter, options: [["all","Все тарифы"],["free","Free"],["starter","Starter"],["pro","Pro"],["enterprise","Enterprise"]] },
          { value: statusFilter, setter: setStatusFilter, options: [["all","Все статусы"],["active","Активные"],["banned","Забаненные"],["pending","Ожидающие"]] },
        ].map((sel, i) => (
          <div key={i} style={{ position: "relative" }}>
            <select
              className="form-input"
              style={{ appearance: "none", paddingRight: 28, cursor: "pointer" }}
              value={sel.value}
              onChange={(e) => sel.setter(e.target.value)}
            >
              {sel.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <ChevronDown size={13} style={{ position: "absolute", right: 9, top: "50%", transform: "translateY(-50%)", color: "var(--text-tertiary)", pointerEvents: "none" }} />
          </div>
        ))}
        <span style={{ fontSize: 12, color: "var(--text-tertiary)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
          {filtered.length} из {users.length}
        </span>
      </div>

      {/* Table */}
      <div className="card card-elevated" style={{ overflow: "hidden" }}>
        {usersQ.isLoading ? (
          <SkeletonTable rows={6} cols={6} />
        ) : filtered.length === 0 ? (
          <EmptyState title="Пользователи не найдены" body="Попробуйте изменить параметры фильтра" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                {["ID", "Пользователь", "Роль", "Тариф", "Статус", "Задач", "Профилей", "Последний вход", "Действия"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((user) => {
                const plan = PLAN_COLOR[user.plan] ?? PLAN_COLOR.free;
                const status = STATUS_COLOR[user.status] ?? STATUS_COLOR.active;
                return (
                  <tr key={`${user.id}-${user.email}`}>
                    <td className="mono" style={{ color: "var(--text-disabled)", fontSize: 11 }}>#{user.id}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "linear-gradient(135deg, var(--accent-purple), var(--accent-cyan))", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 11, color: "#fff", flexShrink: 0 }}>
                          {user.name.slice(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{user.name}</div>
                          <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "var(--font-mono)" }}>{user.email}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      {user.role === "admin" ? (
                        <span className="badge badge-error">
                          <Shield size={10} />
                          admin
                        </span>
                      ) : (
                        <span className="badge badge-neutral">user</span>
                      )}
                    </td>
                    <td>
                      <select
                        style={{ background: "transparent", border: "none", fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, cursor: "pointer", outline: "none", padding: "2px 4px", color: plan.color }}
                        value={user.plan}
                        onChange={(e) => void changePlan(user.id, e.target.value)}
                      >
                        {["free", "starter", "pro", "enterprise"].map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <span style={{ display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)", padding: "2px 9px", borderRadius: 20, color: status.color, background: status.bg }}>
                        {status.label}
                      </span>
                    </td>
                    <td className="mono">{(user.tasks_total ?? 0).toLocaleString()}</td>
                    <td className="mono">{user.profiles_used ?? 0}</td>
                    <td style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                      {user.updated_at ? new Date(user.updated_at).toLocaleDateString("ru-RU") : "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{
                          color: user.status === "banned" ? "var(--accent-green)" : "var(--accent-red)",
                          borderColor: user.status === "banned" ? "rgba(74,222,128,0.3)" : "rgba(242,63,93,0.3)",
                          opacity: banMut.isPending ? 0.5 : 1,
                        }}
                        onClick={() => toggleBan(user.id, user.status)}
                        disabled={banMut.isPending || user.role === "admin"}
                        title={user.status === "banned" ? "Разбанить" : "Заблокировать"}
                      >
                        {user.status === "banned" ? <CheckCircle2 size={12} /> : <Ban size={12} />}
                        {user.status === "banned" ? "Разбан" : "Бан"}
                      </button>
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
