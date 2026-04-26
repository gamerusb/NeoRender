import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Eye, EyeOff, Loader2, LogIn, UserPlus, Zap } from "lucide-react";

type Mode = "login" | "register";

export function LoginPage() {
  const { login, register, isLoading } = useAuth();
  const navigate = useNavigate();

  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === "register") {
      if (!name.trim()) { setError("Введите имя"); return; }
      if (password.length < 6) { setError("Пароль минимум 6 символов"); return; }
      if (password !== passwordConfirm) { setError("Пароли не совпадают"); return; }
    }

    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(name, email, password);
      }
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка авторизации");
    }
  }

  return (
    <div style={styles.page}>
      {/* Background glow */}
      <div style={styles.bgGlow1} />
      <div style={styles.bgGlow2} />

      <div style={styles.card}>
        {/* Logo */}
        <div style={styles.logo}>
          <div style={styles.logoIcon}>N</div>
          <div>
            <div style={styles.logoName}>NeoRender</div>
            <div style={styles.logoSub}>pro platform</div>
          </div>
        </div>

        {/* Tabs */}
        <div style={styles.tabs}>
          <button
            type="button"
            style={{ ...styles.tab, ...(mode === "login" ? styles.tabActive : {}) }}
            onClick={() => { setMode("login"); setError(null); }}
          >
            <LogIn size={14} style={{ marginRight: 6 }} />
            Войти
          </button>
          <button
            type="button"
            style={{ ...styles.tab, ...(mode === "register" ? styles.tabActive : {}) }}
            onClick={() => { setMode("register"); setError(null); }}
          >
            <UserPlus size={14} style={{ marginRight: 6 }} />
            Регистрация
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={styles.form}>
          {mode === "register" && (
            <div style={styles.field}>
              <label style={styles.label}>Имя</label>
              <input
                style={styles.input}
                type="text"
                placeholder="Иван Иванов"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                required
              />
            </div>
          )}

          <div style={styles.field}>
            <label style={styles.label}>Email</label>
            <input
              style={styles.input}
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </div>

          <div style={styles.field}>
            <label style={styles.label}>Пароль</label>
            <div style={styles.passWrap}>
              <input
                style={{ ...styles.input, paddingRight: 44 }}
                type={showPass ? "text" : "password"}
                placeholder={mode === "register" ? "Минимум 6 символов" : "••••••••"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
              />
              <button
                type="button"
                style={styles.passEye}
                onClick={() => setShowPass((v) => !v)}
                tabIndex={-1}
                aria-label={showPass ? "Скрыть пароль" : "Показать пароль"}
              >
                {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          {mode === "register" && (
            <div style={styles.field}>
              <label style={styles.label}>Подтвердить пароль</label>
              <input
                style={styles.input}
                type={showPass ? "text" : "password"}
                placeholder="Повторите пароль"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
          )}

          {error && (
            <div style={styles.errorBox}>
              {error}
            </div>
          )}

          <button
            type="submit"
            style={{ ...styles.submitBtn, ...(isLoading ? styles.submitBtnDisabled : {}) }}
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 size={16} style={{ marginRight: 8, animation: "spin 1s linear infinite" }} />
            ) : (
              <Zap size={16} style={{ marginRight: 8 }} />
            )}
            {mode === "login" ? "Войти в аккаунт" : "Создать аккаунт"}
          </button>
        </form>

        {/* Demo hint */}
        <div style={styles.hint}>
          <div style={styles.hintTitle}>Demo аккаунты</div>
          <div style={styles.hintRow}>
            <span style={styles.hintRole}>Admin</span>
            <span style={styles.hintCreds}>admin@neorender.pro / admin123</span>
          </div>
          <div style={styles.hintRow}>
            <span style={styles.hintRole}>User</span>
            <span style={styles.hintCreds}>user@neorender.pro / user123</span>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    width: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--bg-deep)",
    position: "relative",
    overflow: "hidden",
  },
  bgGlow1: {
    position: "fixed",
    top: "-20%",
    left: "50%",
    transform: "translateX(-50%)",
    width: 600,
    height: 400,
    borderRadius: "50%",
    background: "radial-gradient(ellipse, rgba(94,234,212,0.06) 0%, transparent 70%)",
    pointerEvents: "none",
  },
  bgGlow2: {
    position: "fixed",
    bottom: "-10%",
    right: "10%",
    width: 400,
    height: 300,
    borderRadius: "50%",
    background: "radial-gradient(ellipse, rgba(242,63,93,0.05) 0%, transparent 70%)",
    pointerEvents: "none",
  },
  card: {
    position: "relative",
    zIndex: 1,
    width: 420,
    background: "var(--bg-surface)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-xl)",
    padding: "32px 32px 24px",
    boxShadow: "var(--shadow-lg)",
  },
  logo: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    marginBottom: 28,
  },
  logoIcon: {
    width: 44,
    height: 44,
    borderRadius: "var(--radius-md)",
    background: "linear-gradient(135deg, var(--accent-red) 0%, #C02040 100%)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontWeight: 700,
    fontSize: 18,
    color: "#fff",
    flexShrink: 0,
    boxShadow: "var(--shadow-md), inset 0 1px 0 rgba(255,255,255,0.1)",
    border: "1px solid rgba(255,255,255,0.08)",
  },
  logoName: {
    fontWeight: 700,
    fontSize: 18,
    letterSpacing: "-0.3px",
  },
  logoSub: {
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    color: "var(--text-tertiary)",
    marginTop: 1,
  },
  tabs: {
    display: "flex",
    gap: 4,
    background: "var(--bg-elevated)",
    borderRadius: "var(--radius-md)",
    padding: 4,
    marginBottom: 24,
  },
  tab: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "8px 0",
    borderRadius: "calc(var(--radius-md) - 2px)",
    border: "none",
    background: "transparent",
    color: "var(--text-secondary)",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
    transition: "all var(--transition)",
  },
  tabActive: {
    background: "var(--bg-active)",
    color: "var(--text-primary)",
    boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  field: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  label: {
    fontSize: 12,
    fontWeight: 600,
    color: "var(--text-secondary)",
    letterSpacing: "0.3px",
  },
  input: {
    background: "var(--bg-elevated)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-md)",
    padding: "10px 14px",
    color: "var(--text-primary)",
    fontSize: 14,
    fontFamily: "var(--font-sans)",
    width: "100%",
    outline: "none",
    transition: "border-color var(--transition)",
  },
  passWrap: {
    position: "relative",
  },
  passEye: {
    position: "absolute",
    right: 12,
    top: "50%",
    transform: "translateY(-50%)",
    background: "transparent",
    border: "none",
    color: "var(--text-tertiary)",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    padding: 4,
  },
  errorBox: {
    background: "var(--accent-red-dim)",
    border: "1px solid rgba(242,63,93,0.2)",
    borderRadius: "var(--radius-md)",
    padding: "10px 14px",
    color: "var(--accent-red)",
    fontSize: 13,
  },
  submitBtn: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "12px 0",
    background: "linear-gradient(135deg, var(--accent-cyan) 0%, #3DB9A8 100%)",
    color: "#0D1117",
    border: "none",
    borderRadius: "var(--radius-md)",
    fontWeight: 700,
    fontSize: 14,
    cursor: "pointer",
    transition: "all var(--transition)",
    marginTop: 4,
    letterSpacing: "0.2px",
  },
  submitBtnDisabled: {
    opacity: 0.6,
    cursor: "not-allowed",
  },
  hint: {
    marginTop: 20,
    padding: "14px 16px",
    background: "var(--bg-elevated)",
    border: "1px solid var(--border-subtle)",
    borderRadius: "var(--radius-md)",
  },
  hintTitle: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.8px",
    color: "var(--text-tertiary)",
    marginBottom: 8,
  },
  hintRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 4,
  },
  hintRole: {
    fontSize: 11,
    fontWeight: 600,
    fontFamily: "var(--font-mono)",
    color: "var(--accent-cyan)",
    background: "var(--accent-cyan-dim)",
    padding: "1px 7px",
    borderRadius: 4,
    minWidth: 40,
    textAlign: "center",
  },
  hintCreds: {
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    color: "var(--text-secondary)",
  },
};
