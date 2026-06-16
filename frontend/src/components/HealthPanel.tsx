import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, RefreshCw, Wrench, X } from 'lucide-react'
import api from '../api/client'
import { useLanguage } from '../contexts/LanguageContext'

interface Problem {
  id: string
  node_id?: string | null
  node_name?: string | null
  tunnel_id?: string | null
  tunnel_name?: string | null
  kind: string
  severity: string
  message: string
  status: string
  occurrences: number
  last_seen?: string | null
  auto_heal_action?: string | null
  auto_heal_result?: string | null
}

interface HealthConfig {
  auto_heal_enabled?: boolean
  [k: string]: any
}

const severityStyle = (sev: string) => {
  switch (sev) {
    case 'critical':
      return 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200'
    case 'warning':
      return 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200'
    default:
      return 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200'
  }
}

const HealthPanel = () => {
  const { t } = useLanguage()
  const [problems, setProblems] = useState<Problem[]>([])
  const [config, setConfig] = useState<HealthConfig>({})
  const [lastRun, setLastRun] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const fetchAll = async () => {
    try {
      const [probRes, cfgRes, sumRes] = await Promise.all([
        api.get('/health/problems?status=open'),
        api.get('/health/config'),
        api.get('/health/summary'),
      ])
      setProblems(probRes.data || [])
      setConfig(cfgRes.data || {})
      setLastRun(sumRes.data?.last_run_at || null)
    } catch (error) {
      // silent
    }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 10000)
    return () => clearInterval(interval)
  }, [])

  const runCheck = async () => {
    setChecking(true)
    try {
      await api.post('/health/reconcile')
      await fetchAll()
    } catch (error) {
      // silent
    } finally {
      setChecking(false)
    }
  }

  const toggleAutoHeal = async () => {
    try {
      const next = !config.auto_heal_enabled
      const res = await api.put('/health/config', { auto_heal_enabled: next })
      setConfig(res.data?.config || { ...config, auto_heal_enabled: next })
    } catch (error) {
      // silent
    }
  }

  const fixNow = async (p: Problem) => {
    try {
      if (p.tunnel_id) {
        await api.post(`/health/heal/${p.tunnel_id}`)
      } else {
        await api.post('/health/reconcile')
      }
      await fetchAll()
    } catch (error) {
      alert(t.health.healFailed)
    }
  }

  const resolve = async (p: Problem) => {
    try {
      await api.post(`/health/problems/${p.id}/resolve`)
      setProblems((prev) => prev.filter((x) => x.id !== p.id))
    } catch (error) {
      // silent
    }
  }

  return (
    <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-2">
          {problems.length === 0 ? (
            <CheckCircle size={18} className="text-green-600 dark:text-green-400" />
          ) : (
            <AlertTriangle size={18} className="text-amber-600 dark:text-amber-400" />
          )}
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">{t.health.title}</h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">{t.health.subtitle}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer select-none" title={t.health.autoHealHint}>
            <span className="text-xs text-gray-600 dark:text-gray-300">{t.health.autoHeal}</span>
            <button
              type="button"
              onClick={toggleAutoHeal}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                config.auto_heal_enabled ? 'bg-green-600' : 'bg-gray-300 dark:bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  config.auto_heal_enabled ? 'translate-x-4' : 'translate-x-0.5'
                }`}
              />
            </button>
          </label>
          <button
            onClick={runCheck}
            disabled={checking}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-60"
          >
            <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
            {checking ? t.health.checking : t.health.runCheck}
          </button>
        </div>
      </div>

      {problems.length === 0 ? (
        <div className="px-5 py-4 text-sm text-green-700 dark:text-green-300">{t.health.allHealthy}</div>
      ) : (
        <ul className="divide-y divide-gray-100 dark:divide-gray-700">
          {problems.map((p) => (
            <li key={p.id} className={`px-5 py-3 border-l-4 ${severityStyle(p.severity)}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold uppercase tracking-wide">{p.kind}</span>
                    {p.node_name && (
                      <span className="text-xs text-gray-500 dark:text-gray-400">· {p.node_name}</span>
                    )}
                    {p.tunnel_name && (
                      <span className="text-xs text-gray-500 dark:text-gray-400">· {p.tunnel_name}</span>
                    )}
                    {p.occurrences > 1 && (
                      <span className="text-[10px] text-gray-400">×{p.occurrences} {t.health.occurrences}</span>
                    )}
                  </div>
                  <p className="text-sm mt-0.5 text-gray-700 dark:text-gray-200">{p.message}</p>
                  {p.auto_heal_result && (
                    <p className="text-[11px] mt-0.5 text-gray-500 dark:text-gray-400">→ {p.auto_heal_action}: {p.auto_heal_result}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => fixNow(p)}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white rounded"
                  >
                    <Wrench size={12} />
                    {t.health.fixNow}
                  </button>
                  <button
                    onClick={() => resolve(p)}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
                  >
                    <X size={12} />
                    {t.health.resolve}
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default HealthPanel
