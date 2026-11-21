import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, usePoll, inr, num, ago } from '../api'
import { Kpi, Err, Feed, chartColors, Delta } from '../ui'

export default function Dashboard({ open, go }) {
  const d = usePoll('/dashboard', 4000)
  const alerts = usePoll('/alerts?limit=25', 4000)
  const changes = usePoll('/price-changes?limit=8', 4000)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const D = d.data

  const applyAll = async () => {
    setBusy(true)
    const r = await api.post('/reprice?apply=true')
    setToast(`Applied ${r.applied} price updates`)
    setTimeout(() => setToast(''), 2500)
    setBusy(false); d.reload(); changes.reload()
  }

  return (
    <>
      <div className="top">
        <div><h1>Pricing overview</h1><div className="sub">Live view of {D?.skus ?? '…'} products across the marketplace</div></div>
        <button className="btn primary" disabled={busy || !D} onClick={applyAll}>Apply {D?.pending_recommendations ?? 0} pending recommendations</button>
      </div>
      <Err e={d.error} />
      {D && (
        <>
          <div className="grid g4" style={{ marginBottom: 14 }}>
            <Kpi label="Est. revenue per day" value={inr(D.est_daily_revenue)} delta={D.revenue_uplift_pct} hint="vs static prices" />
            <Kpi label="Est. profit change" value={(D.profit_uplift_pct > 0 ? '+' : '') + D.profit_uplift_pct + '%'} hint="vs static prices" />
            <Kpi label="Price changes (24h)" value={num(D.price_changes_24h)} hint={D.settings.auto_mode ? 'auto-reprice on' : 'auto-reprice off'} />
            <Kpi label="Flash sales active" value={D.flash_active} hint={D.low_stock + ' products low on stock'} />
          </div>
          <div className="grid g21" style={{ marginBottom: 14 }}>
            <div className="card">
              <h2>Estimated daily revenue by category</h2>
              <div className="chartbox">
                <ResponsiveContainer>
                  <BarChart data={D.revenue_by_category}>
                    <CartesianGrid stroke="#eef1f6" vertical={false} />
                    <XAxis dataKey="category" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={(v) => '₹' + (v / 100000).toFixed(1) + 'L'} width={60} tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(v) => inr(v)} />
                    <Bar dataKey="revenue" fill={chartColors.primary} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="sub" style={{ marginTop: 6 }}>{D.note}</div>
            </div>
            <div className="card">
              <h2>Alerts</h2>
              {alerts.data && <Feed items={alerts.data} ts={ago} />}
            </div>
          </div>
          <div className="grid g2">
            <div className="card">
              <h2>Recent price changes</h2>
              <table>
                <thead><tr><th>Product</th><th className="r">From</th><th className="r">To</th><th>When</th><th>Source</th></tr></thead>
                <tbody>
                  {(changes.data || []).map((c) => (
                    <tr key={c.id} className="click" onClick={() => open(c.sku)}>
                      <td>{c.name}</td><td className="r">{inr(c.old_price)}</td>
                      <td className="r">{inr(c.new_price)} <Delta v={(c.new_price / c.old_price - 1) * 100} /></td>
                      <td className="muted">{ago(c.ts)}</td><td><span className="pill">{c.source}</span></td>
                    </tr>
                  ))}
                  {changes.data?.length === 0 && <tr><td colSpan="5" className="muted">No price changes yet. Apply the pending recommendations to get started.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h2>Back-test result</h2>
              {D.backtest ? (
                <div className="grid g3">
                  <Kpi label="Revenue" value={(D.backtest.revenue.uplift_pct > 0 ? '+' : '') + D.backtest.revenue.uplift_pct + '%'} />
                  <Kpi label="Profit" value={(D.backtest.profit.uplift_pct > 0 ? '+' : '') + D.backtest.profit.uplift_pct + '%'} />
                  <Kpi label="Stock-out days" value={'-' + D.backtest.stockout_sku_days.reduction_pct + '%'} />
                </div>
              ) : (
                <div className="muted">No back-test has been run yet.</div>
              )}
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={() => go('sim')}>Open simulation lab</button>
              </div>
              {D.low_stock_skus.length > 0 && (
                <>
                  <h2 style={{ marginTop: 16 }}>Running low</h2>
                  {D.low_stock_skus.map((s) => (
                    <div key={s.sku} className="row" style={{ padding: '3px 0' }}>
                      <a href="#" onClick={(e) => { e.preventDefault(); open(s.sku) }}>{s.name}</a>
                      <span className="spacer" /><span className="pill warn">{s.cover} days of cover</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </>
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
