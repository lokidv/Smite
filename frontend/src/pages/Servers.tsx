import { useEffect, useState } from 'react'
import { Plus, Copy, Trash2, CheckCircle, XCircle, AlertCircle, Pencil, Loader2, Shield } from 'lucide-react'
import api from '../api/client'
import { useLanguage } from '../contexts/LanguageContext'
import HealthPanel from '../components/HealthPanel'

interface Server {
  id: string
  name: string
  fingerprint: string
  status: string
  registered_at: string
  last_seen: string
  metadata: Record<string, any>
}

interface ProxyServerRow {
  id: string
  host: string
  ssh_port: number
  ssh_user: string
  has_ssh_password: boolean
  mode: string
  wg_port: string
  api_port: string
  api_base_url: string
  proxy_ip: string
  proxy_port: string
  proxy_type: string
  proxy_user: string
  proxy_endpoint: string
  proxy_status: string
  updated_at: string
}

const Servers = () => {
  const { t } = useLanguage()
  const [servers, setServers] = useState<Server[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [showCertModal, setShowCertModal] = useState(false)
  const [certContent, setCertContent] = useState('')
  const [certLoading, setCertLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [proxyServers, setProxyServers] = useState<ProxyServerRow[]>([])
  const [editTarget, setEditTarget] = useState<ProxyServerRow | null>(null)

  useEffect(() => {
    fetchServers()
    fetchProxyServers()
    const params = new URLSearchParams(window.location.search)
    if (params.get('add') === 'true') {
      setShowAddModal(true)
      window.history.replaceState({}, '', '/servers')
    }
  }, [])

  const fetchProxyServers = async () => {
    try {
      const res = await api.get('/provisioning/proxy-servers')
      setProxyServers(res.data)
    } catch (error) {
      console.error('Failed to fetch proxy servers:', error)
    }
  }

  const forgetProxyServer = async (row: ProxyServerRow) => {
    if (!confirm(t.servers.confirmForget)) return
    try {
      await api.delete(`/provisioning/proxy-servers/${row.id}`)
      fetchProxyServers()
    } catch (error) {
      console.error('Failed to forget proxy server:', error)
    }
  }

  const fetchServers = async () => {
    try {
      const response = await api.get('/nodes')
      // Filter only foreign servers
      const foreignServers = response.data.filter((node: Server) => 
        node.metadata?.role === 'foreign'
      )
      setServers(foreignServers)
    } catch (error) {
      console.error('Failed to fetch servers:', error)
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      console.error('Failed to copy to clipboard:', error)
      alert('Failed to copy to clipboard. Please copy manually.')
    }
  }

  const showCA = async () => {
    setShowCertModal(true)
    setCertLoading(true)
    try {
      const response = await api.get('/panel/ca/server', {
        responseType: 'text',
        headers: {
          'Accept': 'text/plain'
        }
      })
      const text = response.data
      if (!text || text.trim().length === 0) {
        throw new Error('Certificate is empty. Make sure the panel has generated it.')
      }
      setCertContent(text)
    } catch (error: any) {
      console.error('Failed to fetch CA:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to fetch CA certificate'
      alert(`Failed to fetch CA certificate: ${errorMessage}`)
      setShowCertModal(false)
    } finally {
      setCertLoading(false)
    }
  }

  const downloadCA = async () => {
    try {
      const response = await api.get('/panel/ca/server?download=true', { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', 'ca-server.crt')
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (error) {
      console.error('Failed to download CA:', error)
    }
  }

  const deleteServer = async (id: string) => {
    if (!confirm('Are you sure you want to delete this server?')) return
    
    try {
      await api.delete(`/nodes/${id}`)
      fetchServers()
    } catch (error) {
      console.error('Failed to delete server:', error)
      alert('Failed to delete server')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 dark:border-blue-400 mb-4"></div>
          <p className="text-gray-500 dark:text-gray-400">Loading servers...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">{t.servers.title}</h1>
          <p className="text-gray-500 dark:text-gray-400">{t.servers.subtitle}</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={showCA}
            className="px-5 py-2.5 bg-gradient-to-r from-green-600 to-emerald-600 text-white rounded-lg hover:from-green-700 hover:to-emerald-700 transition-all duration-200 font-medium shadow-sm hover:shadow-md flex items-center gap-2"
          >
            <Copy size={20} />
            {t.servers.viewCACertificate}
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all duration-200 font-medium shadow-sm hover:shadow-md flex items-center gap-2"
          >
            <Plus size={20} />
            {t.dashboard.addServer}
          </button>
        </div>
      </div>

      <HealthPanel />

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-600">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Name
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Fingerprint
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                IP Address
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Last Seen
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            {servers.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                  No foreign servers found. Add a server to get started.
                </td>
              </tr>
            ) : (
              servers.map((server) => (
                <tr key={server.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900 dark:text-white">{server.name}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <code className="text-sm text-gray-600 dark:text-gray-300 font-mono">{server.fingerprint}</code>
                      <button
                        onClick={() => copyToClipboard(server.fingerprint)}
                        className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-gray-600 dark:text-gray-400"
                      >
                        <Copy size={14} />
                      </button>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {(() => {
                      const connStatus = server.metadata?.connection_status || 'failed'
                      const getStatusColor = (status: string) => {
                        switch (status) {
                          case 'connected':
                            return 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200'
                          case 'connecting':
                          case 'reconnecting':
                            return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-200'
                          case 'failed':
                            return 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200'
                          default:
                            return 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200'
                        }
                      }
                      const getStatusIcon = (status: string) => {
                        switch (status) {
                          case 'connected':
                            return <CheckCircle size={12} className="text-green-600 dark:text-green-400" />
                          case 'connecting':
                          case 'reconnecting':
                            return <AlertCircle size={12} className="text-yellow-600 dark:text-yellow-400" />
                          case 'failed':
                            return <XCircle size={12} className="text-red-600 dark:text-red-400" />
                          default:
                            return <XCircle size={12} />
                        }
                      }
                      const getStatusText = (status: string) => {
                        switch (status) {
                          case 'connected':
                            return 'Connected'
                          case 'connecting':
                            return 'Connecting'
                          case 'reconnecting':
                            return 'Reconnecting'
                          case 'failed':
                            return 'Failed'
                          default:
                            return status
                        }
                      }
                      return (
                        <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(connStatus)}`}>
                          {getStatusIcon(connStatus)}
                          {getStatusText(connStatus)}
                        </span>
                      )
                    })()}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {server.metadata?.ip_address || 'N/A'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {new Date(server.last_seen).toLocaleString()}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <button
                      onClick={() => deleteServer(server.id)}
                      className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ---------- WARP / Proxy servers ---------- */}
      <div className="mt-10">
        <div className="mb-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Shield size={22} className="text-violet-500" />
            {t.servers.proxyTitle}
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">{t.servers.proxySubtitle}</p>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm overflow-x-auto">
          <table className="w-full min-w-[720px]">
            <thead className="bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-600">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Host</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">{t.servers.proxyColMode}</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">{t.servers.proxyColEndpoint}</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">{t.servers.proxyColStatus}</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">{t.servers.proxyColApi}</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
              {proxyServers.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                    {t.servers.proxyEmpty}
                  </td>
                </tr>
              ) : (
                proxyServers.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900 dark:text-white" dir="ltr">{row.host}</td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${row.mode === 'warp' ? 'bg-orange-100 dark:bg-orange-900/30 text-orange-800 dark:text-orange-200' : 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200'}`}>
                        {row.mode === 'warp' ? 'WARP' : 'Proxy'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-600 dark:text-gray-300" dir="ltr">
                      {row.mode === 'warp' ? 'Cloudflare WARP' : row.proxy_endpoint}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${row.proxy_status === 'active' ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200' : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200'}`}>
                        {row.proxy_status === 'active' ? <CheckCircle size={12} /> : <AlertCircle size={12} />}
                        {row.proxy_status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-500 dark:text-gray-400" dir="ltr">{row.api_base_url}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => setEditTarget(row)}
                          className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300"
                        >
                          <Pencil size={15} /> {t.servers.proxyEdit}
                        </button>
                        <button
                          onClick={() => forgetProxyServer(row)}
                          className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
                          title={t.servers.proxyForget}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showAddModal && (
        <AddServerModal
          onClose={() => setShowAddModal(false)}
          onSuccess={() => {
            setShowAddModal(false)
            fetchServers()
          }}
        />
      )}

      {editTarget && (
        <EditProxyModal
          server={editTarget}
          onClose={() => setEditTarget(null)}
          onSuccess={() => {
            setEditTarget(null)
            fetchProxyServers()
          }}
        />
      )}

      {showCertModal && (
        <CertModal
          certContent={certContent}
          loading={certLoading}
          onClose={() => setShowCertModal(false)}
          onCopy={() => setCopied(true)}
          copied={copied}
        />
      )}
    </div>
  )
}

interface AddServerModalProps {
  onClose: () => void
  onSuccess: () => void
}

const AddServerModal = ({ onClose, onSuccess }: AddServerModalProps) => {
  const { t } = useLanguage()
  const [name, setName] = useState('')
  const [ipAddress, setIpAddress] = useState('')
  const [apiPort, setApiPort] = useState('8888')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/nodes', { 
        name, 
        ip_address: ipAddress, 
        api_port: parseInt(apiPort) || 8888,
        metadata: {
          role: 'foreign'  // Set role to foreign for servers
        } 
      })
      onSuccess()
    } catch (error) {
      console.error('Failed to add server:', error)
      alert('Failed to add server')
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-6 w-full max-w-md">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">Add Foreign Server</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Server Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-400"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              IP Address
            </label>
            <input
              type="text"
              value={ipAddress}
              onChange={(e) => setIpAddress(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-400"
              placeholder="e.g., 192.168.1.100"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              API Port
            </label>
            <input
              type="number"
              value={apiPort}
              onChange={(e) => setApiPort(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-400"
              placeholder="8888"
              min="1"
              max="65535"
              required
            />
          </div>
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all duration-200 font-medium shadow-sm hover:shadow-md"
            >
              {t.dashboard.addServer}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

interface CertModalProps {
  certContent: string
  loading: boolean
  onClose: () => void
  onCopy: () => void
  copied: boolean
}

const CertModal = ({ certContent, loading, onClose, onCopy, copied }: CertModalProps) => {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-6 w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Foreign Server CA Certificate</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            <XCircle size={24} />
          </button>
        </div>
        
        <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700 rounded-lg">
          <p className="text-sm text-blue-800 dark:text-blue-200">
            <strong>Foreign Server Installation:</strong> Copy the certificate below (click "Copy Certificate" button). 
            During foreign server installation, you will be prompted to paste this certificate.
          </p>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-gray-500 dark:text-gray-400">Loading certificate...</div>
          </div>
        ) : (
          <>
            <textarea
              readOnly
              value={certContent}
              className="flex-1 w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg font-mono text-sm bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 resize-none"
              style={{ minHeight: '300px' }}
            />
            
            <div className="flex justify-end gap-3 mt-4">
              <button
                type="button"
                onClick={async (e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  try {
                    if (certContent && certContent.trim().length > 0) {
                      await navigator.clipboard.writeText(certContent)
                      onCopy()
                    } else {
                      alert('Certificate content is empty. Please wait for it to load.')
                    }
                  } catch (error) {
                    console.error('Failed to copy:', error)
                    const textarea = e.currentTarget.closest('.bg-white, .dark\\:bg-gray-800')?.querySelector('textarea')
                    if (textarea) {
                      textarea.select()
                      textarea.setSelectionRange(0, 99999)
                      try {
                        document.execCommand('copy')
                        onCopy()
                      } catch (err) {
                        alert('Failed to copy to clipboard. Please select and copy manually from the text area above.')
                      }
                    } else {
                      alert('Failed to copy to clipboard. Please select and copy manually from the text area above.')
                    }
                  }
                }}
                disabled={loading || !certContent || certContent.trim().length === 0}
                className={`px-4 py-2 rounded-lg transition-colors flex items-center gap-2 ${
                  copied
                    ? 'bg-green-600 text-white'
                    : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed'
                }`}
              >
                <Copy size={16} />
                {copied ? 'Copied!' : 'Copy Certificate'}
              </button>
              <button
                onClick={onClose}
                className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

interface EditProxyModalProps {
  server: ProxyServerRow
  onClose: () => void
  onSuccess: () => void
}

const EditProxyModal = ({ server, onClose, onSuccess }: EditProxyModalProps) => {
  const { t } = useLanguage()
  const [mode, setMode] = useState<'warp' | 'proxy'>(server.mode === 'warp' ? 'warp' : 'proxy')
  const [proxyIp, setProxyIp] = useState(server.mode === 'proxy' ? server.proxy_ip || '' : '')
  const [proxyPort, setProxyPort] = useState(server.mode === 'proxy' ? server.proxy_port || '' : '')
  const [proxyType, setProxyType] = useState<'socks5' | 'http-connect'>((server.proxy_type as any) || 'socks5')
  const [proxyUser, setProxyUser] = useState(server.mode === 'proxy' ? server.proxy_user || '' : '')
  const [proxyPass, setProxyPass] = useState('')
  const [sshPassword, setSshPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const inputCls =
    'w-full px-3 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
  const labelCls = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1'

  const submit = async () => {
    setError('')
    if (mode === 'proxy' && (!proxyIp.trim() || !proxyPort.trim())) {
      setError(`${t.servers.fProxyIp} / ${t.servers.fProxyPort}`)
      return
    }
    if (!server.has_ssh_password && !sshPassword.trim()) {
      setError(t.servers.fSshPassword)
      return
    }
    setSubmitting(true)
    try {
      const res = await api.post(
        `/provisioning/proxy-servers/${server.id}/update-proxy`,
        {
          mode,
          proxy_ip: mode === 'proxy' ? proxyIp.trim() : null,
          proxy_port: mode === 'proxy' ? proxyPort.trim() : null,
          proxy_type: proxyType,
          proxy_user: mode === 'proxy' ? proxyUser || null : null,
          proxy_pass: mode === 'proxy' && proxyPass ? proxyPass : null,
          ssh_password: sshPassword || null,
        },
        { timeout: 200000 }
      )
      setResult(res.data.result)
      setTimeout(onSuccess, 1200)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || t.servers.updateFailed)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">{t.servers.editProxyTitle}</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4 font-mono" dir="ltr">{server.host}</p>

        <div className="space-y-4">
          <div>
            <label className={labelCls}>{t.servers.egressMode}</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setMode('warp')}
                className={`px-3 py-2 rounded-lg border-2 text-sm font-medium transition-all ${mode === 'warp' ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300' : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400'}`}
              >
                {t.servers.modeWarp}
              </button>
              <button
                type="button"
                onClick={() => setMode('proxy')}
                className={`px-3 py-2 rounded-lg border-2 text-sm font-medium transition-all ${mode === 'proxy' ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300' : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400'}`}
              >
                {t.servers.modeProxy}
              </button>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5" dir="auto">
              {mode === 'warp' ? t.servers.modeWarpHint : t.servers.modeProxyHint}
            </p>
          </div>

          {mode === 'proxy' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>{t.servers.fProxyIp}</label>
                <input className={inputCls} value={proxyIp} onChange={(e) => setProxyIp(e.target.value)} placeholder="1.2.3.4" dir="ltr" />
              </div>
              <div>
                <label className={labelCls}>{t.servers.fProxyPort}</label>
                <input className={inputCls} value={proxyPort} onChange={(e) => setProxyPort(e.target.value)} dir="ltr" />
              </div>
              <div>
                <label className={labelCls}>{t.servers.fProxyType}</label>
                <select className={inputCls} value={proxyType} onChange={(e) => setProxyType(e.target.value as any)} dir="ltr">
                  <option value="socks5">SOCKS5</option>
                  <option value="http-connect">HTTP-CONNECT</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>{t.servers.fProxyUser}</label>
                <input className={inputCls} value={proxyUser} onChange={(e) => setProxyUser(e.target.value)} dir="ltr" />
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>{t.servers.fProxyPass}</label>
                <input type="password" className={inputCls} value={proxyPass} onChange={(e) => setProxyPass(e.target.value)} dir="ltr" />
              </div>
            </div>
          )}

          <div>
            <label className={labelCls}>{t.servers.fSshPassword}</label>
            <input type="password" className={inputCls} value={sshPassword} onChange={(e) => setSshPassword(e.target.value)} dir="ltr" placeholder={server.has_ssh_password ? '••••••••' : ''} />
            {server.has_ssh_password && <p className="text-xs text-gray-400 mt-1" dir="auto">{t.servers.sshPassStoredHint}</p>}
          </div>

          {error && (
            <div className="px-3 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-300" dir="auto">{error}</div>
          )}
          {result && (
            <div className="px-3 py-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-sm text-green-700 dark:text-green-300" dir="auto">
              {t.servers.updateSuccess} ({result.proxyEndpoint} — {result.proxyStatus})
            </div>
          )}

          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600">
              {t.servers.cancel}
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={submitting}
              className="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all font-medium flex items-center gap-2 disabled:opacity-50"
            >
              {submitting ? <Loader2 size={18} className="animate-spin" /> : <Shield size={18} />}
              {submitting ? t.servers.applying : t.servers.apply}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Servers

