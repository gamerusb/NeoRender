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
import "./admin.css";

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

type AuditEvent = {
  id: number;
  admin_email?: string;
  target_email?: string;
  action: string;
  old_value?: string;
  new_value?: string;
  created_at?: string;
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
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkAction, setBulkAction] = useState<"ban" | "unban" | "plan" | "role">("ban");
  const [bulkValue, setBulkValue] = useState("pro");

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
  const auditQ = useQuery({
    queryKey: ["admin-users-audit"],
    queryFn: async () => {
      const data = await apiFetch<{ events?: unknown }>("/api/admin/users/audit?limit=40");
      const raw = data.events;
      const list = Array.isArray(raw) ? raw : [];
      return { events: list as AuditEvent[] };
    },
    staleTime: 10_000,
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

  const roleMut = useMutation({
    mutationFn: ({ id, role }: { id: number; role: MockUser["role"] }) =>
      apiFetch(`/api/admin/users/${id}/role`, {
        method: "POST",
        body: JSON.stringify({ role }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  const bulkMut = useMutation({
    mutationFn: (payload: { user_ids: number[]; action: string; value?: string }) =>
      apiFetch<{ changed?: number; skipped?: number }>("/api/admin/users/bulk", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: async () => {
      setSelectedIds([]);
      await qc.invalidateQueries({ queryKey: ["admin-users"] });
      await qc.invalidateQueries({ queryKey: ["admin-users-audit"] });
    },
  });

  const users = usersQ.data?.users ?? [];
  const auditEvents = auditQ.data?.events ?? [];

  if (usersQ.isError) {
    return (
      <div className="page-root admin-shell">
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

  function changeRole(id: number, role: MockUser["role"]) {
    roleMut.mutate({ id, role });
  }

  function toggleSelectUser(id: number) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function toggleSelectAllFiltered(nextChecked: boolean) {
    if (nextChecked) {
      setSelectedIds(Array.from(new Set([...selectedIds, ...filtered.map((u) => u.id)])));
      return;
    }
    const removeSet = new Set(filtered.map((u) => u.id));
    setSelectedIds(selectedIds.filter((id) => !removeSet.has(id)));
  }

  function runBulkAction() {
    if (selectedIds.length === 0) return;
    const payload: { user_ids: number[]; action: string; value?: string } = {
      user_ids: selectedIds,
      action: bulkAction,
    };
    if (bulkAction === "plan" || bulkAction === "role") {
      payload.value = bulkValue;
    }
    bulkMut.mutate(payload);
  }

  const totalActive = users.filter((u) => u.status === "active").length;
  const totalBanned = users.filter((u) => u.status === "banned").length;
  const totalTasks = users.reduce((a, u) => a + (u.tasks_total ?? 0), 0);

  return (
    <div className="page-root admin-shell">
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

      <div className="admin-toolbar" style={{ opacity: selectedIds.length > 0 ? 1 : 0.75 }}>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Выбрано: {selectedIds.length}</span>
        <select className="form-input" style={{ maxWidth: 160 }} value={bulkAction} onChange={(e) => setBulkAction(e.target.value as "ban" | "unban" | "plan" | "role")}>
          <option value="ban">Ban</option>
          <option value="unban">Unban</option>
          <option value="plan">Set plan</option>
          <option value="role">Set role</option>
        </select>
        {(bulkAction === "plan" || bulkAction === "role") && (
          <select className="form-input" style={{ maxWidth: 160 }} value={bulkValue} onChange={(e) => setBulkValue(e.target.value)}>
            {bulkAction === "plan" ? (
              <>
                <option value="free">free</option>
                <option value="starter">starter</option>
                <option value="pro">pro</option>
                <option value="enterprise">enterprise</option>
              </>
            ) : (
              <>
                <option value="user">user</option>
                <option value="admin">admin</option>
              </>
            )}
          </select>
        )}
        <button type="button" className="btn btn-sm" disabled={selectedIds.length === 0 || bulkMut.isPending} onClick={runBulkAction}>
          {bulkMut.isPending ? "Применение..." : "Применить к выбранным"}
        </button>
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
                <th>
                  <input
                    type="checkbox"
                    checked={filtered.length > 0 && filtered.every((u) => selectedIds.includes(u.id))}
                    onChange={(e) => toggleSelectAllFiltered(e.target.checked)}
                    aria-label="Выбрать всех"
                  />
                </th>
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
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(user.id)}
                        onChange={() => toggleSelectUser(user.id)}
                        aria-label={`Выбрать ${user.email}`}
                      />
                    </td>
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
                      <select
                        style={{
                          background: "transparent",
                          border: "none",
                          fontFamily: "var(--font-mono)",
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: "pointer",
                          outline: "none",
                          padding: "2px 4px",
                          color: user.role === "admin" ? "var(--accent-red)" : "var(--text-secondary)",
                          opacity: roleMut.isPending ? 0.6 : 1,
                        }}
                        value={user.role}
                        onChange={(e) => void changeRole(user.id, e.target.value as MockUser["role"])}
                        disabled={roleMut.isPending}
                        title="Изменить роль"
                      >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
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

      <div className="card card-elevated" style={{ overflow: "hidden", marginTop: 12 }}>
        <div className="card-header">
          <span className="card-title">Audit log (последние изменения)</span>
        </div>
        <div className="card-body-flush">
          {auditQ.isLoading ? (
            <div className="empty-state">Загрузка...</div>
          ) : auditEvents.length === 0 ? (
            <EmptyState title="Событий пока нет" body="Изменения ролей, тарифов и статусов появятся здесь" />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Когда</th>
                  <th>Админ</th>
                  <th>Пользователь</th>
                  <th>Действие</th>
                  <th>Из</th>
                  <th>В</th>
                </tr>
              </thead>
              <tbody>
                {auditEvents.map((ev) => (
                  <tr key={ev.id}>
                    <td className="mono" style={{ color: "var(--text-disabled)", fontSize: 11 }}>#{ev.id}</td>
                    <td style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                      {ev.created_at ? new Date(ev.created_at).toLocaleString("ru-RU") : "—"}
                    </td>
                    <td className="mono" style={{ fontSize: 11 }}>{ev.admin_email || "—"}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{ev.target_email || "—"}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{ev.action || "—"}</td>
                    <td className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{ev.old_value || "—"}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{ev.new_value || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
