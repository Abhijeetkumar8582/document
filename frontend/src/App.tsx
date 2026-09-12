import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { LayoutGrid, Files, UploadCloud, Search, ScrollText, Loader2, Workflow } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { analysis } from './lib/analysis'
import { AnalysisOverlay } from './components/AnalysisOverlay'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutGrid, end: true },
  { to: '/records', label: 'Records', icon: Files },
  { to: '/upload', label: 'Upload', icon: UploadCloud },
  { to: '/audit', label: 'Audit log', icon: ScrollText },
  { to: '/how-it-works', label: 'How it works', icon: Workflow },
]

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [q, setQ] = useState('')
  const sessions = useSyncExternalStore(analysis.subscribe, analysis.getSessions)
  const activeSessions = sessions.filter((s) => s.phase === 'uploading' || s.phase === 'queuing' || s.phase === 'processing')
  const activeFiles = analysis.activeFileCount()
  const onRecords = location.pathname === '/records'

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (onRecords) document.getElementById('global-search')?.focus()
        else navigate('/records?focus=1')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onRecords, navigate])

  // Keep the box in step with the URL, so a filtered link or "Clear" shows the real query.
  useEffect(() => {
    setQ(new URLSearchParams(location.search).get('q') ?? '')
  }, [location.search])

  // Arriving via Ctrl+K from another page: land with the search focused.
  useEffect(() => {
    if (onRecords && new URLSearchParams(location.search).get('focus')) {
      document.getElementById('global-search')?.focus()
      navigate('/records', { replace: true })
    }
  }, [onRecords, location.search, navigate])

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col self-start overflow-y-auto bg-ink text-white md:flex">
        <div className="px-6 pb-6 pt-7">
          <div className="flex items-center gap-2.5">
            <Seal />
            <div>
              <div className="font-display text-[19px] font-semibold leading-none tracking-tight">Registrar</div>
              <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] text-white/50">Academic records</div>
            </div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 text-[13.5px] transition-colors ${
                  isActive ? 'bg-white/10 text-white' : 'text-white/65 hover:bg-white/5 hover:text-white'
                }`
              }
            >
              <Icon size={16} strokeWidth={1.75} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-6 py-6 text-[11.5px] leading-5 text-white/40">
          Education records under FERPA.
          <br />
          SSNs and birth dates are removed on intake. Every view, edit, download and export is logged.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-line bg-paper/90 px-4 backdrop-blur md:px-8">
          <div className="flex items-center gap-2 md:hidden">
            <Seal />
            <span className="font-display text-base font-semibold">Registrar</span>
          </div>
          {activeSessions.length > 0 && (
            <button
              onClick={() => analysis.openOverlay(activeSessions[0].id)}
              className="ml-auto inline-flex items-center gap-2 rounded-full border border-oxford/30 bg-oxford-soft px-3 py-1 text-[12.5px] font-medium text-oxford hover:bg-oxford/10"
              title="Analysis is running on the server. Click to watch."
            >
              <Loader2 size={13} className="animate-spin" />
              Analyzing {activeFiles} {activeFiles === 1 ? 'document' : 'documents'}
            </button>
          )}
          <form
            hidden={!onRecords}
            className={`relative w-full max-w-md ${activeSessions.length > 0 ? '' : 'ml-auto'}`}
            onSubmit={(e) => {
              e.preventDefault()
              navigate(`/records?q=${encodeURIComponent(q.trim())}`)
            }}
          >
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              id="global-search"
              aria-label="Search records"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by student, ID, school…"
              className="input pl-9 pr-14"
            />
            <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-line bg-paper px-1.5 font-mono text-[10px] text-slate-500">
              Ctrl K
            </kbd>
          </form>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
        <AnalysisOverlay />
        <nav className="sticky bottom-0 flex border-t border-line bg-paper-2 md:hidden">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-1 py-2 text-[11px] ${isActive ? 'text-ink' : 'text-slate-500'}`
              }
            >
              <Icon size={18} strokeWidth={1.75} />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  )
}

function Seal() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
      <circle cx="15" cy="15" r="13.5" fill="none" stroke="#B8923E" strokeWidth="1.5" />
      <circle cx="15" cy="15" r="10" fill="none" stroke="#B8923E" strokeWidth="0.75" strokeDasharray="1.5 2" />
      <path d="M15 8.5 L21 12 L15 15.5 L9 12 Z" fill="#B8923E" />
      <path d="M11 13.5 V17.5 L15 19.5 L19 17.5 V13.5" fill="none" stroke="#B8923E" strokeWidth="1.25" />
    </svg>
  )
}
