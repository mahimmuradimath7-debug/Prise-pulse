import { Fragment, useState } from 'react'
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { api, usePoll, inr, num } from '../api'
import { Err, Kpi, chartColors } from '../ui'

const OBJ = [['balanced', 'Balanced'], ['growth', 'Revenue growth (profit held)'], ['revenue', 'Max revenue'], ['profit', 'Max profit']]

export default function Simulation() {
  const last = usePoll('/simulate/backtest')
  const [days, setDays] = useState(30)
  const [obj, setObj] = useState('balanced')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const R = res || (last.data?.summary ? last.data : null)

  const run = async () => {
    setBusy(true); setErr(null)
    try { setRes(await api.post('/simulate/backtest', { days: Number(days), objective: obj })) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <>
      <div className="top"><div><h1>Simulation lab</h1><div className="sub">Compare static prices with PricePulse on a simulated market, then train a reinforcement-learning agent.</div></div></div>
      <Err e={err || last.error} />
      <div className="card" style={{ marginBottom: 14 }}>
        <h2>Back-test</h2>
        <div className="row">
          <label className="f">Days<input type="number" min="7" max="90" value={days} onChange={(e) => setDays(e.target.value)} style={{ width: 90 }} /></label>
          <label className="f">Objective<select value={obj} onChange={(e) => setObj(e.target.value)}>{OBJ.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <button className="btn primary" disabled={busy} onClick={run} style={{ alignSelf: 'end' }}>{busy ? 'Running…' : 'Run back-test'}</button>
        </div>
      </div>
      {R && (
        <>
          <div className="grid g4" style={{ marginBottom: 14 }}>
            <Kpi label="Revenue" value={inr(R.summary.revenue.dynamic)} delta={R.summary.revenue.uplift_pct} hint={'vs ' + inr(R.summary.revenue.static)} />
            <Kpi label="Profit" value={inr(R.summary.profit.dynamic)} delta={R.summary.profit.uplift_pct} hint={'vs ' + inr(R.summary.profit.static)} />
            <Kpi label="Stock-out product-days" value={R.summary.stockout_sku_days.dynamic} hint={'vs ' + R.summary.stockout_sku_days.static + ' static (' + R.summary.stockout_sku_days.reduction_pct + '% fewer)'} />
            <Kpi label="Lost sales (units)" value={num(R.summary.lost_units.dynamic)} hint={'vs ' + num(R.summary.lost_units.static) + ' static'} />
          </div>
          <div className="grid g2" style={{ marginBottom: 14 }}>
            <div className="card">
              <h2>Cumulative revenue ({R.days} days, objective: {R.objective})</h2>
              <div className="chartbox">
                <ResponsiveContainer>
                  <LineChart data={R.daily}>
                    <CartesianGrid stroke="#eef1f6" />
                    <XAxis dataKey="day" tickFormatter={(v) => v.slice(5)} minTickGap={30} tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={(v) => '₹' + (v / 10000000).toFixed(1) + 'Cr'} width={64} tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(v) => inr(v)} /><Legend />
                    <Line dataKey="static_cum" name="Static prices" stroke={chartColors.grey} dot={false} strokeWidth={2} />
                    <Line dataKey="dynamic_cum" name="PricePulse" stroke={chartColors.primary} dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <h2>Change by category</h2>
              <div className="chartbox">
                <ResponsiveContainer>
                  <BarChart data={R.by_category}>
                    <CartesianGrid stroke="#eef1f6" vertical={false} />
                    <XAxis dataKey="category" tick={{ fontSize: 12 }} /><YAxis unit="%" width={44} tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(v) => v + '%'} /><Legend />
                    <Bar dataKey="revenue_uplift_pct" name="Revenue" fill={chartColors.primary} />
                    <Bar dataKey="profit_uplift_pct" name="Profit" fill={chartColors.up} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
          <div className="note" style={{ marginBottom: 14 }}>{R.note}</div>
        </>
      )}
      <RLLab />
    </>
  )
}

function RLLab() {
  const prods = usePoll('/products')
  const [sku, setSku] = useState('')
  const [algo, setAlgo] = useState('dqn')
  const [episodes, setEpisodes] = useState(800)
  const [busy, setBusy] = useState(false)
  const [R, setR] = useState(null)
  const [err, setErr] = useState(null)
  const train = async () => {
    if (!sku) return
    setBusy(true); setErr(null)
    try { setR(await api.post(`/rl/${sku}/train?episodes=${episodes}&algo=${algo}`)) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const stocks = ['<15% stock', '15-40%', '40-70%', '>70%']
  const comps = ['competitor cheaper', 'at par', 'competitor pricier']
  return (
    <div className="card">
      <h2>Reinforcement-learning pricing agent (Deep Q-Learning / DQN)</h2>
      <div className="sub" style={{ marginBottom: 10 }}>Project brief SOTA upgrade: Deep Q-Learning (DQN) with continuous feature inputs, experience replay, and trial-and-error optimization against simulated demand.</div>
      <Err e={err} />
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={sku} onChange={(e) => setSku(e.target.value)} aria-label="Product">
          <option value="">Pick a product…</option>
          {(prods.data?.products || []).map((p) => <option key={p.sku} value={p.sku}>{p.name} ({p.sku})</option>)}
        </select>
        <select value={algo} onChange={(e) => setAlgo(e.target.value)} aria-label="Algorithm">
          <option value="dqn">Deep Q-Learning (DQN)</option>
          <option value="tabular">Tabular Q-learning</option>
        </select>
        <label className="f" style={{ gridAutoFlow: 'column', alignItems: 'center' }}>Episodes <input type="number" min="100" max="5000" step="100" value={episodes} onChange={(e) => setEpisodes(e.target.value)} style={{ width: 90 }} /></label>
        <button className="btn primary" disabled={!sku || busy} onClick={train}>{busy ? 'Training…' : 'Train agent'}</button>
      </div>
      {R && R.curve && (
        <div className="grid g2">
          <div>
            <div className="chartbox" style={{ height: 220 }}>
              <ResponsiveContainer>
                <LineChart data={R.curve}>
                  <CartesianGrid stroke="#eef1f6" />
                  <XAxis dataKey="episode" tick={{ fontSize: 12 }} /><YAxis tickFormatter={(v) => num(v)} width={60} tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(v) => inr(v)} />
                  <Line dataKey="reward" name="Avg. 14-day reward" stroke={chartColors.primary} dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <span className="pill ok">RL vs fixed price: {R.eval.uplift_pct > 0 ? '+' : ''}{R.eval.uplift_pct}%</span>
              <span>Agent suggests <b>{inr(R.rl_recommendation.price)}</b> (x{R.rl_recommendation.multiplier}) · ML engine suggests <b>{inr(R.ml_recommendation)}</b> · now {inr(R.current_price)}</span>
            </div>
          </div>
          <div>
            <div className="sub" style={{ marginBottom: 6 }}>Learned price multiplier by situation</div>
            <div className="heat">
              <div className="h" />{comps.map((c) => <div key={c} className="h">{c}</div>)}
              {stocks.map((s) => (
                <Fragment key={s}>
                  <div className="h">{s}</div>
                  {comps.map((c) => <div key={s + c}>x{R.policy.find((p) => p.stock === s && p.competitor === c)?.multiplier}</div>)}
                </Fragment>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
