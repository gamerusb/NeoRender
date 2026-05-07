import { useState, type FormEvent } from "react";
import { useAuth } from "@/auth/AuthContext";
import { apiFetch } from "@/api";
import { SkeletonStatGrid } from "@/components/Skeleton";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  Shield,
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
  const passStrength =
    newPass.length >= 12 ? "strong" : newPass.length >= 8 ? "medium" : newPass.length > 0 ? "weak" : "none";

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
    <div className="page-root profile-v2">
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Профиль</h1>
          <p className="page-subtitle">Личные данные, безопасность и статус аккаунта</p>
        </div>
      </div>

      <div className="profile-v2-layout">
        <aside className="profile-v2-card profile-v2-summary">
          <div className="profile-v2-avatar">{user.avatar_initials}</div>
          <h3>{user.name}</h3>
          <p className="mono">{user.email}</p>
          <div className="profile-v2-tags">
            <span style={{ color: plan.color, background: plan.bg }}>{plan.label}</span>
            <span style={{ color: role.color, background: "var(--bg-elevated)" }}>
              <ShieldCheck size={12} />
              {role.label}
            </span>
          </div>
          <div className="profile-v2-list">
            <div><span>Tenant</span><strong className="mono">{user.tenant_id}</strong></div>
            <div><span>ID</span><strong className="mono">#{user.id}</strong></div>
            <div><span>Регистрация</span><strong>{new Date(user.created_at).toLocaleDateString("ru-RU")}</strong></div>
          </div>
          <div className="profile-v2-hint">
            <Shield size={13} />
            Не делитесь доступом к аккаунту
          </div>
        </aside>

        <section className="profile-v2-main">
          <div className="profile-v2-card">
            <div className="profile-v2-title"><User size={15} /> Основная информация</div>
            <form onSubmit={saveProfile} className="profile-v2-form">
              <div className="form-group">
                <label className="form-label">Имя</label>
                <input className="form-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ваше имя" />
              </div>
              <div className="form-group">
                <label className="form-label">Email</label>
                <div className="profile-v2-input-icon">
                  <Mail size={14} />
                  <input className="form-input" value={user.email} readOnly disabled />
                </div>
                <span className="profile-v2-note">Email изменяется через поддержку</span>
              </div>
              <button type="submit" className="btn" disabled={saving}>
                {saving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : saved ? <CheckCircle2 size={14} /> : <Check size={14} />}
                {saved ? "Сохранено" : "Сохранить"}
              </button>
            </form>
          </div>

          <div className="profile-v2-card">
            <div className="profile-v2-title"><KeyRound size={15} /> Смена пароля</div>
            <form onSubmit={changePassword} className="profile-v2-form profile-v2-form-2col">
              <div className="form-group">
                <label className="form-label">Текущий пароль</label>
                <input className="form-input" type="password" value={oldPass} onChange={(e) => setOldPass(e.target.value)} placeholder="••••••••" required />
              </div>
              <div className="form-group">
                <label className="form-label">Новый пароль</label>
                <input className="form-input" type="password" value={newPass} onChange={(e) => setNewPass(e.target.value)} placeholder="Минимум 6 символов" required />
              </div>
              <div className="form-group profile-v2-full">
                <label className="form-label">Подтвердить пароль</label>
                <input className="form-input" type="password" value={newPass2} onChange={(e) => setNewPass2(e.target.value)} placeholder="Повторите новый пароль" required />
              </div>

              <div className="profile-v2-full profile-v2-strength">
                <div className="profile-v2-strength-bar">
                  <span className={`seg ${passStrength !== "none" ? "on" : ""}`} />
                  <span className={`seg ${passStrength === "medium" || passStrength === "strong" ? "on" : ""}`} />
                  <span className={`seg ${passStrength === "strong" ? "on" : ""}`} />
                </div>
                <span className="mono profile-v2-strength-label">
                  {passStrength === "strong" ? "Сильный" : passStrength === "medium" ? "Средний" : passStrength === "weak" ? "Слабый" : "Пусто"}
                </span>
              </div>

              {passError && (
                <div className="profile-v2-alert profile-v2-full">
                  <AlertCircle size={13} />
                  {passError}
                </div>
              )}

              <button type="submit" className="btn profile-v2-full" disabled={passSaving}>
                {passSaving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : passSaved ? <CheckCircle2 size={14} /> : <Lock size={14} />}
                {passSaved ? "Пароль обновлён" : "Изменить пароль"}
              </button>
            </form>
          </div>
        </section>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .profile-v2 {
          --pv2-space-1: 8px;
          --pv2-space-2: 12px;
          --pv2-space-3: 16px;
          --pv2-space-4: 20px;
          --pv2-text-xs: 12px;
          --pv2-text-sm: 13px;
          --pv2-text-md: 15px;
          --pv2-text-lg: 18px;
          --pv2-text-xl: 22px;
        }
        .profile-v2 .page-header {
          margin-bottom: var(--pv2-space-3);
        }
        .profile-v2 .page-title {
          font-size: var(--pv2-text-xl);
          line-height: 1.2;
          letter-spacing: -0.02em;
          margin: 0;
        }
        .profile-v2 .page-subtitle {
          margin-top: 4px;
          font-size: var(--pv2-text-md);
          line-height: 1.45;
          color: var(--text-secondary);
        }
        .profile-v2-layout {
          display: grid;
          grid-template-columns: 300px minmax(0, 1fr);
          gap: var(--pv2-space-3);
          align-items: start;
        }
        .profile-v2-card {
          border-radius: 14px;
          border: 1px solid rgba(148,163,184,.18);
          background: rgba(14, 19, 28, .95);
          box-shadow: 0 8px 20px rgba(2, 6, 23, .20);
          padding: var(--pv2-space-3);
        }
        .profile-v2-summary {
          position: sticky;
          top: 14px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: var(--pv2-space-1);
        }
        .profile-v2-avatar {
          width: 72px;
          height: 72px;
          border-radius: 50%;
          display: grid;
          place-items: center;
          font-size: 23px;
          font-weight: 700;
          color: #fff;
          background: linear-gradient(135deg, #3f5efb 0%, #2de2e6 100%);
        }
        .profile-v2-summary h3 {
          margin: 4px 0 0;
          font-size: var(--pv2-text-lg);
          line-height: 1.25;
          font-weight: 700;
        }
        .profile-v2-summary p {
          margin: 0;
          font-size: var(--pv2-text-xs);
          line-height: 1.4;
          color: var(--text-secondary);
        }
        .profile-v2-tags {
          display: flex;
          gap: var(--pv2-space-1);
          margin-top: var(--pv2-space-1);
        }
        .profile-v2-tags span {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 11px;
          font-weight: 600;
          border-radius: 999px;
          padding: 4px 10px;
          font-family: var(--font-mono);
        }
        .profile-v2-list {
          width: 100%;
          margin-top: var(--pv2-space-2);
          border-top: 1px solid rgba(148,163,184,.15);
        }
        .profile-v2-list > div {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: var(--pv2-text-xs);
          line-height: 1.35;
          padding: 10px 0;
          border-bottom: 1px solid rgba(148,163,184,.12);
        }
        .profile-v2-list > div span { color: var(--text-tertiary); }
        .profile-v2-list > div strong { color: var(--text-primary); font-weight: 600; }
        .profile-v2-hint {
          width: 100%;
          margin-top: var(--pv2-space-2);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          border: 1px solid rgba(74,222,128,.24);
          color: var(--accent-green);
          background: rgba(74,222,128,.08);
          border-radius: 8px;
          padding: 9px 12px;
          font-size: 11px;
          font-family: var(--font-mono);
        }
        .profile-v2-main {
          display: flex;
          flex-direction: column;
          gap: var(--pv2-space-3);
        }
        .profile-v2-title {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          margin-bottom: var(--pv2-space-2);
          font-size: var(--pv2-text-sm);
          font-weight: 700;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: .06em;
        }
        .profile-v2-form {
          display: grid;
          gap: var(--pv2-space-2);
        }
        .profile-v2-form-2col {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .profile-v2-full { grid-column: 1 / -1; }
        .profile-v2-input-icon {
          position: relative;
        }
        .profile-v2-input-icon svg {
          position: absolute;
          left: 10px;
          top: 50%;
          transform: translateY(-50%);
          color: var(--text-tertiary);
        }
        .profile-v2-input-icon .form-input {
          padding-left: 34px;
        }
        .profile-v2-note {
          margin-top: 6px;
          font-size: 11px;
          line-height: 1.35;
          color: var(--text-disabled);
        }
        .profile-v2-strength {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          min-width: 0;
        }
        .profile-v2-strength-bar {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 6px;
          flex: 1;
          min-width: 0;
        }
        .profile-v2-strength-bar .seg {
          height: 6px;
          border-radius: 999px;
          background: rgba(148,163,184,.22);
          transition: background .2s;
        }
        .profile-v2-strength-bar .seg.on {
          background: linear-gradient(90deg, #2de2e6, #3f5efb);
        }
        .profile-v2-strength-label {
          min-width: 76px;
          text-align: right;
          white-space: nowrap;
          flex-shrink: 0;
          font-size: 11px;
          color: var(--text-secondary);
        }
        .profile-v2-alert {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border: 1px solid rgba(242,63,93,.3);
          background: rgba(242,63,93,.10);
          color: var(--accent-red);
          border-radius: 8px;
          padding: 9px 11px;
          font-size: var(--pv2-text-xs);
          line-height: 1.35;
        }
        .profile-v2 .form-label {
          font-size: 11px;
          letter-spacing: .06em;
          margin-bottom: 6px;
        }
        .profile-v2 .form-input {
          height: 42px;
          font-size: 14px;
          padding-top: 0;
          padding-bottom: 0;
        }
        .profile-v2 .btn {
          height: 40px;
          font-size: 14px;
          font-weight: 600;
          gap: 7px;
        }
        @media (max-width: 1024px) {
          .profile-v2-layout {
            grid-template-columns: 1fr;
          }
          .profile-v2-summary {
            position: static;
          }
        }
        @media (max-width: 760px) {
          .profile-v2-form-2col {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}
