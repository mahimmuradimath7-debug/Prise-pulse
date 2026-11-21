import { useState } from 'react'
import { ComposedChart, Line, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend, AreaChart, Area } from 'recharts'
import { api, usePoll, inr, pct, num, ago } from '../api'
import { Err, Delta, chartColors } from '../ui'

export default function Products({ focusSku, setFocusSku }) {
  if (focusSku) return <Detail sku={focusSku} back={() => setFocusSku(null)} />
  return <List open={setFocusSku} />
}

function List({ open }) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [sort, setSort] = useState('change')
  const { data, error } = usePoll('/products', 4000)
  let rows = (data?.products || []).filter((p) => (!cat || p.category === cat) && (!q || (p.name + p.sku).toLowerCase().includes(q.toLowerCase())))
  const keys = { change: (p) => -Math.abs(p.change_pct), cover: (p) => p.days_of_cover, price: (p) => -p.current_price, name: (p) => p.name }
  rows = [...rows].sort((a, b) => (keys[sort](a) > keys[sort](b) ? 1 : -1))
  return (
    <>
      <div className="top"><div><h1>Products</h1><div className="sub">Click a product to see how its price is built and to apply it.</div></div></div>
      <Err e={error} />
      <div className="row" style={{ marginBottom: 12 }}>
        <input type="text" placeholder="Search name or SKU" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {(data?.categories || []).map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          <option value="change">Biggest recommended change</option><option value="cover">Lowest stock cover</option>
          <option value="price">Highest price</option><option value="name">Name</option>
        </select>
        <span className="sub">{rows.length} products</span>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div className="scroll" style={{ maxHeight: '70vh' }}>
          <table>
            <thead><tr><th>Product</th><th>Category</th><th className="r">Price now</th><th className="r">Competitor</th><th className="r">Stock</th><th className="r">Cover</th><th className="r">Recommended</th><th className="r">Change</th><th></th></tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.sku} className="click" onClick={() => open(p.sku)}>
                  <td><b>{p.name}</b> <span className="muted">{p.sku}</span></td><td>{p.category}</td>
                  <td className="r">{inr(p.current_price)}</td><td className="r">{inr(p.comp_price)}</td>
                  <td className="r">{num(p.stock)}</td>
                  <td className="r">{p.days_of_cover < 3 ? <span className="pill warn">{p.days_of_cover}d</span> : p.days_of_cover + 'd'}</td>
                  <td className="r"><b>{inr(p.recommended_price)}</b></td><td className="r"><Delta v={p.change_pct} /></td>
                  <td>{p.flash && <span className="pill flash">flash x{p.flash_ratio}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

function Detail({ sku, back }) {
  const [segment, setSegment] = useState('Standard')
  const d = usePoll(`/products/${sku}?segment=${segment}`, 4000, [sku, segment])
  const curve = usePoll(`/products/${sku}/demand-curve`, 8000, [sku])
  const tl = usePoll(`/stream/${sku}/timeline`, 4000, [sku])
  const [custom, setCustom] = useState('')
  const [comp, setComp] = useState('')
  const [stock, setStock] = useState('')
  const [toast, setToast] = useState('')
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 2200) }
  const refresh = () => { d.reload(); curve.reload(); tl.reload() }

  if (!d.data) return <><button className="back" onClick={back}>← All products</button><Err e={d.error} /><div className="muted">Loading…</div></>
  const { product: p, recommendation: r, stream: s, history, truth, price_log, customer_segments } = d.data

  const apply = async (price) => { const res = await api.post(`/products/${sku}/apply`, price ? { price: Number(price) } : {}); say(res.changed ? `Price set to ${inr(res.price)}` : 'Price already at that level'); setCustom(''); refresh() }
  const setState = async (body) => { await api.post(`/products/${sku}/state`, body); say('Updated'); setComp(''); setStock(''); refresh() }
  const flash = async () => { await api.post('/stream/flash', { sku, orders: 45 }); say('Simulated 45 orders in the last 90 seconds'); refresh() }
  const order = async () => { await api.post('/orders', { sku, qty: 5 }); say('Recorded an order of 5 units'); refresh() }

  return (
    <>
      <button className="back" onClick={back}>← All products</button>
      <div className="top">
        <div>
          <h1>{p.name}</h1>
          <div className="sub">{p.sku} · {p.category} · cost {inr(p.cost)} · reference price {inr(p.ref_price)}</div>
        </div>
        <div className="row" style={{ alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600 }}>
            Segment:
            <select value={segment} onChange={(e) => setSegment(e.target.value)} style={{ padding: '4px 8px' }}>
              {(customer_segments || ['Standard', 'Price-Sensitive', 'Loyal', 'VIP']).map((seg) => (
                <option key={seg} value={seg}>{seg}</option>
              ))}
            </select>
          </label>
          <div><div className="sub">Recommended</div><span className="tag big">{inr(r.recommended_price)}</span></div>
          <Delta v={r.change_pct} d={2} />
          <button className="btn primary" onClick={() => apply()}>Apply recommended</button>
        </div>
      </div>
      <Err e={d.error} />

      <div className="grid g3" style={{ marginBottom: 14 }}>
        <div className="card">
          <h2>Market now</h2>
          <Line2 a="Our price" b={inr(p.current_price)} /><Line2 a="Competitor price" b={inr(p.comp_price)} />
          <Line2 a="Margin at current price" b={p.margin_pct + '%'} />
          <Line2 a="Stock" b={`${num(p.stock)} units (${p.days_of_cover} days of cover)`} />
          <Line2 a="Demand spike" b={s.flash ? <span className="pill flash">flash x{s.ratio}</span> : <span className="pill ok">normal x{s.ratio}</span>} />
        </div>
        <div className="card">
          <h2>Expected daily outcome</h2>
          <table><thead><tr><th></th><th className="r">At current price</th><th className="r">At recommended</th></tr></thead><tbody>
            <tr><td>Units</td><td className="r">{r.exp_units_current}</td><td className="r">{r.exp_units_recommended}</td></tr>
            <tr><td>Revenue</td><td className="r">{inr(r.exp_revenue_current)}</td><td className="r"><b>{inr(r.exp_revenue_recommended)}</b></td></tr>
            <tr><td>Profit</td><td className="r">{inr(r.exp_profit_current)}</td><td className="r"><b>{inr(r.exp_profit_recommended)}</b></td></tr>
          </tbody></table>
          <div className="sub" style={{ marginTop: 8 }}>Price elasticity: model estimate {r.est_elasticity}, local slope {r.local_elasticity}. Ground truth (synthetic data only): {truth.true_elasticity}.</div>
        </div>
        <div className="card">
          <h2>Actions</h2>
          <div className="row" style={{ marginBottom: 8 }}>
            <input type="number" placeholder="Custom price" value={custom} onChange={(e) => setCustom(e.target.value)} style={{ width: 120 }} />
            <button className="btn" disabled={!custom} onClick={() => apply(custom)}>Set price</button>
          </div>
          <div className="row" style={{ marginBottom: 8 }}>
            <input type="number" placeholder="Competitor ₹" value={comp} onChange={(e) => setComp(e.target.value)} style={{ width: 120 }} />
            <button className="btn" disabled={!comp} onClick={() => setState({ comp_price: Number(comp) })}>Set competitor</button>
          </div>
          <div className="row" style={{ marginBottom: 8 }}>
            <input type="number" placeholder="Stock units" value={stock} onChange={(e) => setStock(e.target.value)} style={{ width: 120 }} />
            <button className="btn" disabled={stock === ''} onClick={() => setState({ stock: Number(stock) })}>Set stock</button>
          </div>
          <div className="row">
            <button className="btn" onClick={order}>Record order (5)</button>
            <button className="btn danger" onClick={flash}>Simulate flash sale</button>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <h2>How the recommended price is built</h2>
        <div className="steps">
          {r.steps.map((st, i) => (
            <div className="step" key={i}><div>{st.name}</div><div><b>{inr(st.price)}</b></div><div className="muted">{st.note}</div></div>
          ))}
        </div>
      </div>

      <div className="grid g2" style={{ marginBottom: 14 }}>
        <div className="card">
          <h2>Demand curve: revenue and profit by price</h2>
          <div className="chartbox">
            {curve.data && (
              <ResponsiveContainer>
                <ComposedChart data={curve.data.curve}>
                  <CartesianGrid stroke="#eef1f6" />
                  <XAxis dataKey="price" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(v) => num(v)} tick={{ fontSize: 12 }} />
                  <YAxis yAxisId="l" tickFormatter={(v) => num(v)} width={60} tick={{ fontSize: 12 }} />
                  <YAxis yAxisId="r" orientation="right" width={40} tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(v, n) => (n === 'units' ? num(v, 1) : inr(v))} labelFormatter={(v) => 'Price ' + inr(v)} />
                  <Legend />
                  <Line yAxisId="l" dataKey="revenue" stroke={chartColors.primary} dot={false} strokeWidth={2} />
                  <Line yAxisId="l" dataKey="profit" stroke={chartColors.up} dot={false} strokeWidth={2} />
                  <Line yAxisId="r" dataKey="units" stroke={chartColors.grey} dot={false} strokeDasharray="4 3" />
                  <ReferenceLine yAxisId="l" x={curve.data.current} stroke={chartColors.ink} strokeDasharray="3 3" label={{ value: 'now', fontSize: 11 }} />
                  <ReferenceLine yAxisId="l" x={curve.data.recommended} stroke={chartColors.tag} strokeWidth={2} label={{ value: 'rec.', fontSize: 11 }} />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
        <div className="card">
          <h2>Last 90 days: units sold and price</h2>
          <div className="chartbox">
            <ResponsiveContainer>
              <ComposedChart data={history}>
                <CartesianGrid stroke="#eef1f6" />
                <XAxis dataKey="date" tickFormatter={(v) => v.slice(5)} minTickGap={28} tick={{ fontSize: 12 }} />
                <YAxis yAxisId="l" width={40} tick={{ fontSize: 12 }} />
                <YAxis yAxisId="r" orientation="right" domain={['auto', 'auto']} tickFormatter={(v) => num(v)} width={60} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v, n) => (n === 'units' ? v : inr(v))} />
                <Legend />
                <Bar yAxisId="l" dataKey="units" fill="#b9d7e0" />
                <Line yAxisId="r" dataKey="price" stroke={chartColors.ink} dot={false} />
                <Line yAxisId="r" dataKey="comp_price" stroke={chartColors.tag} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Live orders: 5-minute window, sliding every minute</h2>
          <div className="chartbox" style={{ height: 200 }}>
            {tl.data && (
              <ResponsiveContainer>
                <AreaChart data={tl.data.timeline}>
                  <CartesianGrid stroke="#eef1f6" />
                  <XAxis dataKey="minutes_ago" reversed tickFormatter={(v) => (v === 0 ? 'now' : '-' + v + 'm')} tick={{ fontSize: 12 }} />
                  <YAxis width={30} tick={{ fontSize: 12 }} />
                  <Tooltip labelFormatter={(v) => v + ' min ago'} />
                  <Area dataKey="orders" stroke={chartColors.primary} fill="#b9d7e0" />
                  <ReferenceLine y={10} stroke={chartColors.down} strokeDasharray="4 3" label={{ value: 'min. orders to trigger', fontSize: 11, position: 'insideTopLeft' }} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
        <div className="card">
          <h2>Price change log</h2>
          {price_log.length === 0 && <div className="muted">No changes for this product yet.</div>}
          {price_log.map((l, i) => (
            <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #eef1f6' }}>
              {inr(l.old_price)} → <b>{inr(l.new_price)}</b> <Delta v={(l.new_price / l.old_price - 1) * 100} /> <span className="pill">{l.source}</span> <span className="muted">{ago(l.ts)}</span>
              <div className="sub" style={{ whiteSpace: 'normal' }}>{l.reason}</div>
            </div>
          ))}
        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}

const Line2 = ({ a, b }) => (
  <div className="row" style={{ padding: '4px 0', borderBottom: '1px solid #eef1f6' }}><span className="muted">{a}</span><span className="spacer" /><b>{b}</b></div>
)
