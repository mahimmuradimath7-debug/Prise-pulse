import { useState } from 'react'
import { api, usePoll, ago } from '../api'
import { Err, Feed, Kpi } from '../ui'

export default function Live({ open }) {
  const s = usePoll('/stream/status', 3000)
  const alerts = usePoll('/alerts?limit=20', 3000)
  const [sku, setSku] = useState('')
  const [toast, setToast] = useState('')
  const rows = s.data?.rows || []
  const trigger = async () => {
    const target = sku || rows[rows.length - 1]?.sku
    if (!target) return
    await api.post('/stream/flash', { sku: target, orders: 45 })
    setToast('Flash sale simulated: 45 orders in the last 90 seconds'); setTimeout(() => setToast(''), 2500)
    s.reload(); alerts.reload()
  }
  return (
    <>
      <div className="top">
        <div><h1>Live market</h1><div className="sub">Orders are counted in 5-minute windows that slide every minute. A product is flagged when its window holds at least {s.data?.min_orders ?? 10} orders and runs {s.data?.trigger_ratio ?? 3}x above its last-hour baseline.</div></div>
      </div>
      <Err e={s.error} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <Kpi label="Flash sales active" value={s.data?.active ?? '…'} />
        <Kpi label="Products tracked" value={rows.length} />
        <div className="card" style={{ gridColumn: 'span 2' }}>
          <div className="l muted">Simulate a demand spike</div>
          <div className="row" style={{ marginTop: 6 }}>
            <select value={sku} onChange={(e) => setSku(e.target.value)} aria-label="Product">
              <option value="">Pick a product…</option>
              {[...rows].sort((a, b) => a.name.localeCompare(b.name)).map((r) => <option key={r.sku} value={r.sku}>{r.name} ({r.sku})</option>)}
            </select>
            <button className="btn danger" disabled={!sku} onClick={trigger}>Trigger flash sale</button>
          </div>
        </div>
      </div>
      <div className="grid g21">
        <div className="card" style={{ padding: 0 }}>
          <div className="scroll" style={{ maxHeight: '65vh' }}>
            <table>
              <thead><tr><th>Product</th><th>Category</th><th className="r">Orders (5 min)</th><th className="r">Baseline</th><th className="r">Spike</th><th className="r">Price boost</th><th>Status</th></tr></thead>
              <tbody>
                {rows.slice(0, 40).map((r) => (
                  <tr key={r.sku} className="click" onClick={() => open(r.sku)}>
                    <td><b>{r.name}</b></td><td>{r.category}</td><td className="r">{r.window_orders}</td><td className="r">{r.baseline}</td>
                    <td className="r">x{r.ratio}</td><td className="r">{r.flash ? 'x' + r.multiplier : '–'}</td>
                    <td>{r.flash ? <span className="pill flash">flash sale</span> : <span className="pill ok">normal</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card"><h2>Alerts</h2>{alerts.data && <Feed items={alerts.data} ts={ago} />}</div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
