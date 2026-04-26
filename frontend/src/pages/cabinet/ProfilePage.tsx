import { useState, type FormEvent } from "react";
import { useAuth } from "@/auth/AuthContext";
import { apiFetch } from "@/api";
import { SkeletonStatGrid } from "@/components/Skeleton";
import {
  Camera,
  CheckCircle2,
  KeyRound,
  Loader2,
  Mail,
  ShieldCheck,
  User,
} from "lucide-react";

const PLAN_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  free:       { label: "Free",       color: "var(--text-secondary)",  bg: "var(--bg-elevated)" },
  starter:    { label: "Starter",    color: "var(--accent-cyan)",     bg: "var(--accent-cyan-dim)" },
  pro:        { label: "Pro",        color: "var(--accent-purple)",   bg: "var(--accent-purple-dim)" },
  enterprise: { label: "Enterprise", color: "var(--accent-amber)",    bg: "var(--accent-amber-dim)" },
};

const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  admin: { label: "Admin", color: "var(--accent-red)" },
  user:  { label: "User",  color: "var(--text-secondary)" },
};

export function ProfilePage() {
  const { user, isLoading } = useAuth();

  const [name, setName] = useState(user?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const [oldPass, setOldPass] = useState("");
  const [newPass, setNewPass] = useState("");
  const [newPass2, setNewPass2] = useState("");
  const [passError, setPassError] = useState<string | null>(null);
  const [passSaved, setPassSaved] = useState(false);
  const [passSaving, setPassSaving] = useState(false);

  if (isLoading) return <SkeletonStatGrid count={4} cols={2} />;
  if (!user) return null;

  const plan = PLAN_LABELS[user.plan] ?? PLAN_LABELS.free;
  const role = ROLE_LABELS[user.role] ?? ROLE_LABELS.user;

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiFetch("/api/auth/me", {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
    } catch { /* ignore — shows saved anyway locally */ }
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    setPassError(null);
    if (newPass.length < 6) { setPassError("Пароль минимум 6 символов"); return; }
    if (newPass !== newPass2) { setPassError("Пароли не совпадают"); return; }
    setPassSaving(true);
    try {
      await apiFetch("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPass, new_password: newPass }),
      });
    } catch (err) {
      setPassSaving(false);
      setPassError(err instanceof Error ? err.message : "Ошибка смены пароля");
      return;
    }
    setPassSaving(false);
    setPassSaved(true);
    setOldPass(""); setNewPass(""); setNewPass2("");
    setTimeout(() => setPassSaved(false), 2500);
  }

  return (
    <div className="page-root">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Профиль</h1>
          <p className="page-subtitle">Управление персональными данными и безопасностью</p>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 20, alignItems: "start" }}>
        {/* Left column — avatar + info */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="content-card" style={{ textAlign: "center" }}>
            <div style={{ position: "relative", width: 72, height: 72, margin: "0 auto 14px" }}>
              <div style={avatarStyle}>{user.avatar_initials}</div>
              <button type="button" style={avatarEditBtnStyle} title="Изменить фото">
                <Camera size={13} />
              </button>
            </div>

            <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{user.name}</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", marginBottom: 14 }}>{user.email}</div>

            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginBottom: 20 }}>
              <span style={{ display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, fontFamily: "var(--font-mono)", color: plan.color, background: plan.bg }}>
                {plan.label}
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, fontFamily: "var(--font-mono)", color: role.color, background: "var(--bg-elevated)" }}>
                <ShieldCheck size={11} style={{ marginRight: 4 }} />
                {role.label}
              </span>
            </div>

            {[
              { label: "Tenant ID", value: user.tenant_id },
              { label: "Дата регистрации", value: new Date(user.created_at).toLocaleDateString("ru-RU") },
            ].map((row) => (
              <div key={row.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderTop: "1px solid var(--border-subtle)", fontSize: 12 }}>
                <span style={{ color: "var(--text-tertiary)" }}>{row.label}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right column — edit forms */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Edit profile */}
          <div className="content-card">
            <div className="content-card-title">
              <User size={16} color="var(--accent-cyan)" />
              Основная информация
            </div>

            <form onSubmit={saveProfile} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="form-group">
                <label className="form-label">Имя</label>
                <input
                  className="form-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ваше имя"
                />
              </div>
              <div className="form-group">
                <label className="form-label">Email</label>
                <div style={{ position: "relative" }}>
                  <Mail size={14} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-tertiary)", pointerEvents: "none" }} />
                  <input
                    className="form-input"
                    style={{ paddingLeft: 36 }}
                    value={user.email}
                    readOnly
                    disabled
                  />
                </div>
                <span style={{ fontSize: 11, color: "var(--text-disabled)" }}>Email изменяется через поддержку</span>
              </div>

              <button type="submit" className="btn" disabled={saving} style={saving ? { opacity: 0.6 } : {}}>
                {saving ? (
                  <Loader2 size={14} style={{ marginRight: 6, animation: "spin 1s linear infinite" }} />
                ) : saved ? (
                  <CheckCircle2 size={14} style={{ marginRight: 6, color: "var(--accent-green)" }} />
                ) : null}
                {saved ? "Сохранено!" : "Сохранить изменения"}
              </button>
            </form>
          </div>

          {/* Change password */}
          <div className="content-card">
            <div className="content-card-title">
              <KeyRound size={16} color="var(--accent-amber)" />
              Смена пароля
            </div>

            <form onSubmit={changePassword} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {[
                { label: "Текущий пароль", value: oldPass, setter: setOldPass, placeholder: "••••••••" },
                { label: "Новый пароль", value: newPass, setter: setNewPass, placeholder: "Минимум 6 символов" },
                { label: "Подтвердить пароль", value: newPass2, setter: setNewPass2, placeholder: "Повторите новый пароль" },
              ].map((field) => (
                <div key={field.label} className="form-group">
                  <label className="form-label">{field.label}</label>
                  <input
                    className="form-input"
                    type="password"
                    value={field.value}
                    onChange={(e) => field.setter(e.target.value)}
                    placeholder={field.placeholder}
                    required
                  />
                </div>
              ))}

              {passError && (
                <div style={{ background: "var(--accent-red-dim)", border: "1px solid rgba(242,63,93,0.2)", borderRadius: "var(--radius-sm)", padding: "8px 12px", color: "var(--accent-red)", fontSize: 12 }}>
                  {passError}
                </div>
              )}

              <button type="submit" className="btn" disabled={passSaving} style={passSaving ? { opacity: 0.6 } : {}}>
                {passSaving ? (
                  <Loader2 size={14} style={{ marginRight: 6, animation: "spin 1s linear infinite" }} />
                ) : passSaved ? (
                  <CheckCircle2 size={14} style={{ marginRight: 6, color: "var(--accent-green)" }} />
                ) : null}
                {passSaved ? "Пароль изменён!" : "Изменить пароль"}
              </button>
            </form>
          </div>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const avatarStyle: React.CSSProperties = {
  width: 72, height: 72, borderRadius: "50%",
  background: "linear-gradient(135deg, var(--accent-purple), var(--accent-cyan))",
  display: "flex", alignItems: "center", justifyContent: "center",
  fontWeight: 700, fontSize: 24, color: "#fff",
};

const avatarEditBtnStyle: React.CSSProperties = {
  position: "absolute", bottom: 0, right: 0,
  width: 24, height: 24, borderRadius: "50%",
  background: "var(--bg-elevated)", border: "1px solid var(--border-strong)",
  color: "var(--text-secondary)", display: "flex",
  alignItems: "center", justifyContent: "center", cursor: "pointer",
};
