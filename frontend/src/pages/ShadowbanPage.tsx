export function ShadowbanPage() {
  return (
    <div className="page">
      <div className="stats-grid-3">
        <div className="stat-card"><div className="stat-label">Порог velocity</div><div className="stat-value cyan">500</div><div style={{ fontSize:11, color:"var(--text-tertiary)", marginTop:4 }}>views / 4 часа</div></div>
        <div className="stat-card"><div className="stat-label">Окно проверки</div><div className="stat-value">5</div><div style={{ fontSize:11, color:"var(--text-tertiary)", marginTop:4 }}>последних видео</div></div>
        <div className="stat-card"><div className="stat-label">Каналов под флагом</div><div className="stat-value red">2</div></div>
      </div>
      <div className="settings-grid">
        <div>
          <div className="card section-gap">
            <div className="card-header"><span className="card-title">Каналы под наблюдением</span></div>
            <div className="card-body-flush">
              <table className="data-table">
                <thead><tr><th>Канал</th><th>Last 5 avg</th><th>Порог</th><th>Статус</th><th>С когда</th></tr></thead>
                <tbody>
                  <tr><td>KR_casino_03</td><td className="mono" style={{ color:"var(--accent-amber)" }}>420</td><td className="mono">500</td><td><span className="badge badge-warning"><span className="badge-dot"></span>Falling</span></td><td className="mono">2д назад</td></tr>
                  <tr><td>TH_react_01</td><td className="mono" style={{ color:"var(--accent-red)" }}>89</td><td className="mono">500</td><td><span className="badge badge-error"><span className="badge-dot"></span>Shadowban</span></td><td className="mono">5д назад</td></tr>
                </tbody>
              </table>
            </div>
          </div>
          <div className="card">
            <div className="card-header"><span className="card-title">Настройки детектора</span></div>
            <div className="card-body">
              <div className="form-group"><label className="form-label">Минимальный velocity (views/4h)</label><input className="form-input" defaultValue="500" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <div className="form-group"><label className="form-label">Количество видео для анализа</label><input className="form-input" defaultValue="5" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <div className="form-group"><label className="form-label">Min engagement rate (%)</label><input className="form-input" defaultValue="1.0" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <button className="btn btn-primary">Сохранить</button>
            </div>
          </div>
        </div>
        <div>
          <div className="card">
            <div className="card-header"><span className="card-title">История алертов</span></div>
            <div className="card-body" style={{ fontSize:12 }}>
              {[
                { date:"01.04 09:15", msg:"TH_react_01 velocity", val:"89", op:"< 500", color:"var(--accent-red)" },
                { date:"31.03 22:40", msg:"KR_casino_03 velocity", val:"420", op:"< 500", color:"var(--accent-amber)" },
                { date:"30.03 14:10", msg:"TH_react_01 engagement", val:"0.4%", op:"< 1.0%", color:"var(--accent-red)" },
              ].map((a,i) => (
                <div key={i} style={{ padding:"8px 0", borderBottom:"1px solid var(--border-subtle)" }}>
                  <span className="mono" style={{ color:"var(--text-tertiary)" }}>{a.date}</span> — {a.msg}{" "}
                  <span style={{ color:a.color }}>{a.val}</span> {a.op}
                </div>
              ))}
              <div style={{ padding:"8px 0" }}>
                <span className="mono" style={{ color:"var(--text-tertiary)" }}>28.03 11:00</span> — KR_shorts_03 восстановлен <span style={{ color:"var(--accent-green)" }}>✓</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
