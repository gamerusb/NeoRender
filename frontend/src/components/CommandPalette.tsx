import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AreaChart,
  CalendarDays,
  Captions,
  Clapperboard,
  Crosshair,
  Download,
  Flame,
  Globe2,
  LayoutDashboard,
  LineChart,
  ListOrdered,
  Megaphone,
  Network,
  Play,
  Search,
  Settings,
  Tags,
  Users,
} from "lucide-react";
import { uiIconProps } from "@/components/icons/uiIconProps";

interface CmdItem {
  id: string;
  label: string;
  icon: JSX.Element;
  to?: string;
  action?: () => void;
  shortcut?: string;
  section: "nav" | "action" | "settings";
}

const C = uiIconProps(16);
const C18 = uiIconProps(18);

interface Props {
  open: boolean;
  onClose: () => void;
  onToast?: (type: string, msg: string) => void;
}

export function CommandPalette({ open, onClose, onToast }: Props) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const allItems: CmdItem[] = [
    { id: "dashboard", label: "Главная", icon: <LayoutDashboard {...C} aria-hidden />, to: "/dashboard", shortcut: "G H", section: "nav" },
    { id: "uniqualizer", label: "Уникализатор", icon: <Clapperboard {...C} aria-hidden />, to: "/uniqualizer", shortcut: "G U", section: "nav" },
    { id: "analytics", label: "Аналитика каналов", icon: <LineChart {...C} aria-hidden />, to: "/analytics", shortcut: "G A", section: "nav" },
    { id: "shadowban", label: "Shadowban детектор", icon: <Crosshair {...C} aria-hidden />, to: "/shadowban", section: "nav" },
    { id: "research", label: "Контент-ресёрч", icon: <Search {...C} aria-hidden />, to: "/research", shortcut: "G R", section: "nav" },
    { id: "downloader", label: "Загрузчик видео", icon: <Download {...C} aria-hidden />, to: "/downloader", section: "nav" },
    { id: "subtitles", label: "AI Субтитры", icon: <Captions {...C} aria-hidden />, to: "/subtitles", section: "nav" },
    { id: "queue", label: "Очередь задач", icon: <ListOrdered {...C} aria-hidden />, to: "/queue", shortcut: "G Q", section: "nav" },
    { id: "campaigns", label: "Кампании", icon: <Megaphone {...C} aria-hidden />, to: "/campaigns", section: "nav" },
    { id: "pnl", label: "P&L дашборд", icon: <AreaChart {...C} aria-hidden />, to: "/pnl", shortcut: "G P", section: "nav" },
    { id: "uploads", label: "История заливов", icon: <CalendarDays {...C} aria-hidden />, to: "/uploads", section: "nav" },
    { id: "proxy", label: "Прокси-мониторинг", icon: <Globe2 {...C} aria-hidden />, to: "/proxy", section: "nav" },
    { id: "warmup", label: "Прогрев каналов", icon: <Flame {...C} aria-hidden />, to: "/warmup", section: "nav" },
    { id: "accounts", label: "Аккаунты", icon: <Users {...C} aria-hidden />, to: "/accounts", section: "nav" },
    { id: "pricing", label: "Тарифы", icon: <Tags {...C} aria-hidden />, to: "/pricing", section: "nav" },
    { id: "render", label: "Запустить рендер", icon: <Play {...C} aria-hidden />, action: () => onToast?.("info", "Запуск рендера..."), shortcut: "⌘ ↵", section: "action" },
    { id: "proxycheck", label: "Проверить все прокси", icon: <Network {...C} aria-hidden />, action: () => onToast?.("info", "Проверка прокси..."), section: "action" },
    { id: "settings", label: "Открыть настройки", icon: <Settings {...C} aria-hidden />, to: "/settings", shortcut: "⌘ ,", section: "settings" },
  ];

  const filtered = query
    ? allItems.filter((i) => i.label.toLowerCase().includes(query.toLowerCase()))
    : allItems;

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery("");
      setSelected(0);
    }
  }, [open]);

  useEffect(() => {
    setSelected(0);
  }, [query]);

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[selected];
      if (item) activate(item);
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  function activate(item: CmdItem) {
    if (item.to) {
      navigate(item.to);
    } else if (item.action) {
      item.action();
    }
    onClose();
  }

  if (!open) return null;

  const sections = [
    { key: "nav", label: "Навигация" },
    { key: "action", label: "Действия" },
    { key: "settings", label: "Настройки" },
  ] as const;

  let cursor = 0;
  const sectionItems = sections.map((sec) => {
    const items = filtered.filter((i) => i.section === sec.key);
    const start = cursor;
    cursor += items.length;
    return { ...sec, items, start };
  });

  return (
    <div className="cmdk-overlay show" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cmdk">
        <div className="cmdk-input-wrap">
          <Search {...C18} className="cmdk-input-search-ico" color="var(--text-tertiary)" aria-hidden />
          <input
            ref={inputRef}
            className="cmdk-input"
            placeholder="Поиск страниц, действий, настроек..."
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
          />
          <kbd className="topbar-search-key" style={{ margin: 0 }}>ESC</kbd>
        </div>
        <div className="cmdk-list">
          {sectionItems.map((sec) =>
            sec.items.length > 0 ? (
              <div key={sec.key}>
                <div className="cmdk-section-label">{sec.label}</div>
                {sec.items.map((item, i) => {
                  const idx = sec.start + i;
                  return (
                    <div
                      key={item.id}
                      className={`cmdk-item${idx === selected ? " selected" : ""}`}
                      onClick={() => activate(item)}
                      onMouseEnter={() => setSelected(idx)}
                    >
                      <div className="cmdk-item-icon">{item.icon}</div>
                      {item.label}
                      {item.shortcut && (
                        <span className="cmdk-item-shortcut">{item.shortcut}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : null
          )}
          {filtered.length === 0 && (
            <div style={{ padding: "24px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
              Ничего не найдено
            </div>
          )}
        </div>
        <div className="cmdk-footer">
          <div><kbd className="cmdk-footer-kbd">↑↓</kbd> навигация</div>
          <div><kbd className="cmdk-footer-kbd">↵</kbd> выбрать</div>
          <div><kbd className="cmdk-footer-kbd">ESC</kbd> закрыть</div>
        </div>
      </div>
    </div>
  );
}
