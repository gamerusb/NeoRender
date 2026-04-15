import { Check, X } from "lucide-react";
import { uiIconProps } from "@/components/icons/uiIconProps";

const FEAT_ICO = uiIconProps(14);

export function PricingPage() {
  const plans = [
    {
      key:"starter", plan:"Starter", price:"$49", period:"/мес", featured:false,
      desc:"Для старта. Попробовать систему и понять workflow.",
      color:"var(--text-primary)",
      features:[
        {ok:true,text:"До 5 каналов"},{ok:true,text:"50 видео/день"},{ok:true,text:"Уникализатор + эффекты"},
        {ok:true,text:"Расписание заливов"},{ok:true,text:"Hash-проверка"},
        {ok:false,text:"Авто-залив"},{ok:false,text:"Shadowban детектор"},{ok:false,text:"P&L дашборд"},
      ],
      btnClass:"pricing-btn-outline", btnLabel:"Выбрать Starter",
    },
    {
      key:"pro", plan:"Pro", price:"$149", period:"/мес", featured:true,
      desc:"Полный арсенал. Для тех кто зарабатывает на органике.",
      color:"var(--accent-cyan)",
      features:[
        {ok:true,text:"До 20 каналов"},{ok:true,text:"200 видео/день"},{ok:true,text:"Всё из Starter"},
        {ok:true,text:"Авто-залив через антидетект"},{ok:true,text:"Shadowban детектор"},
        {ok:true,text:"A/B тесты + AI тексты"},{ok:true,text:"Контент-ротация"},{ok:true,text:"Прогрев каналов"},
      ],
      btnClass:"pricing-btn-primary", btnLabel:"Выбрать Pro",
    },
    {
      key:"agency", plan:"Agency", price:"$349", period:"/мес", featured:false,
      desc:"Для команд. Безлимит, API, приоритет.",
      color:"var(--accent-amber)",
      features:[
        {ok:true,text:"Безлимит каналов"},{ok:true,text:"Безлимит видео/день"},{ok:true,text:"Всё из Pro"},
        {ok:true,text:"P&L дашборд"},{ok:true,text:"Прокси авторотация"},
        {ok:true,text:"API доступ"},{ok:true,text:"Приоритетная поддержка"},{ok:true,text:"Мульти-пользователи"},
      ],
      btnClass:"pricing-btn-gold", btnLabel:"Выбрать Agency",
    },
  ];

  return (
    <div>
      <div className="lifetime-banner">
        <div>
          <div className="lifetime-text">Lifetime Deal — Pro навсегда</div>
          <div className="lifetime-sub">Ограниченно 100 мест. Вместо $149/мес — одноразовая оплата.</div>
        </div>
        <div style={{ textAlign:"right" }}>
          <div className="lifetime-price">$499</div>
          <div className="lifetime-slots">Осталось 23 места</div>
        </div>
      </div>

      <div className="pricing-grid">
        {plans.map((p) => (
          <div key={p.key} className={`pricing-card${p.featured?" featured":""}`}>
            <div className="pricing-plan">{p.plan}</div>
            <div className="pricing-price" style={{ color:p.color }}>{p.price}<span>{p.period}</span></div>
            <div className="pricing-desc">{p.desc}</div>
            <ul className="pricing-features">
              {p.features.map((f,i) => (
                <li key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {f.ok ? (
                    <Check {...FEAT_ICO} color="var(--accent-green)" strokeWidth={2.25} aria-hidden />
                  ) : (
                    <X {...FEAT_ICO} color="var(--text-disabled)" strokeWidth={2} aria-hidden />
                  )}
                  <span style={{ color:f.ok?undefined:"var(--text-disabled)" }}>{f.text}</span>
                </li>
              ))}
            </ul>
            <button className={`pricing-btn ${p.btnClass}`}>{p.btnLabel}</button>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">Сравнение тарифов</span></div>
        <div className="card-body-flush">
          <table className="data-table">
            <thead><tr><th>Функция</th><th style={{ textAlign:"center" }}>Starter</th><th style={{ textAlign:"center" }}>Pro</th><th style={{ textAlign:"center" }}>Agency</th></tr></thead>
            <tbody>
              {[
                ["Каналов","5","20","∞"],["Видео/день","50","200","∞"],
                ["Уникализатор","✓","✓","✓"],["Эффекты + Hash","✓","✓","✓"],
                ["Авто-залив","—","✓","✓"],["Shadowban","—","✓","✓"],
                ["A/B тесты","—","✓","✓"],["P&L дашборд","—","—","✓"],["API","—","—","✓"],
              ].map(([feat,...vals]) => (
                <tr key={feat}>
                  <td>{feat}</td>
                  {vals.map((v,i) => (
                    <td key={i} style={{ textAlign:"center", fontFamily:"var(--font-mono)", fontSize:12, color:v==="✓"?"var(--accent-green)":v==="∞"?"var(--accent-green)":v==="—"?"var(--text-disabled)":undefined }}>{v}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
