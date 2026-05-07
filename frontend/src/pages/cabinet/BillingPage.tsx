import { useAuth, type UserPlan } from "@/auth/AuthContext";
import { SkeletonStatGrid } from "@/components/Skeleton";
import { CheckCircle2, CreditCard, Zap } from "lucide-react";
import { useNavigate } from "react-router-dom";

type PlanDef = {
  id: UserPlan;
  name: string;
  price: string;
  period: string;
  color: string;
  bg: string;
  accent: string;
  features: string[];
  limits: {
    tasks_per_day: number | string;
    profiles: number | string;
    campaigns: number | string;
    storage_gb: number | string;
  };
};

const PLANS: PlanDef[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    period: "навсегда",
    color: "var(--text-secondary)",
    bg: "var(--bg-elevated)",
    accent: "var(--text-tertiary)",
    features: ["10 задач в день", "3 профиля", "1 кампания", "5 GB хранилища"],
    limits: { tasks_per_day: 10, profiles: 3, campaigns: 1, storage_gb: 5 },
  },
  {
    id: "starter",
    name: "Starter",
    price: "$29",
    period: "/ мес",
    color: "var(--accent-cyan)",
    bg: "var(--accent-cyan-dim)",
    accent: "var(--accent-cyan)",
    features: ["50 задач в день", "10 профилей", "5 кампаний", "20 GB хранилища"],
    limits: { tasks_per_day: 50, profiles: 10, campaigns: 5, storage_gb: 20 },
  },
  {
    id: "pro",
    name: "Pro",
    price: "$79",
    period: "/ мес",
    color: "var(--accent-purple)",
    bg: "var(--accent-purple-dim)",
    accent: "var(--accent-purple)",
    features: ["100 задач в день", "20 профилей", "10 кампаний", "50 GB хранилища", "Приоритетная поддержка"],
    limits: { tasks_per_day: 100, profiles: 20, campaigns: 10, storage_gb: 50 },
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "$299",
    period: "/ мес",
    color: "var(--accent-amber)",
    bg: "var(--accent-amber-dim)",
    accent: "var(--accent-amber)",
    features: ["Без ограничений", "Неограниченно профилей", "Неограниченно кампаний", "1 TB хранилища", "Dedicated поддержка", "SLA 99.9%"],
    limits: { tasks_per_day: "∞", profiles: "∞", campaigns: "∞", storage_gb: 1000 },
  },
];

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const isHigh = pct >= 85;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, background: "var(--bg-elevated)", borderRadius: 4, height: 6, overflow: "hidden" }}>
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: isHigh ? "var(--accent-red)" : color,
            borderRadius: 4,
            transition: "width 0.5s ease",
          }}
        />
      </div>
      <span className="mono" style={{ minWidth: 40, textAlign: "right", fontSize: 11, color: "var(--text-tertiary)" }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

export function BillingPage() {
  const { user, isLoading } = useAuth();
  const navigate = useNavigate();

  if (isLoading) return <SkeletonStatGrid count={4} />;
  if (!user) return null;

  const currentPlan = PLANS.find((p) => p.id === user.plan) ?? PLANS[0];
  const { usage, plan_limits } = user;

  const limitItems = [
    { label: "Задач сегодня",    used: usage.tasks_today,       max: plan_limits.tasks_per_day, color: "var(--accent-cyan)" },
    { label: "Профилей",         used: usage.profiles_used,     max: plan_limits.profiles,      color: "var(--accent-purple)" },
    { label: "Кампаний",         used: usage.campaigns_used,    max: plan_limits.campaigns,     color: "var(--accent-amber)" },
    { label: "Хранилище (GB)",   used: usage.storage_used_gb,   max: plan_limits.storage_gb,    color: "var(--accent-green)" },
  ];

  return (
    <div className="page-root">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Тариф и оплата</h1>
          <p className="page-subtitle">Текущий план, лимиты использования и апгрейд</p>
        </div>
      </div>

      {/* Current plan + usage */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16, marginBottom: 16 }}>
        {/* Plan badge */}
        <div className="content-card" style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <div style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)", padding: "3px 12px", borderRadius: 20, marginBottom: 12, color: currentPlan.color, background: currentPlan.bg }}>
            {currentPlan.name}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 18 }}>
            <span style={{ fontSize: 28, fontWeight: 700 }}>{currentPlan.price}</span>
            <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>{currentPlan.period}</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20, width: "100%" }}>
            {currentPlan.features.map((f) => (
              <div key={f} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-secondary)" }}>
                <CheckCircle2 size={13} style={{ color: currentPlan.accent, flexShrink: 0 }} />
                <span>{f}</span>
              </div>
            ))}
          </div>

          {user.plan !== "enterprise" && (
            <button
              type="button"
              className="btn"
              style={{ background: currentPlan.bg, color: currentPlan.color, borderColor: currentPlan.accent, width: "100%", justifyContent: "center", marginTop: "auto" }}
              onClick={() => navigate("/pricing")}
            >
              <Zap size={14} />
              Апгрейд плана
            </button>
          )}
        </div>

        {/* Usage bars */}
        <div className="content-card">
          <div className="content-card-title">
            <CreditCard size={15} color="var(--accent-cyan)" />
            Использование ресурсов
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {limitItems.map((item) => (
              <div key={item.label} style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{item.label}</span>
                  <span style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}>
                    <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{item.used}</span>
                    <span style={{ color: "var(--text-disabled)" }}> / {item.max}</span>
                  </span>
                </div>
                <ProgressBar value={item.used} max={item.max} color={item.color} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Plans grid */}
      <div className="content-card">
        <div className="content-card-title">Доступные тарифы</div>
        <div className="plan-grid-4">
          {PLANS.map((plan) => {
            const isCurrent = plan.id === user.plan;
            return (
              <div
                key={plan.id}
                className="plan-card"
                style={isCurrent ? { borderColor: plan.accent, boxShadow: `0 0 0 1px ${plan.accent}40` } : {}}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)", padding: "2px 10px", borderRadius: 20, color: plan.color, background: plan.bg }}>{plan.name}</span>
                  {isCurrent && (
                    <span style={{ fontSize: 10, fontWeight: 600, background: "var(--accent-green-dim)", color: "var(--accent-green)", padding: "2px 8px", borderRadius: 20, fontFamily: "var(--font-mono)" }}>
                      Активен
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 14 }}>
                  {plan.price}
                  <span style={{ fontSize: 12, fontWeight: 400, color: "var(--text-tertiary)", marginLeft: 4 }}>{plan.period}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {plan.features.map((f) => (
                    <div key={f} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--text-secondary)" }}>
                      <CheckCircle2 size={12} style={{ color: plan.accent, flexShrink: 0 }} />
                      {f}
                    </div>
                  ))}
                </div>
                {!isCurrent && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{ marginTop: 16, borderColor: plan.accent, color: plan.color, width: "100%", justifyContent: "center" }}
                  >
                    Выбрать
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
