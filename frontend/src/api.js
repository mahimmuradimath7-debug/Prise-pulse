import { useEffect, useRef, useState, useCallback } from 'react'

async function req(path, opts = {}) {
  const res = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...opts })
  if (!res.ok) {
    let msg = res.statusText
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch {}
    throw new Error(msg)
  }
  return res.json()
}
export const api = {
  get: (p) => req(p),
  post: (p, b) => req(p, { method: 'POST', body: JSON.stringify(b || {}) }),
  put: (p, b) => req(p, { method: 'PUT', body: JSON.stringify(b || {}) }),
}

/** Poll an endpoint. Returns {data, error, reload}. */
export function usePoll(path, ms = 0, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const alive = useRef(true)
  const load = useCallback(async () => {
    if (!path) return
    try { const d = await api.get(path); if (alive.current) { setData(d); setError(null) } }
    catch (e) { if (alive.current) setError(e.message) }
  }, [path])
  useEffect(() => {
    alive.current = true
    setData(null)
    load()
    const t = ms ? setInterval(load, ms) : null
    return () => { alive.current = false; if (t) clearInterval(t) }
    // eslint-disable-next-line
  }, [load, ms, ...deps])
  return { data, error, reload: load }
}

export const inr = (n, d = 0) => n == null ? '–' : '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })
export const pct = (n, d = 1) => n == null ? '–' : (n > 0 ? '+' : '') + Number(n).toFixed(d) + '%'
export const num = (n, d = 0) => n == null ? '–' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })
export const ago = (ts) => {
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 60) return Math.round(s) + 's ago'
  if (s < 3600) return Math.round(s / 60) + 'm ago'
  return Math.round(s / 3600) + 'h ago'
}
