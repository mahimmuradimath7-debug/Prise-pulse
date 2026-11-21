import { useEffect, useState } from 'react'
import { api, usePoll } from '../api'
import { Err, Switch } from '../ui'

const OBJ = [
  ['balanced', 'Balanced', 'Weights revenue and profit equally against what the current price delivers.'],
  ['growth', 'Revenue growth', 'Maximise revenue while keeping profit at or above today’s level.'],
  ['revenue', 'Maximum revenue', 'Chase volume. Prices fall toward the margin floor on elastic products.'],
  ['profit', 'Maximum profit', 'Protect margin. Expect fewer units sold and lower revenue.'],
]

export default function SettingsPage({ onChange }) {
  const s = usePoll('/settings')
  const [v, setV] = useState(null)
  const [toast, setToast] = useState('')
  useEffect(() => { if (s.data && !v) setV(s.data) }, [s.data])
  if (!v) return <Err e={s.error} />
  const save = async (patch) => {
    const next = { ...v, ...patch }; setV(next)
    await api.put('/settings', patch); onChange?.()
    setToast('Saved'); setTimeout(() => setToast(''), 1200)
  }
  const reset = async () => {
    if (!window.confirm('Reset prices, stock, alerts and history to the starting demo data?')) return
    await api.post('/reset'); const n = await api.get('/settings'); setV(n); onChange?.()
    setToast('Demo data reset'); setTimeout(() => setToast(''), 1800)
  }
  const Slider = ({ k, label, min, max, step, fmt }) => (
    <div className="slider">
      <label htmlFor={k}>{label}</label>
      <input id={k} type="range" min={min} max={max} step={step} value={v[k]} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} onMouseUp={() => save({ [k]: v[k] })} onTouchEnd={() => save({ [k]: v[k] })} onKeyUp={() => save({ [k]: v[k] })} />
      <b>{fmt(v[k])}</b>
    </div>
  )
  return (
    <>
      <div className="top"><div><h1>Pricing rules</h1><div className="sub">These settings apply to every recommendation and to auto-repricing.</div></div></div>
      <div className="grid g2">
        <div className="card">
          <h2>Objective</h2>
          <div className="grid" style={{ gap: 8 }}>
            {OBJ.map(([k, l, d]) => (
              <label key={k} className={'opt' + (v.objective === k ? ' on' : '')}>
                <input type="radio" name="obj" checked={v.objective === k} onChange={() => save({ objective: k })} style={{ marginRight: 8 }} /><b>{l}</b>
                <div className="sub">{d}</div>
              </label>
            ))}
          </div>
        </div>
        <div className="card">
          <h2>Guardrails</h2>
          <Slider k="comp_weight" label="Competitor weight in blend" min={0} max={1} step={0.05} fmt={(x) => Math.round(x * 100) + '%'} />
          <Slider k="min_margin" label="Minimum margin" min={0} max={0.4} step={0.01} fmt={(x) => Math.round(x * 100) + '%'} />
          <Slider k="max_step" label="Max change per update" min={0.02} max={0.4} step={0.01} fmt={(x) => '±' + Math.round(x * 100) + '%'} />
          <Slider k="max_price_ratio" label="Price ceiling vs reference" min={1} max={2} step={0.05} fmt={(x) => 'x' + x.toFixed(2)} />
          <div style={{ marginTop: 14 }}>
            <Switch on={v.auto_mode} onChange={(a) => save({ auto_mode: a })}>Auto-reprice when the market moves</Switch>
            <div className="sub" style={{ marginTop: 4 }}>Reprices a product within seconds of a competitor change, stock change or flash sale.</div>
          </div>
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h2>Demo data</h2>
        <button className="btn danger" onClick={reset}>Reset demo data</button>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
