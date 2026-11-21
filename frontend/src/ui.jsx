import { pct } from './api'

export const Kpi = ({ label, value, delta, hint, tone }) => (
  <div className="card kpi">
    <div className="l">{label}</div>
    <div className="v">{value}</div>
    {delta != null && <div className={'d ' + (delta > 0 ? 'up' : delta < 0 ? 'down' : 'muted')}>{pct(delta)} {hint}</div>}
    {delta == null && hint && <div className={'d muted'}>{hint}</div>}
  </div>
)
export const Delta = ({ v, d = 1 }) => <span className={v > 0 ? 'up' : v < 0 ? 'down' : 'muted'}>{pct(v, d)}</span>
export const Err = ({ e }) => e ? <div className="err">Could not reach the API: {e}. Is the backend running on port 8000?</div> : null
export const Switch = ({ on, onChange, children }) => (
  <span className={'switch' + (on ? ' on' : '')} role="switch" aria-checked={on} tabIndex={0}
        onClick={() => onChange(!on)} onKeyDown={(e) => (e.key === ' ' || e.key === 'Enter') && onChange(!on)}>
    <i /> {children}
  </span>
)
export const Feed = ({ items, ts }) => (
  <div className="feed">
    {items.length === 0 && <div className="muted">Nothing yet.</div>}
    {items.map((a) => (
      <div key={a.id} className={'it ' + a.level}>
        <div>{a.message}</div><div className="ts">{ts(a.ts)}</div>
      </div>
    ))}
  </div>
)
export const chartColors = { primary: '#0e7490', tag: '#e0a100', ink: '#14213d', up: '#15803d', down: '#b91c1c', grey: '#9aa7bd' }
