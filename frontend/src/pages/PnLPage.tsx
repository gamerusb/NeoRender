export function PnLPage() {
  return (
    <div className="page">
      <div className="pnl-summary">
        <div className="pnl-card"><div className="pnl-card-label">Доход / мес</div><div className="pnl-card-value pnl-positive">$4,820</div><div className="pnl-card-sub">RPM × views по каналам</div></div>
        <div className="pnl-card"><div className="pnl-card-label">Расход / мес</div><div className="pnl-card-value pnl-negative">$387</div><div className="pnl-card-sub">Прокси + антидетект + AI</div></div>
        <div className="pnl-card"><div className="pnl-card-label">Чистая прибыль</div><div className="pnl-card-value pnl-positive">$4,433</div><div className="pnl-card-sub">ROI: 1,145%</div></div>
        <div className="pnl-card"><div className="pnl-card-label">CPM средний</div><div className="pnl-card-value pnl-neutral">$2.40</div><div className="pnl-card-sub">По всем каналам</div></div>
      </div>
      <div className="settings-grid">
        <div>
          <div className="card section-gap">
            <div className="card-header"><span className="card-title">P&L по каналам</span></div>
            <div className="card-body-flush">
              <table className="data-table">
                <thead><tr><th>Канал</th><th>Views/мес</th><th>RPM</th><th>Доход</th><th>Расход</th><th>Profit</th></tr></thead>
                <tbody>
                  {[
                    { ch:"KR_shorts_01", views:"620K", rpm:"$2.80", rev:"$1,736", exp:"$32", profit:"$1,704", pos:true },
                    { ch:"KR_shorts_02", views:"480K", rpm:"$2.60", rev:"$1,248", exp:"$32", profit:"$1,216", pos:true },
                    { ch:"KR_shorts_04", views:"340K", rpm:"$2.40", rev:"$816",   exp:"$32", profit:"$784",   pos:true },
                    { ch:"KR_casino_03", views:"95K",  rpm:"$3.20", rev:"$304",   exp:"$32", profit:"$272",   pos:true },
                    { ch:"TH_react_01", views:"12K",   rpm:"$1.80", rev:"$22",    exp:"$28", profit:"-$6",    pos:false },
                  ].map((r) => (
                    <tr key={r.ch}>
                      <td>{r.ch}</td><td className="mono">{r.views}</td><td className="mono">{r.rpm}</td>
                      <td style={{ color:"var(--accent-green)", fontWeight:600, fontFamily:"var(--font-mono)" }}>{r.rev}</td>
                      <td className="mono">{r.exp}</td>
                      <td style={{ color:r.pos?"var(--accent-green)":"var(--accent-red)", fontWeight:700, fontFamily:"var(--font-mono)" }}>{r.profit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="card">
            <div className="card-header"><span className="card-title">Структура расходов</span></div>
            <div className="card-body">
              {[
                { label:"Прокси (8шт)", pct:52, val:"$200" },
                { label:"AdsPower",     pct:26, val:"$100" },
                { label:"Groq API",     pct:13, val:"$50"  },
                { label:"Серверы",      pct:10, val:"$37"  },
              ].map((r) => (
                <div key={r.label} className="pnl-bar-row">
                  <span className="pnl-bar-label">{r.label}</span>
                  <div className="pnl-bar-track"><div className="pnl-bar-fill pnl-bar-expense" style={{ width:`${r.pct}%` }}>{r.val}</div></div>
                  <div className="pnl-bar-value pnl-negative">{r.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div>
          <div className="card section-gap">
            <div className="card-header"><span className="card-title">Доход vs Расход</span></div>
            <div className="card-body">
              <div style={{ marginBottom:16 }}>
                <div style={{ display:"flex", justifyContent:"space-between", fontSize:12, color:"var(--text-tertiary)", marginBottom:6 }}><span>Доход</span><span style={{ color:"var(--accent-green)" }}>$4,820</span></div>
                <div style={{ height:24, background:"var(--bg-hover)", borderRadius:"var(--radius-sm)", overflow:"hidden" }}><div style={{ height:"100%", width:"92%", background:"var(--accent-green)", borderRadius:"var(--radius-sm)", opacity:0.7 }}></div></div>
              </div>
              <div style={{ marginBottom:16 }}>
                <div style={{ display:"flex", justifyContent:"space-between", fontSize:12, color:"var(--text-tertiary)", marginBottom:6 }}><span>Расход</span><span style={{ color:"var(--accent-red)" }}>$387</span></div>
                <div style={{ height:24, background:"var(--bg-hover)", borderRadius:"var(--radius-sm)", overflow:"hidden" }}><div style={{ height:"100%", width:"8%", background:"var(--accent-red)", borderRadius:"var(--radius-sm)", opacity:0.7 }}></div></div>
              </div>
              <div style={{ borderTop:"1px solid var(--border-subtle)", paddingTop:12, display:"flex", justifyContent:"space-between", alignItems:"baseline" }}>
                <span style={{ fontSize:14, fontWeight:600 }}>Net Profit</span>
                <span style={{ fontSize:24, fontWeight:700, color:"var(--accent-green)", fontFamily:"var(--font-mono)" }}>$4,433</span>
              </div>
              <div style={{ fontSize:11, color:"var(--text-tertiary)", textAlign:"right", marginTop:4 }}>Маржа: 92% · ROI: 1,145%</div>
            </div>
          </div>
          <div className="card">
            <div className="card-header"><span className="card-title">Настройки P&L</span></div>
            <div className="card-body">
              <div className="form-group"><label className="form-label">CPM по умолчанию ($)</label><input className="form-input" defaultValue="2.40" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <div className="form-group"><label className="form-label">Стоимость прокси ($/мес за шт)</label><input className="form-input" defaultValue="25" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <div className="form-group"><label className="form-label">Стоимость антидетект ($/мес)</label><input className="form-input" defaultValue="100" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <button className="btn btn-primary">Пересчитать</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
