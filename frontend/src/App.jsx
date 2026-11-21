import { useState } from 'react'
import { api, usePoll } from './api'
import { Switch } from './ui'
import Dashboard from './pages/Dashboard'
import Products from './pages/Products'
import Live from './pages/Live'
import Simulation from './pages/Simulation'
import ModelPage from './pages/ModelPage'
import SettingsPage from './pages/SettingsPage'

const NAV = [
  ['dashboard', '📊', 'Overview'],
  ['products', '🏷️', 'Products'],
  ['live', '⚡', 'Live market'],
  ['sim', '🧪', 'Simulation lab'],
  ['model', '🧠', 'Demand model'],
  ['settings', '⚙️', 'Pricing rules'],
]

export default function App() {
  const [page, setPage] = useState('dashboard')
  const [focusSku, setFocusSku] = useState(null)
  const settings = usePoll('/settings', 5000)
  const open = (sku) => { setFocusSku(sku); setPage('products') }
  const toggleAuto = async (v) => { await api.put('/settings', { auto_mode: v }); settings.reload() }

  return (
    <div className="app">
      <nav className="side" aria-label="Main">
        <div className="brand">PricePulse <span className="tag">AI</span></div>
        {NAV.map(([k, icon, label]) => (
          <button key={k} className={'nav' + (page === k ? ' on' : '')} onClick={() => { setPage(k); if (k !== 'products') setFocusSku(null) }}>
            <span aria-hidden>{icon}</span>{label}
          </button>
        ))}
        <div className="foot">
          <Switch on={!!settings.data?.auto_mode} onChange={toggleAuto}>
            <span style={{ color: '#dbe4f5' }}>Auto-reprice</span>
          </Switch>
          <div style={{ marginTop: 8 }}>Prices update within seconds of a competitor move, stock change or demand spike.</div>
        </div>
      </nav>
      <main className="main">
        {page === 'dashboard' && <Dashboard open={open} go={setPage} />}
        {page === 'products' && <Products focusSku={focusSku} setFocusSku={setFocusSku} />}
        {page === 'live' && <Live open={open} />}
        {page === 'sim' && <Simulation />}
        {page === 'model' && <ModelPage />}
        {page === 'settings' && <SettingsPage onChange={settings.reload} />}
      </main>
    </div>
  )
}
