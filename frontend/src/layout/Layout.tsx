import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useTenant } from "@/tenant/TenantContext";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useEffect, useState, useCallback } from "react";
import {
  AlertTriangle,
  AreaChart,
  BadgeCheck,
  Bell,
  CalendarDays,
  Captions,
  ChevronsLeft,
  ChevronsRight,
  CircleCheck,
  Clapperboard,
  Crosshair,
  Download,
  Flame,
  Globe2,
  Info,
  LayoutDashboard,
  LineChart,
  ListOrdered,
  Megaphone,
  ReceiptText,
  RefreshCw,
  Search,
  Settings,
  Tags,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { CommandPalette } from "@/components/CommandPalette";
import { navIconProps, uiIconProps } from "@/components/icons/uiIconProps";
import pkg from "../../package.json";

const NAV = navIconProps();

const pageTitles: Record<string, string> = {
  "/dashboard": "Главная",
  "/uniqualizer": "Уникализатор",
  "/analytics": "Аналитика каналов",
  "/shadowban": "Shadowban детектор",
  "/pnl": "P&L дашборд",
  "/uploads": "История заливов",
  "/queue": "Очередь задач",
  "/research": "Контент-ресёрч",
  "/downloader": "Загрузчик видео",
  "/subtitles": "AI Субтитры",
  "/campaigns": "Кампании",
  "/proxy": "Прокси-мониторинг",
  "/warmup": "Прогрев каналов",
  "/accounts": "Аккаунты",
  "/profile-links": "Profile Links",
  "/profile-jobs": "Profile Jobs",
  "/pricing": "Тарифы",
  "/settings": "Настройки",
  "/cabinet/profile": "Профиль",
  "/cabinet/usage": "Использование",
  "/cabinet/billing": "Биллинг",
  "/admin/users": "Пользователи",
  "/admin/stats": "Статистика",
  "/admin/system": "Система",
};

type NavSection = {
  title: string;
  items: { to: string; icon: JSX.Element; label: string; badge?: number }[];
};

function useNavSections(tenantId: string): NavSection[] {
  const analyticsQ = useQuery({
    queryKey: ["analytics-nav-badge", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/analytics?limit=500", { tenantId }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const tasksQ = useQuery({
    queryKey: ["tasks-nav-badge", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=200", { tenantId }),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
  const rows = (analyticsQ.data?.analytics as { status?: string }[] | undefined) ?? [];
  const alertCount = rows.filter((r) => r.status === "shadowban" || r.status === "banned").length;
  const taskRows = (tasksQ.data?.tasks as { status?: string }[] | undefined) ?? [];
  const activeCount = taskRows.filter((t) => t.status === "rendering" || t.status === "uploading" || t.status === "pending").length;

  return [
    {
      title: "Основное",
      items: [
        { to: "/dashboard", label: "Главная", icon: <LayoutDashboard {...NAV} aria-hidden /> },
        { to: "/uniqualizer", label: "Уникализатор", icon: <Clapperboard {...NAV} aria-hidden /> },
        { to: "/research", label: "Контент-ресёрч", icon: <Search {...NAV} aria-hidden /> },
        { to: "/downloader", label: "Загрузчик", icon: <Download {...NAV} aria-hidden /> },
        { to: "/subtitles", label: "AI Субтитры", icon: <Captions {...NAV} aria-hidden /> },
        { to: "/queue", label: "Очередь", badge: activeCount > 0 ? activeCount : undefined, icon: <ListOrdered {...NAV} aria-hidden /> },
      ],
    },
    {
      title: "Каналы",
      items: [
        { to: "/analytics", label: "Аналитика", badge: alertCount > 0 ? alertCount : undefined, icon: <LineChart {...NAV} aria-hidden /> },
        { to: "/shadowban", label: "Shadowban", badge: alertCount > 0 ? alertCount : undefined, icon: <Crosshair {...NAV} aria-hidden /> },
        { to: "/campaigns", label: "Кампании", icon: <Megaphone {...NAV} aria-hidden /> },
        { to: "/pnl", label: "P&L", icon: <AreaChart {...NAV} aria-hidden /> },
      ],
    },
    {
      title: "Инфраструктура",
      items: [
        { to: "/uploads", label: "История заливов", icon: <CalendarDays {...NAV} aria-hidden /> },
        { to: "/proxy", label: "Прокси", icon: <Globe2 {...NAV} aria-hidden /> },
        { to: "/warmup", label: "Прогрев", icon: <Flame {...NAV} aria-hidden /> },
        { to: "/accounts", label: "Аккаунты", icon: <Users {...NAV} aria-hidden /> },
        { to: "/pricing", label: "Тарифы", icon: <Tags {...NAV} aria-hidden /> },
        { to: "/settings", label: "Настройки", icon: <Settings {...NAV} aria-hidden /> },
      ],
    },
    {
      title: "Кабинет",
      items: [
        { to: "/cabinet/profile", label: "Профиль", icon: <Users {...NAV} aria-hidden /> },
        { to: "/cabinet/usage", label: "Использование", icon: <BadgeCheck {...NAV} aria-hidden /> },
        { to: "/cabinet/billing", label: "Биллинг", icon: <ReceiptText {...NAV} aria-hidden /> },
      ],
    },
    {
      title: "Админ",
      items: [
        { to: "/admin/users", label: "Пользователи", icon: <Users {...NAV} aria-hidden /> },
        { to: "/admin/stats", label: "Статистика", icon: <LineChart {...NAV} aria-hidden /> },
        { to: "/admin/system", label: "Система", icon: <Settings {...NAV} aria-hidden /> },
      ],
    },
  ];
}

function logoVersionLabel(version: string): string {
  const [major = "0", minor = "0"] = version.split(".");
  return `v${major}.${minor} pro`;
}

const _pkgVersion = pkg.version ?? "0.3";

export function Layout() {
  const { tenantId, setTenantId } = useTenant();
  const qc = useQueryClient();
  const navSections = useNavSections(tenantId);
  const [tenantDraft, setTenantDraft] = useState(tenantId);
  const [tenantMode, setTenantMode] = useState<"default" | "custom">(
    tenantId === "default" ? "default" : "custom"
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; type: string; msg: string }[]>([]);
  const location = useLocation();
  const navigate = useNavigate();

  const pageTitle =
    pageTitles[location.pathname] ??
    navSections.flatMap((s) => s.items).find((n) => location.pathname.startsWith(n.to))?.label ??
    "NeoRender";

  useEffect(() => {
    setTenantDraft(tenantId);
    setTenantMode(tenantId === "default" ? "default" : "custom");
  }, [tenantId]);

  const addToast = useCallback((type: string, msg: string) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, type, msg }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const refresh = useCallback(async () => {
    await qc.invalidateQueries();
    addToast("info", "Данные обновлены");
  }, [qc, addToast]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCmdkOpen((v) => !v);
      }
      if (e.key === "Escape") setCmdkOpen(false);
      if (e.ctrlKey && e.key === "[") {
        e.preventDefault();
        setSidebarCollapsed((c) => !c);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const TICO = uiIconProps(16);
  const toastIcons: Record<string, JSX.Element> = {
    success: <CircleCheck {...TICO} color="var(--accent-green)" aria-hidden />,
    error: <XCircle {...TICO} color="var(--accent-red)" aria-hidden />,
    warning: <AlertTriangle {...TICO} color="var(--accent-amber)" aria-hidden />,
    info: <Info {...TICO} color="var(--accent-cyan)" aria-hidden />,
  };

  return (
    <div className={`container${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      {/* Toast container */}
      <div className="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            <span className="toast-icon-wrap">{toastIcons[t.type] ?? toastIcons.info}</span>
            <span style={{ flex: 1 }}>{t.msg}</span>
            <button
              type="button"
              className="toast-dismiss"
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
              aria-label="Закрыть"
            >
              <X {...uiIconProps(14)} strokeWidth={2} />
            </button>
          </div>
        ))}
      </div>

      {/* Command Palette */}
      <CommandPalette open={cmdkOpen} onClose={() => setCmdkOpen(false)} onToast={addToast} />

      {/* Keyboard hint */}
      <div className="kbd-hint">
        <kbd>Ctrl</kbd><kbd>K</kbd> поиск
      </div>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-logo">N</div>
          <div className="sidebar-brand-text">
            <div className="sidebar-brand-name">NeoRender</div>
            <div className="sidebar-brand-version">{logoVersionLabel(_pkgVersion)}</div>
          </div>
        </div>

        <button
          type="button"
          className="sidebar-collapse-btn"
          onClick={() => setSidebarCollapsed((c) => !c)}
          title={sidebarCollapsed ? "Развернуть" : "Свернуть"}
        >
          {sidebarCollapsed ? (
            <ChevronsRight {...uiIconProps(16)} aria-hidden />
          ) : (
            <ChevronsLeft {...uiIconProps(16)} aria-hidden />
          )}
        </button>

        <nav className="sidebar-nav" style={{ display: "flex", flexDirection: "column" }}>
          {navSections.map((section) => (
            <div key={section.title}>
              <div className="nav-section-title">{section.title}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
                >
                  <span className="nav-icon" style={{ width: 18, height: 18 }}>
                    {item.icon}
                  </span>
                  <span className="nav-item-label">{item.label}</span>
                  {item.badge != null && (
                    <span className="nav-badge">{item.badge}</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="antidetect-select">
          <label className="antidetect-label">Tenant</label>
          <div className="tenant-select-wrap">
            <select
              className="tenant-select-native"
              value={tenantMode === "default" ? "default" : "__custom__"}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "default") {
                  setTenantMode("default");
                  setTenantId("default");
                  setTenantDraft("default");
                  void qc.invalidateQueries();
                } else {
                  setTenantMode("custom");
                  setTenantDraft(tenantId !== "default" ? tenantId : "");
                }
              }}
            >
              <option value="default">default</option>
              <option value="__custom__">Свой workspace…</option>
            </select>
          </div>
          {tenantMode === "custom" && (
            <div className="tenant-custom-block">
              <input
                className="form-input mono"
                value={tenantDraft}
                onChange={(e) => setTenantDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const next = tenantDraft.trim() || "default";
                    setTenantId(next);
                    void qc.invalidateQueries();
                  }
                }}
                placeholder="team_kr_01"
                style={{ fontSize: 12, marginBottom: 6 }}
              />
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  const next = tenantDraft.trim() || "default";
                  setTenantId(next);
                  void qc.invalidateQueries();
                }}
              >
                Применить
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main */}
      <main className="main">
        <header className="topbar">
          {/* Breadcrumbs */}
          <div className="breadcrumbs">
            <span className="breadcrumb-item" onClick={() => navigate("/dashboard")}>NeoRender</span>
            <span className="breadcrumb-sep">/</span>
            <span className="breadcrumb-current">{pageTitle}</span>
          </div>

          <div className="topbar-spacer" />

          {/* Search bar */}
          <div className="topbar-search" onClick={() => setCmdkOpen(true)}>
            <Search {...uiIconProps(15)} className="topbar-search-ico" aria-hidden />
            Найти что угодно...
            <span className="topbar-search-key">⌘K</span>
          </div>

          {/* Actions */}
          <div className="topbar-actions">
            <button type="button" className="topbar-btn" title="Обновить" onClick={() => void refresh()}>
              <RefreshCw {...uiIconProps(15)} aria-hidden />
            </button>
            <button
              type="button"
              className="topbar-btn"
              title="Уведомления"
              style={{ position: "relative" }}
              onClick={() => addToast("info", "3 новых уведомления")}
            >
              <Bell {...uiIconProps(15)} aria-hidden />
              <div className="notif-dot" />
            </button>
            <div className="topbar-avatar">{tenantId.slice(0, 1).toUpperCase()}</div>
          </div>
        </header>

        <div className="content react-main-stack">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
