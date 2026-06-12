import { useEffect, useRef, useState } from 'react'
import { Copy, Check, Loader2, Play, Server, Upload, Trash2, Globe, Package, Shield, AlertTriangle } from 'lucide-react'
import api from '../api/client'
import { useLanguage } from '../contexts/LanguageContext'

interface Artifact {
  name: string
  size: number
}

interface LogEntry {
  time: string
  level: string
  message: string
}

interface JobSnapshot {
  id: string
  status: string
  error?: string | null
  logs: LogEntry[]
  results: Record<string, any>
}

const formatSize = (bytes: number) => {
  if (bytes > 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes > 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

const InstallNode = () => {
  const { t } = useLanguage()
  const tr = t.installNode

  // --- form state ---
  const [host, setHost] = useState('')
  const [sshPort, setSshPort] = useState('22')
  const [username, setUsername] = useState('root')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'iran' | 'foreign'>('iran')
  const [nodeName, setNodeName] = useState('node-1')
  const [panelHost, setPanelHost] = useState(window.location.hostname)
  const [panelApiPort, setPanelApiPort] = useState('8000')
  const [installNode, setInstallNode] = useState(true)
  const [installXui, setInstallXui] = useState(false)
  const [installWireguard, setInstallWireguard] = useState(false)
  const [xuiPort, setXuiPort] = useState('')
  const [xuiUsername, setXuiUsername] = useState('')
  const [xuiPassword, setXuiPassword] = useState('')

  // --- artifacts ---
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [bundleArtifact, setBundleArtifact] = useState('')
  const [xuiArtifact, setXuiArtifact] = useState('')
  const [uploadingKind, setUploadingKind] = useState<string | null>(null)
  const [uploadPercent, setUploadPercent] = useState(0)
  const bundleInputRef = useRef<HTMLInputElement>(null)
  const xuiInputRef = useRef<HTMLInputElement>(null)

  // --- job state ---
  const [submitting, setSubmitting] = useState(false)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [formError, setFormError] = useState('')
  const [copiedKey, setCopiedKey] = useState('')
  const [nodeRegistered, setNodeRegistered] = useState(false)
  const jobIdRef = useRef<string | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchArtifacts()
  }, [])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [job?.logs.length])

  // Poll the job while it is pending/running
  useEffect(() => {
    if (!job || (job.status !== 'pending' && job.status !== 'running')) return
    const interval = setInterval(async () => {
      const id = jobIdRef.current
      if (!id) return
      try {
        const res = await api.get(`/provisioning/install/${id}`)
        setJob(res.data)
      } catch (error) {
        console.error('Failed to poll job:', error)
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [job?.id, job?.status])

  // After a successful node install, confirm the node registered itself in the panel
  const nodeInstallStatus = job?.results?.node?.status
  const installedNodeName = job?.results?.node?.node_name
  useEffect(() => {
    if (nodeInstallStatus !== 'success' || !installedNodeName || nodeRegistered) return
    let attempts = 0
    const interval = setInterval(async () => {
      attempts += 1
      if (attempts > 40) {
        clearInterval(interval)
        return
      }
      try {
        const res = await api.get('/nodes')
        const found = (res.data as any[]).some((n) => n.name === installedNodeName)
        if (found) {
          setNodeRegistered(true)
          clearInterval(interval)
        }
      } catch (error) {
        console.error('Failed to check node registration:', error)
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [nodeInstallStatus, installedNodeName, nodeRegistered])

  const fetchArtifacts = async () => {
    try {
      const res = await api.get('/provisioning/artifacts')
      const items: Artifact[] = res.data
      setArtifacts(items)
      // Auto-select the most likely artifacts if nothing selected yet
      setBundleArtifact((prev) => prev || items.find((a) => a.name.includes('smite-offline'))?.name || '')
      setXuiArtifact((prev) => prev || items.find((a) => a.name.startsWith('x-ui'))?.name || '')
    } catch (error) {
      console.error('Failed to fetch artifacts:', error)
    }
  }

  const uploadArtifact = async (kind: 'bundle' | 'xui', file: File) => {
    setUploadingKind(kind)
    setUploadPercent(0)
    try {
      const formData = new FormData()
      formData.append('kind', kind)
      formData.append('file', file)
      const res = await api.post('/provisioning/artifacts', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (e.total) setUploadPercent(Math.round((e.loaded / e.total) * 100))
        },
      })
      await fetchArtifacts()
      if (kind === 'bundle') setBundleArtifact(res.data.name)
      else setXuiArtifact(res.data.name)
    } catch (error: any) {
      console.error('Upload failed:', error)
      alert(`${tr.uploadFailed}: ${error.response?.data?.detail || error.message}`)
    } finally {
      setUploadingKind(null)
      setUploadPercent(0)
    }
  }

  const deleteArtifact = async (name: string) => {
    try {
      await api.delete(`/provisioning/artifacts/${encodeURIComponent(name)}`)
      if (bundleArtifact === name) setBundleArtifact('')
      if (xuiArtifact === name) setXuiArtifact('')
      await fetchArtifacts()
    } catch (error: any) {
      console.error('Delete failed:', error)
      alert(`${tr.deleteFailed}: ${error.response?.data?.detail || error.message}`)
    }
  }

  const startInstall = async () => {
    setFormError('')
    if (!host.trim() || !username.trim() || !password) {
      setFormError(`${tr.sshHost} / ${tr.sshUsername} / ${tr.sshPassword}`)
      return
    }
    if (!installNode && !installXui && !installWireguard) {
      setFormError(tr.selectComponent)
      return
    }
    setSubmitting(true)
    setJob(null)
    setNodeRegistered(false)
    try {
      const res = await api.post('/provisioning/install', {
        host: host.trim(),
        ssh_port: parseInt(sshPort) || 22,
        username: username.trim(),
        password,
        role,
        node_name: nodeName.trim() || 'node-1',
        panel_host: panelHost.trim(),
        panel_api_port: parseInt(panelApiPort) || 8000,
        install_node: installNode,
        install_xui: installXui,
        install_wireguard: role === 'foreign' ? installWireguard : false,
        xui_version: 'v2.9.4',
        xui_port: xuiPort ? parseInt(xuiPort) : null,
        xui_username: xuiUsername || null,
        xui_password: xuiPassword || null,
        bundle_artifact: bundleArtifact || null,
        xui_artifact: xuiArtifact || null,
      })
      jobIdRef.current = res.data.job_id
      setJob({ id: res.data.job_id, status: res.data.status || 'pending', logs: [], results: {} })
    } catch (error: any) {
      console.error('Failed to start install:', error)
      setFormError(error.response?.data?.detail || error.message || tr.startFailed)
    } finally {
      setSubmitting(false)
    }
  }

  const copyValue = async (key: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey(''), 2000)
    } catch (error) {
      console.error('Copy failed:', error)
    }
  }

  const statusBadge = (status?: string) => {
    const map: Record<string, { cls: string; label: string }> = {
      pending: { cls: 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300', label: tr.statusPending },
      running: { cls: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-200', label: tr.statusRunning },
      success: { cls: 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200', label: tr.statusSuccess },
      error: { cls: 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200', label: tr.statusError },
    }
    const item = map[status || 'pending'] || map.pending
    return <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${item.cls}`}>{item.label}</span>
  }

  const inputCls =
    'w-full px-3 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
  const labelCls = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1'
  const sectionCls = 'bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-6'
  const sectionTitleCls = 'text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2'

  const ResultRow = ({ label, value, mono = true, multiline = false }: { label: string; value?: string; mono?: boolean; multiline?: boolean }) => {
    if (!value) return null
    const key = `${label}:${value.slice(0, 24)}`
    return (
      <div className="py-2 border-b border-gray-100 dark:border-gray-700/50 last:border-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</div>
            {multiline ? (
              <pre className="text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap break-all bg-gray-50 dark:bg-gray-900/50 rounded-lg p-2 mt-1">{value}</pre>
            ) : (
              <div className={`text-sm text-gray-900 dark:text-white break-all ${mono ? 'font-mono' : ''}`}>{value}</div>
            )}
          </div>
          <button
            onClick={() => copyValue(key, value)}
            className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-gray-500 dark:text-gray-400 shrink-0"
            title={tr.copy}
          >
            {copiedKey === key ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
          </button>
        </div>
      </div>
    )
  }

  const nodeRes = job?.results?.node
  const xuiRes = job?.results?.xui
  const wgRes = job?.results?.wireguard
  const jobActive = job && (job.status === 'pending' || job.status === 'running')

  return (
    <div className="w-full max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">{tr.title}</h1>
        <p className="text-gray-500 dark:text-gray-400">{tr.subtitle}</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* ---------------- Left column: form ---------------- */}
        <div className="space-y-6">
          {/* SSH target */}
          <div className={sectionCls}>
            <h2 className={sectionTitleCls}>
              <Server size={20} className="text-blue-500" />
              {tr.serverSection}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="sm:col-span-2">
                <label className={labelCls}>{tr.sshHost}</label>
                <input className={inputCls} value={host} onChange={(e) => setHost(e.target.value)} placeholder="1.2.3.4" dir="ltr" />
              </div>
              <div>
                <label className={labelCls}>{tr.sshPort}</label>
                <input className={inputCls} value={sshPort} onChange={(e) => setSshPort(e.target.value)} placeholder="22" dir="ltr" />
              </div>
              <div>
                <label className={labelCls}>{tr.sshUsername}</label>
                <input className={inputCls} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="root" dir="ltr" />
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>{tr.sshPassword}</label>
                <input type="password" className={inputCls} value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
              </div>
            </div>

            <div className="mt-4">
              <label className={labelCls}>{tr.role}</label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setRole('iran')}
                  className={`px-4 py-3 rounded-lg border-2 text-sm font-medium transition-all ${
                    role === 'iran'
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                      : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-gray-300'
                  }`}
                >
                  {tr.roleIran}
                </button>
                <button
                  type="button"
                  onClick={() => setRole('foreign')}
                  className={`px-4 py-3 rounded-lg border-2 text-sm font-medium transition-all ${
                    role === 'foreign'
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                      : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-gray-300'
                  }`}
                >
                  {tr.roleForeign}
                </button>
              </div>
            </div>
          </div>

          {/* Components */}
          <div className={sectionCls}>
            <h2 className={sectionTitleCls}>
              <Package size={20} className="text-indigo-500" />
              {tr.componentsSection}
            </h2>
            <div className="space-y-3">
              {/* Smite node */}
              <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${installNode ? 'border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-900/10' : 'border-gray-200 dark:border-gray-700'}`}>
                <input type="checkbox" checked={installNode} onChange={(e) => setInstallNode(e.target.checked)} className="mt-1 w-4 h-4 text-blue-600 rounded" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">{tr.installSmiteNode}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{tr.installSmiteNodeDesc}</div>
                  {installNode && (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
                      <div>
                        <label className={labelCls}>{tr.nodeName}</label>
                        <input className={inputCls} value={nodeName} onChange={(e) => setNodeName(e.target.value)} dir="ltr" />
                      </div>
                      <div>
                        <label className={labelCls}>{tr.panelHost}</label>
                        <input className={inputCls} value={panelHost} onChange={(e) => setPanelHost(e.target.value)} dir="ltr" title={tr.panelHostHint} />
                      </div>
                      <div>
                        <label className={labelCls}>{tr.panelApiPort}</label>
                        <input className={inputCls} value={panelApiPort} onChange={(e) => setPanelApiPort(e.target.value)} dir="ltr" />
                      </div>
                    </div>
                  )}
                </div>
              </label>

              {/* 3x-ui */}
              <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${installXui ? 'border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-900/10' : 'border-gray-200 dark:border-gray-700'}`}>
                <input type="checkbox" checked={installXui} onChange={(e) => setInstallXui(e.target.checked)} className="mt-1 w-4 h-4 text-blue-600 rounded" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">{tr.installXui}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{tr.installXuiDesc}</div>
                  {installXui && (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
                      <div>
                        <label className={labelCls}>{tr.xuiPort}</label>
                        <input className={inputCls} value={xuiPort} onChange={(e) => setXuiPort(e.target.value)} placeholder={tr.randomIfEmpty} dir="ltr" />
                      </div>
                      <div>
                        <label className={labelCls}>{tr.xuiUsername}</label>
                        <input className={inputCls} value={xuiUsername} onChange={(e) => setXuiUsername(e.target.value)} placeholder={tr.randomIfEmpty} dir="ltr" />
                      </div>
                      <div>
                        <label className={labelCls}>{tr.xuiPassword}</label>
                        <input className={inputCls} value={xuiPassword} onChange={(e) => setXuiPassword(e.target.value)} placeholder={tr.randomIfEmpty} dir="ltr" />
                      </div>
                    </div>
                  )}
                </div>
              </label>

              {/* WireGuard */}
              <label className={`flex items-start gap-3 p-3 rounded-lg border transition-all ${role !== 'foreign' ? 'opacity-50 cursor-not-allowed border-gray-200 dark:border-gray-700' : installWireguard ? 'cursor-pointer border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-900/10' : 'cursor-pointer border-gray-200 dark:border-gray-700'}`}>
                <input
                  type="checkbox"
                  checked={role === 'foreign' && installWireguard}
                  disabled={role !== 'foreign'}
                  onChange={(e) => setInstallWireguard(e.target.checked)}
                  className="mt-1 w-4 h-4 text-blue-600 rounded"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">{tr.installWireguard}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{tr.installWireguardDesc}</div>
                  {role !== 'foreign' && (
                    <div className="text-xs text-amber-600 dark:text-amber-400 mt-1 flex items-center gap-1">
                      <AlertTriangle size={12} />
                      {tr.wireguardForeignOnly}
                    </div>
                  )}
                </div>
              </label>
            </div>
          </div>

          {/* Artifacts */}
          <div className={sectionCls}>
            <h2 className={sectionTitleCls}>
              <Upload size={20} className="text-emerald-500" />
              {tr.artifactsSection}
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-4" dir="auto">{tr.artifactsHint}</p>

            <div className="space-y-4">
              {/* bundle */}
              <div>
                <label className={labelCls}>
                  {tr.bundleArtifact}
                  {role === 'iran' && installNode && <span className="text-red-500 ms-1">*</span>}
                </label>
                <div className="flex gap-2">
                  <select className={inputCls} value={bundleArtifact} onChange={(e) => setBundleArtifact(e.target.value)} dir="ltr">
                    <option value="">{tr.noArtifact}</option>
                    {artifacts.map((a) => (
                      <option key={a.name} value={a.name}>
                        {a.name} ({formatSize(a.size)})
                      </option>
                    ))}
                  </select>
                  <input
                    ref={bundleInputRef}
                    type="file"
                    accept=".gz,.tgz,.tar.gz"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) uploadArtifact('bundle', f)
                      e.target.value = ''
                    }}
                  />
                  <button
                    onClick={() => bundleInputRef.current?.click()}
                    disabled={uploadingKind !== null}
                    className="px-3 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-all text-sm font-medium whitespace-nowrap flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {uploadingKind === 'bundle' ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                    {uploadingKind === 'bundle' ? `${uploadPercent}%` : tr.uploadBundle}
                  </button>
                </div>
              </div>

              {/* x-ui tarball */}
              <div>
                <label className={labelCls}>
                  {tr.xuiArtifact}
                  {role === 'iran' && installXui && <span className="text-red-500 ms-1">*</span>}
                </label>
                <div className="flex gap-2">
                  <select className={inputCls} value={xuiArtifact} onChange={(e) => setXuiArtifact(e.target.value)} dir="ltr">
                    <option value="">{tr.noArtifact}</option>
                    {artifacts.map((a) => (
                      <option key={a.name} value={a.name}>
                        {a.name} ({formatSize(a.size)})
                      </option>
                    ))}
                  </select>
                  <input
                    ref={xuiInputRef}
                    type="file"
                    accept=".gz,.tgz,.tar.gz"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) uploadArtifact('xui', f)
                      e.target.value = ''
                    }}
                  />
                  <button
                    onClick={() => xuiInputRef.current?.click()}
                    disabled={uploadingKind !== null}
                    className="px-3 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-all text-sm font-medium whitespace-nowrap flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {uploadingKind === 'xui' ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                    {uploadingKind === 'xui' ? `${uploadPercent}%` : tr.uploadXui}
                  </button>
                </div>
              </div>

              {/* uploaded files list */}
              {artifacts.length > 0 && (
                <div className="border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-700/50">
                  {artifacts.map((a) => (
                    <div key={a.name} className="flex items-center justify-between px-3 py-2">
                      <div className="text-xs font-mono text-gray-700 dark:text-gray-300 break-all" dir="ltr">
                        {a.name} <span className="text-gray-400">({formatSize(a.size)})</span>
                      </div>
                      <button onClick={() => deleteArtifact(a.name)} className="p-1.5 hover:bg-red-50 dark:hover:bg-red-900/20 rounded text-red-500 shrink-0">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Submit */}
          <div>
            {formError && (
              <div className="mb-3 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-300" dir="auto">
                {formError}
              </div>
            )}
            <button
              onClick={startInstall}
              disabled={submitting || !!jobActive}
              className="w-full px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all duration-200 font-medium shadow-sm hover:shadow-md flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting || jobActive ? <Loader2 size={20} className="animate-spin" /> : <Play size={20} />}
              {submitting || jobActive ? tr.installing : tr.startInstall}
            </button>
          </div>
        </div>

        {/* ---------------- Right column: log + results ---------------- */}
        <div className="space-y-6">
          {/* Live log */}
          <div className={sectionCls}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                <Globe size={20} className="text-cyan-500" />
                {tr.liveLog}
              </h2>
              {job && statusBadge(job.status)}
            </div>
            <div className="bg-gray-900 rounded-lg p-3 h-80 overflow-y-auto font-mono text-xs leading-relaxed" dir="ltr">
              {!job || job.logs.length === 0 ? (
                <div className="text-gray-500">$ _</div>
              ) : (
                job.logs.map((entry, i) => (
                  <div
                    key={i}
                    className={
                      entry.level === 'error'
                        ? 'text-red-400'
                        : entry.level === 'step'
                          ? 'text-cyan-400 font-semibold'
                          : entry.level === 'info'
                            ? 'text-green-400'
                            : 'text-gray-300'
                    }
                  >
                    {entry.message}
                  </div>
                ))
              )}
              <div ref={logEndRef} />
            </div>
            {job?.error && (
              <div className="mt-3 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-300" dir="auto">
                {job.error}
              </div>
            )}
          </div>

          {/* Results */}
          {(nodeRes || xuiRes || wgRes) && (
            <div className={sectionCls}>
              <h2 className={sectionTitleCls}>
                <Shield size={20} className="text-violet-500" />
                {tr.resultsSection}
              </h2>
              <div className="space-y-5">
                {nodeRes && (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{tr.nodeResult}</h3>
                      {statusBadge(nodeRes.status)}
                    </div>
                    {nodeRes.error && <div className="text-xs text-red-500 mb-2" dir="auto">{nodeRes.error}</div>}
                    <ResultRow label={tr.nodeName} value={nodeRes.node_name} />
                    <ResultRow label={tr.fieldMethod} value={nodeRes.method} />
                    <ResultRow label={tr.role} value={nodeRes.role} />
                    <ResultRow label={tr.panelHost} value={nodeRes.panel_address} />
                    {nodeRes.status === 'success' && (
                      <div className="mt-2">
                        {nodeRegistered ? (
                          <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
                            <Check size={14} />
                            {tr.nodeRegistered}
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                            <Loader2 size={14} className="animate-spin" />
                            {tr.nodeWaitingRegistration}
                          </div>
                        )}
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1" dir="auto">{tr.checkNodesPage}</p>
                      </div>
                    )}
                  </div>
                )}

                {xuiRes && (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{tr.xuiResult}</h3>
                      {statusBadge(xuiRes.status)}
                    </div>
                    {xuiRes.error && <div className="text-xs text-red-500 mb-2" dir="auto">{xuiRes.error}</div>}
                    <ResultRow label={tr.panelUrl} value={xuiRes.panelUrl} />
                    <ResultRow label={tr.username} value={xuiRes.username} />
                    <ResultRow label={tr.password} value={xuiRes.password} />
                    <ResultRow label={tr.port} value={xuiRes.port} />
                    <ResultRow label={tr.webBasePath} value={xuiRes.webBasePath} />
                    <ResultRow label={tr.apiToken} value={xuiRes.apiToken} />
                    {xuiRes.note && <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">{xuiRes.note}</p>}
                  </div>
                )}

                {wgRes && (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{tr.wireguardResult}</h3>
                      {statusBadge(wgRes.status)}
                    </div>
                    {wgRes.error && <div className="text-xs text-red-500 mb-2" dir="auto">{wgRes.error}</div>}
                    <ResultRow label={tr.wgPort} value={wgRes.wgPort} />
                    <ResultRow label={tr.serverEndpoint} value={wgRes.serverEndpoint} />
                    <ResultRow label={tr.serverPublicKey} value={wgRes.serverPublicKey} />
                    <ResultRow label={tr.apiBaseUrl} value={wgRes.apiBaseUrl} />
                    <ResultRow label={tr.apiEndpoints} value={wgRes.apiEndpoints} />
                    {wgRes.apiKeyNote && (
                      <div className="mt-2 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg text-xs text-amber-700 dark:text-amber-300 flex items-start gap-1.5">
                        <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                        <span>{wgRes.apiKeyNote}</span>
                      </div>
                    )}
                    <ResultRow label={tr.clientConfig} value={wgRes.defaultClientConfig} multiline />
                    {wgRes.note && <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">{wgRes.note}</p>}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default InstallNode
