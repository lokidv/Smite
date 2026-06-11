import { useEffect, useState } from 'react'
import { Plus, Trash2, Edit2, RotateCw } from 'lucide-react'
import api from '../api/client'
import { parseAddressPort, formatAddressPort } from '../utils/addressUtils'
import { useLanguage } from '../contexts/LanguageContext'

interface Tunnel {
  id: string
  name: string
  core: string
  type: string
  node_id: string
  spec: Record<string, any>
  status: string
  error_message?: string | null
  revision: number
  created_at: string
  updated_at: string
}

type BackhaulTransport = 'tcp' | 'udp' | 'ws' | 'wsmux' | 'tcpmux'

interface BackhaulFormState {
  transport: BackhaulTransport
  control_port: string
  public_port: string
  listen_ip: string
  public_host: string
  remote_addr: string
  target_host: string
  target_port: string
  token: string
  accept_udp: boolean
}

interface BackhaulAdvancedServerState {
  keepalive_period: string
  heartbeat: string
  channel_size: string
  mux_con: string
  log_level: string
  nodelay: boolean
  skip_optz: boolean
  tls_cert: string
  tls_key: string
  sniffer: boolean
  web_port: string
  proxy_protocol: boolean
}

interface BackhaulAdvancedClientState {
  connection_pool: string
  retry_interval: string
  dial_timeout: string
  keepalive_period: string
  log_level: string
  nodelay: boolean
  aggressive_pool: boolean
  edge_ip: string
  skip_optz: boolean
}

interface BackhaulAdvancedState {
  server: BackhaulAdvancedServerState
  client: BackhaulAdvancedClientState
  customPorts: string
}

const createDefaultBackhaulState = (): BackhaulFormState => ({
  transport: 'tcp',
  control_port: '3080',
  public_port: '443',
  listen_ip: '0.0.0.0',
  public_host: '',
  remote_addr: '',
  target_host: '127.0.0.1',
  target_port: '8080',
  token: '',
  accept_udp: false,
})

const createDefaultBackhaulAdvancedState = (): BackhaulAdvancedState => ({
  server: {
    keepalive_period: '75',
    heartbeat: '40',
    channel_size: '2048',
    mux_con: '8',
    log_level: 'info',
    nodelay: true,
    skip_optz: false,
    tls_cert: '',
    tls_key: '',
    sniffer: false,
    web_port: '',
    proxy_protocol: false,
  },
  client: {
    connection_pool: '4',
    retry_interval: '3',
    dial_timeout: '10',
    keepalive_period: '75',
    log_level: 'info',
    nodelay: true,
    aggressive_pool: false,
    edge_ip: '',
    skip_optz: false,
  },
  customPorts: '',
})

type Udp2rawRawMode = 'faketcp' | 'icmp' | 'udp'

const UDP2RAW_RAW_MODES: Udp2rawRawMode[] = ['faketcp', 'icmp', 'udp']
const UDP2RAW_CIPHER_MODES = ['aes128cbc', 'aes128cfb', 'xor', 'none']
const UDP2RAW_AUTH_MODES = ['md5', 'crc32', 'simple', 'none']

interface Udp2rawFormState {
  raw_mode: Udp2rawRawMode
  listen_port: string
  raw_port: string
  target_host: string
  target_port: string
  key: string
  cipher_mode: string
  auth_mode: string
}

const createDefaultUdp2rawState = (): Udp2rawFormState => ({
  raw_mode: 'faketcp',
  listen_port: '4096',
  raw_port: '',
  target_host: '127.0.0.1',
  target_port: '',
  key: '',
  cipher_mode: 'aes128cbc',
  auth_mode: 'md5',
})

const buildUdp2rawSpec = (state: Udp2rawFormState, rawModeOverride?: string): Record<string, any> => {
  const rawModeCandidate = (rawModeOverride || state.raw_mode || 'faketcp') as Udp2rawRawMode
  const rawMode = UDP2RAW_RAW_MODES.includes(rawModeCandidate) ? rawModeCandidate : 'faketcp'

  const spec: Record<string, any> = {
    raw_mode: rawMode,
    cipher_mode: state.cipher_mode || 'aes128cbc',
    auth_mode: state.auth_mode || 'md5',
    target_host: state.target_host.trim() || '127.0.0.1',
  }

  const listenPort = parseInt(state.listen_port, 10)
  if (!Number.isNaN(listenPort) && listenPort > 0) {
    spec.listen_port = listenPort
    spec.ports = [listenPort]
  }

  const rawPort = parseInt(state.raw_port, 10)
  if (!Number.isNaN(rawPort) && rawPort > 0) {
    spec.raw_port = rawPort
  }

  const targetPort = parseInt(state.target_port, 10)
  if (!Number.isNaN(targetPort) && targetPort > 0) {
    spec.target_port = targetPort
  } else if (!Number.isNaN(listenPort) && listenPort > 0) {
    spec.target_port = listenPort
  }

  if (state.key.trim()) {
    spec.key = state.key.trim()
  }

  return spec
}

const parseUdp2rawSpec = (spec: Record<string, any> | undefined, currentType?: string): Udp2rawFormState => {
  const state = createDefaultUdp2rawState()
  const rawModeCandidate = ((spec?.raw_mode || currentType || 'faketcp') as string).toLowerCase() as Udp2rawRawMode
  if (UDP2RAW_RAW_MODES.includes(rawModeCandidate)) {
    state.raw_mode = rawModeCandidate
  }
  if (!spec) {
    return state
  }
  const listenPort = spec.listen_port ?? (Array.isArray(spec.ports) && spec.ports.length > 0 ? spec.ports[0] : undefined)
  if (listenPort) {
    state.listen_port = String(listenPort)
  }
  if (spec.raw_port) {
    state.raw_port = String(spec.raw_port)
  }
  if (spec.target_host) {
    state.target_host = String(spec.target_host)
  }
  if (spec.target_port) {
    state.target_port = String(spec.target_port)
  }
  state.key = spec.key ?? ''
  state.cipher_mode = spec.cipher_mode || state.cipher_mode
  state.auth_mode = spec.auth_mode || state.auth_mode
  return state
}

// ---- zapret (DPI desync / SNI bypass) ----
const ZAPRET_DESYNC_MODES = ['fake', 'fakedsplit', 'multisplit', 'multidisorder', 'disorder2', 'split2', 'syndata']
const ZAPRET_L7_FILTERS = ['tls', 'http', 'quic', 'none']
const ZAPRET_DIRECTIONS = ['both', 'out', 'in']

interface ZapretFormState {
  desync_mode: string
  filter_tcp: string
  filter_l7: string
  fake_tls_sni: string
  desync_fooling: string
  direction: string
  queue_num: string
  extra_args: string
}

const createDefaultZapretState = (): ZapretFormState => ({
  desync_mode: 'fake',
  filter_tcp: '443',
  filter_l7: 'tls',
  fake_tls_sni: 'hcaptcha.com',
  desync_fooling: 'badseq,ts',
  direction: 'both',
  queue_num: '',
  extra_args: '',
})

const buildZapretSpec = (state: ZapretFormState, desyncOverride?: string): Record<string, any> => {
  const modeCandidate = (desyncOverride || state.desync_mode || 'fake')
  const mode = ZAPRET_DESYNC_MODES.includes(modeCandidate) ? modeCandidate : 'fake'

  const spec: Record<string, any> = {
    desync_mode: mode,
    filter_tcp: state.filter_tcp.trim() || '443',
    filter_l7: state.filter_l7 || 'tls',
    desync_fooling: state.desync_fooling.trim(),
    direction: ZAPRET_DIRECTIONS.includes(state.direction) ? state.direction : 'both',
    max_pkt: 10,
  }

  if (state.fake_tls_sni.trim()) {
    spec.fake_tls_sni = state.fake_tls_sni.trim()
  }

  const queue = parseInt(state.queue_num, 10)
  if (!Number.isNaN(queue) && queue > 0) {
    spec.queue_num = queue
  }

  if (state.extra_args.trim()) {
    spec.extra_args = state.extra_args.trim()
  }

  return spec
}

const parseZapretSpec = (spec: Record<string, any> | undefined, currentType?: string): ZapretFormState => {
  const state = createDefaultZapretState()
  const modeCandidate = ((spec?.desync_mode || currentType || 'fake') as string).toLowerCase()
  if (ZAPRET_DESYNC_MODES.includes(modeCandidate)) {
    state.desync_mode = modeCandidate
  }
  if (!spec) {
    return state
  }
  if (spec.filter_tcp) state.filter_tcp = String(spec.filter_tcp)
  if (spec.filter_l7) state.filter_l7 = String(spec.filter_l7)
  state.fake_tls_sni = spec.fake_tls_sni ?? spec.fake_sni ?? state.fake_tls_sni
  if (spec.desync_fooling !== undefined) state.desync_fooling = String(spec.desync_fooling)
  if (spec.direction) state.direction = String(spec.direction)
  if (spec.queue_num) state.queue_num = String(spec.queue_num)
  if (spec.extra_args) state.extra_args = String(spec.extra_args)
  return state
}

const numericServerKeys = new Set([
  'keepalive_period',
  'heartbeat',
  'channel_size',
  'mux_con',
  'web_port',
])
const booleanServerKeys = new Set(['nodelay', 'skip_optz', 'sniffer', 'proxy_protocol'])
const stringServerKeys = new Set(['log_level', 'tls_cert', 'tls_key', 'sniffer_log'])

const numericClientKeys = new Set(['connection_pool', 'retry_interval', 'dial_timeout', 'keepalive_period'])
const booleanClientKeys = new Set(['nodelay', 'aggressive_pool', 'skip_optz'])
const stringClientKeys = new Set(['log_level', 'edge_ip'])

interface BackhaulDisplayInfo {
  controlPort: string
  publicPort: string
  target: string
}

const getBackhaulDisplayInfo = (spec: Record<string, any> | undefined): BackhaulDisplayInfo => {
  if (!spec) {
    return { controlPort: 'N/A', publicPort: 'N/A', target: 'N/A' }
  }

  const controlPort =
    spec.control_port ||
    (typeof spec.bind_addr === 'string' && spec.bind_addr.includes(':') ? spec.bind_addr.split(':').pop() : undefined) ||
    (typeof spec.remote_addr === 'string' && spec.remote_addr.includes(':') ? spec.remote_addr.split(':').pop() : undefined) ||
    'N/A'

  const publicPort =
    spec.public_port ||
    spec.listen_port ||
    (Array.isArray(spec.ports) && spec.ports.length > 0
      ? (() => {
          const [first] = spec.ports
          if (typeof first !== 'string') return undefined
          const [left] = first.split('=')
          const parts = left.split(':')
          return parts.pop()
        })()
      : undefined) ||
    'N/A'

  const target =
    spec.target_addr ||
    (Array.isArray(spec.ports) && spec.ports.length > 0
      ? (() => {
          const [first] = spec.ports
          if (typeof first !== 'string') return undefined
          const segments = first.split('=')
          return segments.length > 1 ? segments[1] : undefined
        })()
      : undefined) ||
    'N/A'

  return {
    controlPort: controlPort?.toString() || 'N/A',
    publicPort: publicPort?.toString() || 'N/A',
    target: target?.toString() || 'N/A',
  }
}

const Tunnels = () => {
  const { t } = useLanguage()
  const [tunnels, setTunnels] = useState<Tunnel[]>([])
  const [nodes, setNodes] = useState<any[]>([])
  const [servers, setServers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingTunnel, setEditingTunnel] = useState<Tunnel | null>(null)
  const [reapplyingAll, setReapplyingAll] = useState(false)

  useEffect(() => {
    fetchData()
    const params = new URLSearchParams(window.location.search)
    if (params.get('create') === 'true') {
      setShowAddModal(true)
      window.history.replaceState({}, '', '/tunnels')
    }
    
  }, [])

  const fetchData = async () => {
    try {
      const [tunnelsRes, nodesRes] = await Promise.all([
        api.get('/tunnels'),
        api.get('/nodes'),
      ])
      setTunnels(tunnelsRes.data)
      // Filter nodes: iran nodes and foreign servers
      const iranNodes = nodesRes.data.filter((node: any) => 
        node.metadata?.role === 'iran' || !node.metadata?.role  // Default to iran for backward compatibility
      )
      const foreignServers = nodesRes.data.filter((node: any) => 
        node.metadata?.role === 'foreign'
      )
      setNodes(iranNodes)
      setServers(foreignServers)
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  const deleteTunnel = async (id: string) => {
    if (!confirm('Are you sure you want to delete this tunnel?')) return
    
    try {
      await api.delete(`/tunnels/${id}`)
      fetchData()
    } catch (error) {
      console.error('Failed to delete tunnel:', error)
      alert('Failed to delete tunnel')
    }
  }

  const reapplyTunnel = async (tunnel: Tunnel) => {
    try {
      const response = await api.post(`/tunnels/${tunnel.id}/apply`)
      if (response.data && response.data.status === 'success') {
        fetchData()
      } else {
        throw new Error(response.data?.message || 'Failed to reapply tunnel')
      }
    } catch (error: any) {
      console.error('Failed to reapply tunnel:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to reapply tunnel'
      alert(errorMessage)
    }
  }

  const handleReapplyAll = async () => {
    if (!confirm(t.tunnels.confirmReapplyAll || 'Are you sure you want to reapply all tunnels?')) return
    
    setReapplyingAll(true)
    try {
      const response = await api.post('/tunnels/reapply-all')
      if (response.data && response.data.status === 'success') {
        alert(`${t.tunnels.reapplyAllSuccess || 'Success'}: ${response.data.message}`)
        fetchData()
      } else {
        throw new Error(response.data?.message || 'Failed to reapply all tunnels')
      }
    } catch (error: any) {
      console.error('Failed to reapply all tunnels:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to reapply all tunnels'
      alert(errorMessage)
    } finally {
      setReapplyingAll(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 dark:border-blue-400 mb-4"></div>
          <p className="text-gray-500 dark:text-gray-400">{t.tunnels.loadingTunnels}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">{t.tunnels.title}</h1>
          <p className="text-gray-500 dark:text-gray-400">{t.tunnels.subtitle}</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleReapplyAll}
            disabled={reapplyingAll}
            className="px-5 py-2.5 bg-gradient-to-r from-green-600 to-emerald-600 text-white rounded-lg hover:from-green-700 hover:to-emerald-700 transition-all duration-200 font-medium shadow-sm hover:shadow-md flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RotateCw size={20} className={reapplyingAll ? "animate-spin" : ""} />
            {t.tunnels.reapplyAll}
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all duration-200 font-medium shadow-sm hover:shadow-md flex items-center gap-2"
          >
            <Plus size={20} />
            {t.tunnels.createTunnel}
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {tunnels.map((tunnel) => {
          // Extract ports from spec
          const getPorts = (): string => {
            if (tunnel.core === 'zapret') {
              return (tunnel.spec?.filter_tcp || '443').toString()
            }
            if (tunnel.spec?.ports) {
              if (Array.isArray(tunnel.spec.ports)) {
                // For Backhaul, ports are in format "8080=127.0.0.1:8080", extract just the port numbers
                if (tunnel.core === 'backhaul' && typeof tunnel.spec.ports[0] === 'string' && tunnel.spec.ports[0].includes('=')) {
                  return tunnel.spec.ports.map(p => {
                    const portPart = p.split('=')[0]
                    const port = portPart.includes(':') ? portPart.split(':')[1] : portPart
                    return port
                  }).join(', ')
                }
                // For other cores, ports are numbers
                return tunnel.spec.ports.map(p => typeof p === 'object' && p.local ? p.local : p).join(', ')
              } else if (typeof tunnel.spec.ports === 'string') {
                return tunnel.spec.ports
              }
            }
            // Fallback to single port
            const port = tunnel.spec?.listen_port || tunnel.spec?.remote_port
            return port ? port.toString() : 'N/A'
          }

          // Get core badge color
          const getCoreBadge = () => {
            const coreColors: Record<string, { bg: string; text: string; border: string }> = {
              rathole: { bg: 'bg-purple-100 dark:bg-purple-900/30', text: 'text-purple-800 dark:text-purple-200', border: 'border-purple-300 dark:border-purple-700' },
              backhaul: { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-800 dark:text-blue-200', border: 'border-blue-300 dark:border-blue-700' },
              chisel: { bg: 'bg-orange-100 dark:bg-orange-900/30', text: 'text-orange-800 dark:text-orange-200', border: 'border-orange-300 dark:border-orange-700' },
              frp: { bg: 'bg-cyan-100 dark:bg-cyan-900/30', text: 'text-cyan-800 dark:text-cyan-200', border: 'border-cyan-300 dark:border-cyan-700' },
              gost: { bg: 'bg-indigo-100 dark:bg-indigo-900/30', text: 'text-indigo-800 dark:text-indigo-200', border: 'border-indigo-300 dark:border-indigo-700' },
              udp2raw: { bg: 'bg-rose-100 dark:bg-rose-900/30', text: 'text-rose-800 dark:text-rose-200', border: 'border-rose-300 dark:border-rose-700' },
              zapret: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
            }
            return coreColors[tunnel.core] || { bg: 'bg-gray-100 dark:bg-gray-700', text: 'text-gray-800 dark:text-gray-200', border: 'border-gray-300 dark:border-gray-600' }
          }

          const coreBadge = getCoreBadge()
          const ports = getPorts()
          const iranNode = nodes.find(n => n.id === tunnel.iran_node_id || n.id === tunnel.node_id)
            || (tunnel.core === 'zapret' ? servers.find(s => s.id === tunnel.node_id) : undefined)
          const foreignServer = servers.find(s => s.id === tunnel.foreign_node_id)

          return (
            <div
              key={tunnel.id}
              className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 transition-all hover:shadow-lg hover:border-gray-300 dark:hover:border-gray-600"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-4 flex-1 min-w-0">
                  {/* Status Badge */}
                  <span
                    className={`px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap shrink-0 ${
                      tunnel.status === 'active'
                        ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200'
                        : tunnel.status === 'error'
                        ? 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200'
                    }`}
                  >
                    {tunnel.status}
                  </span>

                  <div className="flex-1 min-w-0">
                    {/* Name, Core Badge, Transmission Badge, and Ports in one line */}
                    <div className="flex items-center gap-3 mb-2 flex-wrap">
                      <h3 className="text-base font-semibold text-gray-900 dark:text-white truncate">{tunnel.name}</h3>
                      <span
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wide border ${coreBadge.bg} ${coreBadge.text} ${coreBadge.border} shrink-0`}
                      >
                        {tunnel.core}
                      </span>
                      {(() => {
                        let transmissionType = null
                        if (tunnel.core === 'chisel') {
                          transmissionType = 'TCP'
                        } else if (tunnel.core === 'rathole') {
                          const transport = tunnel.spec?.transport || (tunnel.type && tunnel.type !== 'rathole' ? tunnel.type : 'tcp')
                          transmissionType = transport.toUpperCase()
                        } else if (tunnel.type && tunnel.type.toLowerCase() !== tunnel.core.toLowerCase()) {
                          transmissionType = tunnel.type.toUpperCase()
                        }
                        
                        if (!transmissionType) return null
                        
                        const getTransmissionBadge = () => {
                          const typeColors: Record<string, { bg: string; text: string; border: string }> = {
                            TCP: { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-800 dark:text-green-200', border: 'border-green-300 dark:border-green-700' },
                            UDP: { bg: 'bg-yellow-100 dark:bg-yellow-900/30', text: 'text-yellow-800 dark:text-yellow-200', border: 'border-yellow-300 dark:border-yellow-700' },
                            WS: { bg: 'bg-pink-100 dark:bg-pink-900/30', text: 'text-pink-800 dark:text-pink-200', border: 'border-pink-300 dark:border-pink-700' },
                            WSS: { bg: 'bg-pink-100 dark:bg-pink-900/30', text: 'text-pink-800 dark:text-pink-200', border: 'border-pink-300 dark:border-pink-700' },
                            GRPC: { bg: 'bg-teal-100 dark:bg-teal-900/30', text: 'text-teal-800 dark:text-teal-200', border: 'border-teal-300 dark:border-teal-700' },
                            TCPMUX: { bg: 'bg-violet-100 dark:bg-violet-900/30', text: 'text-violet-800 dark:text-violet-200', border: 'border-violet-300 dark:border-violet-700' },
                            FAKETCP: { bg: 'bg-rose-100 dark:bg-rose-900/30', text: 'text-rose-800 dark:text-rose-200', border: 'border-rose-300 dark:border-rose-700' },
                            ICMP: { bg: 'bg-amber-100 dark:bg-amber-900/30', text: 'text-amber-800 dark:text-amber-200', border: 'border-amber-300 dark:border-amber-700' },
                            FAKE: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                            FAKEDSPLIT: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                            MULTISPLIT: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                            MULTIDISORDER: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                            DISORDER2: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                            SPLIT2: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                            SYNDATA: { bg: 'bg-emerald-100 dark:bg-emerald-900/30', text: 'text-emerald-800 dark:text-emerald-200', border: 'border-emerald-300 dark:border-emerald-700' },
                          }
                          return typeColors[transmissionType] || { bg: 'bg-gray-100 dark:bg-gray-700', text: 'text-gray-800 dark:text-gray-200', border: 'border-gray-300 dark:border-gray-600' }
                        }
                        
                        const transmissionBadge = getTransmissionBadge()
                        return (
                          <span
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wide border ${transmissionBadge.bg} ${transmissionBadge.text} ${transmissionBadge.border} shrink-0`}
                          >
                            {transmissionType}
                          </span>
                        )
                      })()}
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Ports:</span>
                        <span className="text-sm font-mono font-semibold text-gray-700 dark:text-gray-300">{ports}</span>
                      </div>
                    </div>

                    {/* Core Port, Node and Server Info */}
                    <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
                      {(() => {
                        let corePort = null
                        if (tunnel.core === 'rathole') {
                          if (tunnel.spec?.bind_addr) {
                            const match = tunnel.spec.bind_addr.match(/:(\d+)$/)
                            if (match) corePort = match[1]
                          }
                          if (!corePort && tunnel.spec?.control_port) {
                            corePort = tunnel.spec.control_port
                          }
                          if (!corePort) {
                            const remoteAddr = tunnel.spec?.remote_addr || ''
                            const match = remoteAddr.match(/:(\d+)$/)
                            if (match) corePort = match[1]
                          }
                          if (!corePort) corePort = '23333'
                        } else if (tunnel.core === 'chisel') {
                          corePort = tunnel.spec?.control_port || tunnel.spec?.server_port
                        } else if (tunnel.core === 'backhaul') {
                          corePort = tunnel.spec?.control_port || tunnel.spec?.public_port || '3080'
                        } else if (tunnel.core === 'frp') {
                          corePort = tunnel.spec?.bind_port || '7000'
                        } else if (tunnel.core === 'udp2raw') {
                          corePort = tunnel.spec?.raw_port
                        } else if (tunnel.core === 'zapret') {
                          corePort = tunnel.spec?.queue_num || null
                        }
                        return corePort ? (
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium">Core Port:</span>
                            <span className="text-gray-700 dark:text-gray-300 font-mono">{corePort}</span>
                          </div>
                        ) : null
                      })()}
                      {iranNode && (
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium">Node:</span>
                          <span className="text-gray-700 dark:text-gray-300">{iranNode.name || iranNode.id.substring(0, 8)}</span>
                        </div>
                      )}
                      {foreignServer && (
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium">Server:</span>
                          <span className="text-gray-700 dark:text-gray-300">{foreignServer.name || foreignServer.id.substring(0, 8)}</span>
                        </div>
                      )}
                    </div>

                    {/* Error Message */}
                    {tunnel.status === 'error' && tunnel.error_message && (
                      <div className="mt-2 text-xs text-red-600 dark:text-red-400">
                        {tunnel.error_message}
                      </div>
                    )}
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => reapplyTunnel(tunnel)}
                    className="p-2.5 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded-lg transition-colors"
                    title="Reapply tunnel"
                  >
                    <RotateCw size={18} />
                  </button>
                  <button
                    onClick={() => setEditingTunnel(tunnel)}
                    className="p-2.5 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors"
                    title="Edit tunnel"
                  >
                    <Edit2 size={18} />
                  </button>
                  <button
                    onClick={() => deleteTunnel(tunnel.id)}
                    className="p-2.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    title="Delete tunnel"
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {showAddModal && (
        <AddTunnelModal
          nodes={nodes}
          servers={servers}
          onClose={() => setShowAddModal(false)}
          onSuccess={() => {
            setShowAddModal(false)
            fetchData()
          }}
        />
      )}

      {editingTunnel && (
        <EditTunnelModal
          tunnel={editingTunnel}
          nodes={nodes}
          onClose={() => setEditingTunnel(null)}
          onSuccess={() => {
            setEditingTunnel(null)
            fetchData()
          }}
        />
      )}
    </div>
  )
}

interface EditTunnelModalProps {
  tunnel: Tunnel
  nodes: any[]
  onClose: () => void
  onSuccess: () => void
}

const EditTunnelModal = ({ tunnel, onClose, onSuccess }: EditTunnelModalProps) => {
  const { t } = useLanguage()
  const forwardToParsed = tunnel.spec?.forward_to ? parseAddressPort(tunnel.spec.forward_to) : null
  const remoteIp = tunnel.spec?.remote_ip || forwardToParsed?.host || '127.0.0.1'
  const remotePort = tunnel.spec?.remote_port || forwardToParsed?.port || 8080
  
  // Parse ports from spec
  const parsePortsFromSpec = (spec: Record<string, any>): string => {
    if (spec?.ports) {
      if (Array.isArray(spec.ports)) {
        // For Backhaul, ports are in format "8080=127.0.0.1:8080" or "0.0.0.0:8080=127.0.0.1:8080"
        // Extract just the port number (first number before = or after :)
        return spec.ports.map(p => {
          if (typeof p === 'object' && p.local) {
            return p.local.toString()
          } else if (typeof p === 'string') {
            // Handle Backhaul format: "8080=127.0.0.1:8080" or "0.0.0.0:8080=127.0.0.1:8080"
            if (p.includes('=')) {
              const leftPart = p.split('=')[0]
              // Extract port from left part (could be "8080" or "0.0.0.0:8080")
              if (leftPart.includes(':')) {
                return leftPart.split(':')[1]
              }
              return leftPart
            }
            // If it's just a number, return as-is
            return p
          }
          return p.toString()
        }).join(',')
      } else if (typeof spec.ports === 'string') {
        return spec.ports
      }
    }
    // Fallback to single port
    return (spec?.listen_port || spec?.remote_port || 8080).toString()
  }
  
  const [formData, setFormData] = useState({
    name: tunnel.name,
    ports: parsePortsFromSpec(tunnel.spec || {}),
    remote_ip: remoteIp,
    rathole_remote_addr: tunnel.spec?.remote_addr ? (() => {
      const parsed = parseAddressPort(tunnel.spec.remote_addr)
      return parsed.port?.toString() || ''
    })() : '',
    chisel_control_port: tunnel.spec?.control_port ? tunnel.spec.control_port.toString() : '',
    frp_bind_port: tunnel.spec?.bind_port ? tunnel.spec.bind_port.toString() : '7000',
    frp_token: tunnel.spec?.token || '',
    frp_local_ip: tunnel.spec?.local_ip || '127.0.0.1',
    node_ipv6: tunnel.spec?.node_ipv6 || '',
  })
  const parsedBackhaul = parseBackhaulSpec(tunnel.spec, tunnel.type)
  const [backhaulState, setBackhaulState] = useState<BackhaulFormState>(parsedBackhaul.state)
  const [backhaulAdvanced, setBackhaulAdvanced] = useState<BackhaulAdvancedState>(parsedBackhaul.advanced)
  const [showBackhaulAdvanced, setShowBackhaulAdvanced] = useState(false)
  const [udp2rawState, setUdp2rawState] = useState<Udp2rawFormState>(() => parseUdp2rawSpec(tunnel.spec, tunnel.type))
  const [zapretState, setZapretState] = useState<ZapretFormState>(() => parseZapretSpec(tunnel.spec, tunnel.type))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      let updatedSpec = { ...tunnel.spec }
      
      const useV4ToV6 = updatedSpec.use_ipv6 || false
      
      // Parse comma-separated ports
      const parsePorts = (portsStr: string): number[] => {
        return portsStr
          .split(',')
          .map(p => p.trim())
          .filter(p => p)
          .map(p => parseInt(p))
          .filter(p => !isNaN(p) && p > 0 && p <= 65535)
      }
      
      const ports = parsePorts(formData.ports)
      if (ports.length === 0) {
        alert('Please enter at least one valid port')
        return
      }
      
      if (tunnel.core === 'rathole') {
        if (formData.rathole_remote_addr) {
          const remoteHost = window.location.hostname
          const remotePort = formData.rathole_remote_addr.includes(':') 
            ? formData.rathole_remote_addr.split(':')[1] 
            : formData.rathole_remote_addr
          updatedSpec.remote_addr = `${remoteHost}:${remotePort || '23333'}`
        }
        if (formData.node_ipv6) {
          updatedSpec.node_ipv6 = formData.node_ipv6
        }
        updatedSpec.ports = ports
        updatedSpec.remote_port = ports[0]  // Keep for backward compatibility
        updatedSpec.listen_port = ports[0]  // Keep for backward compatibility
      } else if (tunnel.core === 'gost' && (tunnel.type === 'tcp' || tunnel.type === 'udp' || tunnel.type === 'grpc' || tunnel.type === 'tcpmux')) {
        const remoteIp = formData.remote_ip || '127.0.0.1'
        updatedSpec.remote_ip = remoteIp
        updatedSpec.ports = ports
        updatedSpec.remote_port = ports[0]  // Keep for backward compatibility
        updatedSpec.listen_port = ports[0]  // Keep for backward compatibility
      } else if (tunnel.core === 'chisel') {
        updatedSpec.ports = ports
        const firstPort = ports[0]
        updatedSpec.listen_port = firstPort
        updatedSpec.remote_port = firstPort
        const controlPort = formData.chisel_control_port 
          ? parseInt(formData.chisel_control_port.toString())
          : firstPort + 10000
        updatedSpec.control_port = controlPort
        if (formData.node_ipv6) {
          updatedSpec.node_ipv6 = formData.node_ipv6
        }
      } else if (tunnel.core === 'frp') {
        const bindPort = parseInt(formData.frp_bind_port) || 7000
        updatedSpec.bind_port = bindPort
        updatedSpec.ports = ports
        updatedSpec.listen_port = ports[0]  // Keep for backward compatibility
        updatedSpec.remote_port = ports[0]  // Keep for backward compatibility
        if (formData.frp_token) {
          updatedSpec.token = formData.frp_token
        } else {
          delete updatedSpec.token
        }
        updatedSpec.local_ip = formData.frp_local_ip || '127.0.0.1'
        updatedSpec.local_port = ports[0]  // Keep for backward compatibility
        updatedSpec.type = tunnel.type === 'udp' ? 'udp' : 'tcp'
      } else if (tunnel.core === 'backhaul') {
        updatedSpec = buildBackhaulSpec(backhaulState, backhaulAdvanced, tunnel.type as BackhaulTransport)
        // Override ports if provided
        if (ports.length > 0) {
          const targetHost = updatedSpec.target_host || '127.0.0.1'
          updatedSpec.ports = ports.map(p => `${p}=${targetHost}:${p}`)
        }
      } else if (tunnel.core === 'udp2raw') {
        updatedSpec = { ...tunnel.spec, ...buildUdp2rawSpec(udp2rawState, tunnel.type) }
      } else if (tunnel.core === 'zapret') {
        updatedSpec = { ...tunnel.spec, ...buildZapretSpec(zapretState, tunnel.type) }
      }

      await api.put(`/tunnels/${tunnel.id}`, {
        name: formData.name,
        spec: updatedSpec,
      })
      onSuccess()
    } catch (error) {
      console.error('Failed to update tunnel:', error)
      alert('Failed to update tunnel')
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[100]">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-6 w-full max-w-md">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">Edit Tunnel</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t.tunnels.name}
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
              required
            />
          </div>
          {tunnel.core === 'gost' && (tunnel.type === 'tcp' || tunnel.type === 'udp' || tunnel.type === 'grpc' || tunnel.type === 'tcpmux') && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.tunnels.remoteIP}
                </label>
                <input
                  type="text"
                  value={formData.remote_ip}
                  onChange={(e) =>
                    setFormData({ ...formData, remote_ip: e.target.value || '127.0.0.1' })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="127.0.0.1 or [2001:db8::1]"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {t.tunnels.remoteIPDescription}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Ports
                </label>
                <input
                  type="text"
                  value={formData.ports}
                  onChange={(e) =>
                    setFormData({ ...formData, ports: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="8080,8081,8082"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Ports (comma-separated, same for panel and target server)
                </p>
              </div>
            </>
          )}
          
          {tunnel.core === 'backhaul' && (
            <BackhaulForm
              state={backhaulState}
              onChange={(partial) => {
                setBackhaulState((prev) => ({ ...prev, ...partial }))
              }}
              onOpenAdvanced={() => setShowBackhaulAdvanced(true)}
              acceptUdpVisible={
                backhaulState.transport === 'tcp' || backhaulState.transport === 'tcpmux'
              }
            />
          )}
          
          {tunnel.core === 'udp2raw' && (
            <Udp2rawForm
              state={udp2rawState}
              onChange={(partial) => {
                setUdp2rawState((prev) => ({ ...prev, ...partial }))
              }}
            />
          )}

          {tunnel.core === 'zapret' && (
            <ZapretForm
              state={zapretState}
              onChange={(partial) => {
                setZapretState((prev) => ({ ...prev, ...partial }))
              }}
            />
          )}
          
          {tunnel.core === 'rathole' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Ports
              </label>
              <input
                type="text"
                value={formData.ports}
                onChange={(e) =>
                  setFormData({ ...formData, ports: e.target.value })
                }
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                placeholder="8080,8081,8082"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Ports (comma-separated, same for panel and node local service)
              </p>
            </div>
          )}
          
          {tunnel.core === 'rathole' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Rathole Port
                </label>
                <input
                  type="number"
                  value={formData.rathole_remote_addr ? formData.rathole_remote_addr.split(':')[1] || formData.rathole_remote_addr : ''}
                  onChange={(e) => {
                    const port = e.target.value
                    const host = window.location.hostname
                    setFormData({ ...formData, rathole_remote_addr: port ? `${host}:${port}` : '' })
                  }}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="23333"
                  min="1"
                  max="65535"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Rathole server port on panel (IP: {window.location.hostname})</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Local Port
                </label>
                <input
                  type="number"
                  value={formData.rathole_local_port}
                  onChange={(e) =>
                    setFormData({ ...formData, rathole_local_port: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="8080"
                  min="1"
                  max="65535"
                />
              </div>
            </>
          )}
          
          {tunnel.core === 'chisel' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Ports
                </label>
                <input
                  type="text"
                  value={formData.ports}
                  onChange={(e) =>
                    setFormData({ ...formData, ports: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="8080,8081,8082"
                  required
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Ports (comma-separated, same for reverse port and local port)
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Control Port
                </label>
                <input
                  type="number"
                  value={formData.chisel_control_port}
                  onChange={(e) =>
                    setFormData({ ...formData, chisel_control_port: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder={`${(parseInt(formData.ports.split(',')[0]?.trim()) || 8080) + 10000} (auto)`}
                  min="1"
                  max="65535"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Chisel server control port (leave empty for auto: first port + 10000)
                </p>
              </div>
              {/* Node IPv6 address field for Chisel when v4 to v6 is enabled */}
              {tunnel.spec?.use_ipv6 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Node IPv6 Address (Optional)
                  </label>
                  <input
                    type="text"
                    value={formData.node_ipv6}
                    onChange={(e) =>
                      setFormData({ ...formData, node_ipv6: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                    placeholder="::1 or 2001:db8::1"
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    IPv6 address of the node. Leave empty to use ::1 (localhost IPv6)
                  </p>
                </div>
              )}
            </>
          )}
          
          {tunnel.core === 'frp' && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Bind Port
                  </label>
                  <input
                    type="number"
                    value={formData.frp_bind_port}
                    onChange={(e) =>
                      setFormData({ ...formData, frp_bind_port: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                    placeholder="7000"
                    min="1"
                    max="65535"
                    required
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    FRP server port on panel (default: 7000)
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Ports
                  </label>
                  <input
                    type="text"
                    value={formData.ports}
                    onChange={(e) =>
                      setFormData({ ...formData, ports: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                    placeholder="8080,8081,8082"
                    required
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Ports (comma-separated, same for remote port and local port)
                  </p>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Token (Optional - Auto-generated if empty)
                </label>
                <input
                  type="text"
                  value={formData.frp_token}
                  onChange={(e) =>
                    setFormData({ ...formData, frp_token: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="Leave empty for auto-generation"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Authentication token (will be auto-generated if not provided)</p>
              </div>
            </>
          )}
          
          {/* Node IPv6 address field for Rathole when v4 to v6 is enabled */}
          {tunnel.core === 'rathole' && tunnel.spec?.use_ipv6 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Node IPv6 Address (Optional)
              </label>
              <input
                type="text"
                value={formData.node_ipv6}
                onChange={(e) =>
                  setFormData({ ...formData, node_ipv6: e.target.value })
                }
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                placeholder="::1 or 2001:db8::1"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                IPv6 address of the node. Leave empty to use ::1 (localhost IPv6)
              </p>
            </div>
          )}
          
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              {t.tunnels.cancel}
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Save Changes
            </button>
          </div>
        </form>
        <BackhaulAdvancedDrawer
          open={showBackhaulAdvanced}
          state={backhaulAdvanced}
          onClose={() => setShowBackhaulAdvanced(false)}
          onChange={setBackhaulAdvanced}
        />
      </div>
    </div>
  )
}

interface AddTunnelModalProps {
  nodes: any[]
  servers: any[]
  onClose: () => void
  onSuccess: () => void
}

const AddTunnelModal = ({ nodes, servers, onClose, onSuccess }: AddTunnelModalProps) => {
  const { t } = useLanguage()
  const [formData, setFormData] = useState({
    name: '',
    core: 'gost',
    type: 'tcp',
    node_id: '',
    foreign_node_id: '',
    iran_node_id: '',
    ports: '8080',  // Comma-separated ports (e.g., "8080,8081,8082")
    remote_ip: '127.0.0.1',
    rathole_remote_addr: '23333',
    rathole_token: '',
    chisel_control_port: '',  // Empty means auto (listen_port + 10000)
    frp_bind_port: '7000',
    frp_token: '',
    frp_local_ip: '127.0.0.1',
    use_ipv6: false,
    node_ipv6: '',  // Optional IPv6 address for node (Rathole/Chisel)
    spec: {} as Record<string, any>,
  })
  const [backhaulState, setBackhaulState] = useState<BackhaulFormState>(createDefaultBackhaulState())
  const [backhaulAdvanced, setBackhaulAdvanced] = useState<BackhaulAdvancedState>(createDefaultBackhaulAdvancedState())
  const [showBackhaulAdvanced, setShowBackhaulAdvanced] = useState(false)
  const [udp2rawState, setUdp2rawState] = useState<Udp2rawFormState>(createDefaultUdp2rawState())
  const [zapretState, setZapretState] = useState<ZapretFormState>(createDefaultZapretState())

  // Auto-populate remote_ip with foreign server IP when GOST is selected
  useEffect(() => {
    if (formData.core === 'gost' && formData.foreign_node_id) {
      const selectedServer = servers.find(s => s.id === formData.foreign_node_id)
      if (selectedServer?.metadata?.ip_address) {
        setFormData(prev => ({
          ...prev,
          remote_ip: selectedServer.metadata.ip_address
        }))
      }
    }
  }, [formData.foreign_node_id, formData.core, servers])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      let spec = getSpecForType(formData.core, formData.type)
      let tunnelType = formData.type
      
      spec.use_ipv6 = formData.use_ipv6 || false
      
      // Parse comma-separated ports
      const parsePorts = (portsStr: string): number[] => {
        return portsStr
          .split(',')
          .map(p => p.trim())
          .filter(p => p)
          .map(p => parseInt(p))
          .filter(p => !isNaN(p) && p > 0 && p <= 65535)
      }
      
      const ports = parsePorts(formData.ports)
      if (ports.length === 0) {
        alert('Please enter at least one valid port')
        return
      }
      
      if (formData.core === 'gost' && (formData.type === 'tcp' || formData.type === 'udp' || formData.type === 'grpc' || formData.type === 'tcpmux')) {
        const remoteIp = formData.remote_ip || (formData.use_ipv6 ? '::1' : '127.0.0.1')
        // For GOST, ports are equal (listen_port = forward_to port)
        spec.remote_ip = remoteIp
        spec.ports = ports  // Store multiple ports
        spec.listen_port = ports[0]  // Keep first port for backward compatibility
        spec.remote_port = ports[0]  // Keep first port for backward compatibility
      }
      
      if (formData.core === 'rathole') {
        const remoteHost = window.location.hostname
        const remotePort = formData.rathole_remote_addr || '23333'
        spec.remote_addr = `${remoteHost}:${remotePort}`
        if (formData.rathole_token) {
          spec.token = formData.rathole_token
        }
        spec.ports = ports
        spec.remote_port = ports[0]
        spec.listen_port = ports[0]
      }
      
      if (formData.core === 'chisel') {
        // For Chisel, ports are equal (reverse_port = local_port)
        spec.ports = ports  // Store multiple ports
        const firstPort = ports[0]
        spec.listen_port = firstPort
        spec.remote_port = firstPort
        spec.server_port = firstPort
        const controlPort = formData.chisel_control_port 
          ? parseInt(formData.chisel_control_port.toString())
          : firstPort + 10000
        spec.control_port = controlPort
        const panelHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost'
        spec.panel_host = panelHost
      }
      
      if (formData.core === 'backhaul') {
        if (!formData.node_id) {
          alert('Backhaul tunnels require a node')
          return
        }
        // CRITICAL: For Backhaul, the Ports field is in BackhaulForm, not in the main formData.ports
        // backhaulState.public_port contains the comma-separated ports from the Backhaul form
        // We should use backhaulState.public_port, NOT formData.ports (which is for other cores)
        console.log('Backhaul tunnel creation - formData.ports:', formData.ports, 'type:', typeof formData.ports)
        console.log('Backhaul tunnel creation - backhaulState.public_port:', backhaulState.public_port)
        
        // Use backhaulState.public_port (from BackhaulForm) - it has the correct comma-separated ports
        // Only fallback to formData.ports if backhaulState.public_port is empty
        const portsToUse = backhaulState.public_port && backhaulState.public_port.trim() 
          ? backhaulState.public_port 
          : (formData.ports || '8080')
        
        const updatedBackhaulState = {
          ...backhaulState,
          public_port: portsToUse,
          target_port: portsToUse
        }
        console.log('Backhaul tunnel creation - updatedBackhaulState.public_port (final):', updatedBackhaulState.public_port)
        spec = buildBackhaulSpec(updatedBackhaulState, backhaulAdvanced)
        spec.use_ipv6 = formData.use_ipv6 || false
        // buildBackhaulSpec should already build ports array from public_port (formData.ports)
        // Verify ports were built correctly - if not, build them from parsed ports
        if (!spec.ports || !Array.isArray(spec.ports) || spec.ports.length === 0) {
          // buildBackhaulSpec didn't build ports, so build them from formData.ports
          if (backhaulAdvanced.customPorts && backhaulAdvanced.customPorts.trim()) {
            // Use customPorts if provided
            spec.ports = backhaulAdvanced.customPorts
              .split(/\r?\n/)
              .map((line) => line.trim())
              .filter(Boolean)
          } else if (ports.length > 0) {
            // Build from parsed ports (numbers) - format: "port=targetHost:port"
            const targetHost = spec.target_host || '127.0.0.1'
            const listenIp = spec.listen_ip || updatedBackhaulState.listen_ip || '0.0.0.0'
            spec.ports = ports.map(p => {
              // Format: "port=targetHost:port" or "listenIp:port=targetHost:port" if listenIp is set
              const listenPart = listenIp !== '0.0.0.0' ? `${listenIp}:${p}` : `${p}`
              return `${listenPart}=${targetHost}:${p}`
            })
          }
        }
        // Ensure ports array is properly formatted and has all ports
        if (spec.ports && Array.isArray(spec.ports) && spec.ports.length > 0) {
          console.log('Backhaul tunnel creation - final ports:', spec.ports, 'count:', spec.ports.length)
        } else {
          console.warn('Backhaul tunnel creation - no ports found! formData.ports:', formData.ports, 'publicPorts:', updatedBackhaulState.public_port)
        }
        tunnelType = backhaulState.transport
      }
      
      if (formData.core === 'frp') {
        if (!formData.node_id) {
          alert('FRP tunnels require a node')
          return
        }
        const bindPort = parseInt(formData.frp_bind_port) || 7000
        spec.bind_port = bindPort
        spec.ports = ports
        spec.listen_port = ports[0]
        spec.remote_port = ports[0]
        if (formData.frp_token) {
          spec.token = formData.frp_token
        }
        spec.local_ip = formData.frp_local_ip || '127.0.0.1'
        spec.local_port = ports[0]
        spec.type = formData.type === 'udp' ? 'udp' : 'tcp'
        tunnelType = formData.type === 'udp' ? 'udp' : 'tcp'
      }
      
      if (formData.core === 'udp2raw') {
        if (!formData.node_id && !formData.iran_node_id) {
          alert('udp2raw tunnels require an iran node')
          return
        }
        const listenPort = parseInt(udp2rawState.listen_port, 10)
        if (Number.isNaN(listenPort) || listenPort <= 0) {
          alert('Please enter a valid listen port for udp2raw')
          return
        }
        spec = buildUdp2rawSpec(udp2rawState)
        spec.use_ipv6 = formData.use_ipv6 || false
        tunnelType = udp2rawState.raw_mode
      }

      if (formData.core === 'zapret') {
        if (!formData.node_id && !formData.iran_node_id) {
          alert('zapret requires a node (the server running the proxy / outbound TLS)')
          return
        }
        spec = buildZapretSpec(zapretState)
        tunnelType = zapretState.desync_mode
      }
      
      const payload = {
        name: formData.name,
        core: formData.core,
        type: tunnelType,
        node_id: formData.node_id || formData.iran_node_id || null,
        foreign_node_id: formData.foreign_node_id || null,
        iran_node_id: formData.iran_node_id || formData.node_id || null,
        spec: spec,
      }
      await api.post('/tunnels', payload)
      onSuccess()
    } catch (error) {
      console.error('Failed to create tunnel:', error)
      alert('Failed to create tunnel')
    }
  }

  const getSpecForType = (core: string, type: string): Record<string, any> => {
    const baseSpec: Record<string, any> = {}

    if (core === 'rathole') {
      return { ...baseSpec, remote_addr: '', token: '', local_addr: '127.0.0.1:8080' }
    }

    switch (type) {
      case 'grpc':
        return { ...baseSpec, service_name: 'GrpcService', uuid: generateUUID() }
      case 'udp':
        return { ...baseSpec, uuid: generateUUID(), header_type: 'none' }
      default:
        return baseSpec
    }
  }

  const handleCoreChange = (core: string) => {
    let newType = formData.type
    if (core === 'rathole' || core === 'chisel') {
      newType = core
    } else if (core === 'frp') {
      // Keep current type if it's tcp or udp, otherwise default to tcp
      newType = (formData.type === 'tcp' || formData.type === 'udp') ? formData.type : 'tcp'
    } else if (core === 'backhaul') {
      newType = backhaulState.transport
    } else if (core === 'udp2raw') {
      newType = udp2rawState.raw_mode
    } else if (core === 'zapret') {
      newType = zapretState.desync_mode
    } else if (formData.type === 'rathole' || formData.type === 'chisel' || formData.core === 'backhaul' || formData.core === 'udp2raw' || formData.core === 'zapret') {
      newType = 'tcp'
    }
    setFormData({ ...formData, core, type: newType })
  }

  const generateUUID = () => {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0
      const v = c === 'x' ? r : (r & 0x3) | 0x8
      return v.toString(16)
    })
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[100] overflow-auto">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-4 w-full max-w-xl my-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">{t.tunnels.createTunnel}</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Name
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
              required
            />
          </div>
          {formData.core !== 'zapret' && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t.tunnels.iranNode}
              </label>
              <select
                value={formData.iran_node_id || formData.node_id}
                onChange={(e) => setFormData({ ...formData, iran_node_id: e.target.value, node_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                required={formData.core === 'rathole' || formData.core === 'backhaul' || formData.core === 'frp' || formData.core === 'chisel' || formData.core === 'udp2raw'}
              >
                <option value="">{t.tunnels.selectIranNode}</option>
                {nodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t.tunnels.foreignServer}
              </label>
              <select
                value={formData.foreign_node_id}
                onChange={(e) => setFormData({ ...formData, foreign_node_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                required={formData.core === 'rathole' || formData.core === 'backhaul' || formData.core === 'frp' || formData.core === 'chisel' || formData.core === 'udp2raw'}
              >
                <option value="">{t.tunnels.selectForeignServer}</option>
                {servers.map((server) => (
                  <option key={server.id} value={server.id}>
                    {server.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          )}

          {formData.core === 'zapret' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t.tunnels.zapretNode}
              </label>
              <select
                value={formData.iran_node_id || formData.node_id}
                onChange={(e) => setFormData({ ...formData, iran_node_id: e.target.value, node_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                required
              >
                <option value="">{t.tunnels.selectZapretNode}</option>
                {[...nodes, ...servers].map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.name} ({node.metadata?.role || node.node_metadata?.role || 'node'})
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {t.tunnels.zapretNodeHint}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t.tunnels.core}
              </label>
              <select
                value={formData.core}
                onChange={(e) => handleCoreChange(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
              >
                <option value="gost">GOST</option>
                <option value="rathole">Rathole</option>
                <option value="backhaul">Backhaul</option>
                <option value="chisel">Chisel</option>
                <option value="frp">FRP</option>
                <option value="udp2raw">udp2raw</option>
                <option value="zapret">Zapret (DPI bypass)</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t.tunnels.type}
              </label>
              <select
                value={formData.type}
                onChange={(e) => {
                  const value = e.target.value as BackhaulTransport
                  setFormData({ ...formData, type: value })
                  if (formData.core === 'backhaul') {
                    setBackhaulState((prev) => ({ ...prev, transport: value }))
                  }
                  if (formData.core === 'udp2raw') {
                    setUdp2rawState((prev) => ({ ...prev, raw_mode: e.target.value as Udp2rawRawMode }))
                  }
                  if (formData.core === 'zapret') {
                    setZapretState((prev) => ({ ...prev, desync_mode: e.target.value }))
                  }
                }}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                disabled={formData.core === 'chisel'}
              >
                {formData.core === 'chisel' ? (
                  <option value={formData.core}>{formData.core.charAt(0).toUpperCase() + formData.core.slice(1)}</option>
                ) : formData.core === 'rathole' ? (
                  <>
                    <option value="tcp">TCP</option>
                    <option value="ws">WebSocket (WS)</option>
                  </>
                ) : formData.core === 'frp' ? (
                  <>
                    <option value="tcp">TCP</option>
                    <option value="udp">UDP</option>
                  </>
                ) : formData.core === 'backhaul' ? (
                  <>
                    <option value="tcp">TCP</option>
                    <option value="udp">UDP</option>
                    <option value="ws">WebSocket (WS)</option>
                    <option value="wsmux">WebSocket Mux</option>
                    <option value="tcpmux">TCPMux</option>
                  </>
                ) : formData.core === 'udp2raw' ? (
                  <>
                    <option value="faketcp">FakeTCP</option>
                    <option value="icmp">ICMP</option>
                    <option value="udp">UDP</option>
                  </>
                ) : formData.core === 'zapret' ? (
                  <>
                    {ZAPRET_DESYNC_MODES.map((mode) => (
                      <option key={mode} value={mode}>{mode}</option>
                    ))}
                  </>
                ) : (
                  <>
                    <option value="tcp">TCP</option>
                    <option value="udp">UDP</option>
                    <option value="grpc">gRPC</option>
                    <option value="tcpmux">TCPMux</option>
                  </>
                )}
              </select>
            </div>
          </div>

          {formData.core === 'gost' && (formData.type === 'tcp' || formData.type === 'udp' || formData.type === 'grpc' || formData.type === 'tcpmux') && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.tunnels.remoteIP}
                </label>
                <input
                  type="text"
                  value={formData.remote_ip}
                  onChange={(e) =>
                    setFormData({ ...formData, remote_ip: e.target.value || '127.0.0.1' })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="127.0.0.1 or [2001:db8::1]"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {t.tunnels.remoteIPDescription}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.tunnels.ports}
                </label>
                <input
                  type="text"
                  value={formData.ports}
                  onChange={(e) =>
                    setFormData({ ...formData, ports: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="8080,8081,8082"
                  required
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {t.tunnels.portsDescription}
                </p>
              </div>
            </div>
          )}
          
          {formData.core === 'backhaul' && (
            <BackhaulForm
              state={backhaulState}
              onChange={(partial) => {
                setBackhaulState((prev) => ({ ...prev, ...partial }))
                if (partial.transport) {
                  setFormData((prev) => ({ ...prev, type: partial.transport as string }))
                }
              }}
              onOpenAdvanced={() => setShowBackhaulAdvanced(true)}
              acceptUdpVisible={
                backhaulState.transport === 'tcp' || backhaulState.transport === 'tcpmux'
              }
            />
          )}
          
          {formData.core === 'udp2raw' && (
            <Udp2rawForm
              state={udp2rawState}
              onChange={(partial) => {
                setUdp2rawState((prev) => ({ ...prev, ...partial }))
                if (partial.raw_mode) {
                  setFormData((prev) => ({ ...prev, type: partial.raw_mode as string }))
                }
              }}
            />
          )}

          {formData.core === 'zapret' && (
            <ZapretForm
              state={zapretState}
              onChange={(partial) => {
                setZapretState((prev) => ({ ...prev, ...partial }))
                if (partial.desync_mode) {
                  setFormData((prev) => ({ ...prev, type: partial.desync_mode as string }))
                }
              }}
            />
          )}
          
          {formData.core === 'rathole' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Ports
                </label>
                <input
                  type="text"
                  value={formData.ports}
                  onChange={(e) =>
                    setFormData({ ...formData, ports: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="8080,8081,8082"
                  required
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Ports (comma-separated, same for panel and node local service)
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Rathole Port
                </label>
                <input
                  type="number"
                  value={formData.rathole_remote_addr}
                  onChange={(e) =>
                    setFormData({ ...formData, rathole_remote_addr: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="23333"
                  min="1"
                  max="65535"
                  required
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Rathole server port on panel (IP: {window.location.hostname})</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Token (Optional - Auto-generated if empty)
                </label>
                <input
                  type="text"
                  value={formData.rathole_token}
                  onChange={(e) =>
                    setFormData({ ...formData, rathole_token: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="Leave empty for auto-generation"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Authentication token (will be auto-generated if not provided)</p>
              </div>
            </div>
            </>
          )}
          
          {formData.core === 'chisel' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Ports
                </label>
                <input
                  type="text"
                  value={formData.ports}
                  onChange={(e) =>
                    setFormData({ ...formData, ports: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="8080,8081,8082"
                  required
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Ports (comma-separated, same for reverse port and local port)
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Control Port
                </label>
                <input
                  type="number"
                  value={formData.chisel_control_port}
                  onChange={(e) =>
                    setFormData({ ...formData, chisel_control_port: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder={`${(parseInt(formData.ports.split(',')[0]?.trim()) || 8080) + 10000} (auto)`}
                  min="1"
                  max="65535"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Chisel server control port (leave empty for auto: first port + 10000)
                </p>
              </div>
            </>
          )}
          
          {formData.core === 'frp' && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Bind Port
                  </label>
                  <input
                    type="number"
                    value={formData.frp_bind_port}
                    onChange={(e) =>
                      setFormData({ ...formData, frp_bind_port: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                    placeholder="7000"
                    min="1"
                    max="65535"
                    required
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    FRP server port on panel (default: 7000)
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Ports
                  </label>
                  <input
                    type="text"
                    value={formData.ports}
                    onChange={(e) =>
                      setFormData({ ...formData, ports: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                    placeholder="8080,8081,8082"
                    required
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Ports (comma-separated, same for remote port and local port)
                  </p>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Token (Optional - Auto-generated if empty)
                </label>
                <input
                  type="text"
                  value={formData.frp_token}
                  onChange={(e) =>
                    setFormData({ ...formData, frp_token: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
                  placeholder="Leave empty for auto-generation"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Authentication token (will be auto-generated if not provided)</p>
              </div>
            </>
          )}
          
          {/* v4 to v6 tunnel checkbox - only for Rathole, Backhaul, Chisel, FRP (not GOST) */}
          {formData.core !== 'gost' && (
            <>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="v4_to_v6"
                  checked={formData.use_ipv6}
                  onChange={(e) => setFormData({ ...formData, use_ipv6: e.target.checked })}
                  className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 dark:focus:ring-blue-600 dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600"
                />
                <label htmlFor="v4_to_v6" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  v4 to v6 tunnel
                </label>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">
                Enable this to create a tunnel from IPv4 (iran node) to IPv6 (node/target). Iran node listens on IPv4, target uses IPv6.
              </p>
            </>
          )}

          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              {t.tunnels.cancel}
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              {t.tunnels.createTunnel}
            </button>
          </div>
        </form>
        <BackhaulAdvancedDrawer
          open={showBackhaulAdvanced}
          state={backhaulAdvanced}
          onClose={() => setShowBackhaulAdvanced(false)}
          onChange={setBackhaulAdvanced}
        />
      </div>
    </div>
  )
}

const BACKHAUL_TRANSPORTS: BackhaulTransport[] = ['tcp', 'udp', 'ws', 'wsmux', 'tcpmux']

function BackhaulForm({
  state,
  onChange,
  onOpenAdvanced,
  acceptUdpVisible,
}: {
  state: BackhaulFormState
  onChange: (partial: Partial<BackhaulFormState>) => void
  onOpenAdvanced: () => void
  acceptUdpVisible?: boolean
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Control Port
        </label>
        <input
          type="number"
          value={state.control_port}
          onChange={(e) => onChange({ control_port: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          placeholder="3080"
          min={1}
          max={65535}
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Port where the node connects back to the panel.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Ports
        </label>
        <input
          type="text"
          value={state.public_port}
          onChange={(e) => {
            onChange({ public_port: e.target.value, target_port: e.target.value })
          }}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          placeholder="8080,8081,8082"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Ports (comma-separated, same for public port and target port)
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Token (Optional - Auto-generated if empty)
        </label>
        <input
          type="text"
          value={state.token}
          onChange={(e) => onChange({ token: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          placeholder="Leave empty for auto-generation"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Authentication token (will be auto-generated if not provided)</p>
      </div>

      {acceptUdpVisible && (
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Allow UDP over TCP
          </label>
          <input
            type="checkbox"
            checked={state.accept_udp}
            onChange={() => onChange({ accept_udp: !state.accept_udp })}
            className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
          />
        </div>
      )}

      <div className="pt-2">
        <button
          type="button"
          onClick={onOpenAdvanced}
          className="px-3 py-2 text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
        >
          Advanced settings
        </button>
      </div>
    </div>
  )
}

function Udp2rawForm({
  state,
  onChange,
}: {
  state: Udp2rawFormState
  onChange: (partial: Partial<Udp2rawFormState>) => void
}) {
  const { t } = useLanguage()
  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
        {t.tunnels.udp2rawHint}
      </p>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Listen Port
          </label>
          <input
            type="number"
            value={state.listen_port}
            onChange={(e) => onChange({ listen_port: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="4096"
            min={1}
            max={65535}
            required
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Public UDP port on the iran node (users connect here)
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Raw Port (Optional)
          </label>
          <input
            type="number"
            value={state.raw_port}
            onChange={(e) => onChange({ raw_port: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="Auto"
            min={1}
            max={65535}
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Raw faketcp/icmp/udp port on the foreign server (auto if empty)
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Target Host
          </label>
          <input
            type="text"
            value={state.target_host}
            onChange={(e) => onChange({ target_host: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="127.0.0.1"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            UDP service host on the foreign server
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Target Port (Optional)
          </label>
          <input
            type="number"
            value={state.target_port}
            onChange={(e) => onChange({ target_port: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="Same as listen port"
            min={1}
            max={65535}
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            UDP service port on the foreign server (defaults to listen port)
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Key (Optional - Auto-generated if empty)
        </label>
        <input
          type="text"
          value={state.key}
          onChange={(e) => onChange({ key: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          placeholder="Leave empty for auto-generation"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Shared password used by both sides (will be auto-generated if not provided)</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Cipher Mode
          </label>
          <select
            value={state.cipher_mode}
            onChange={(e) => onChange({ cipher_mode: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          >
            {UDP2RAW_CIPHER_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Auth Mode
          </label>
          <select
            value={state.auth_mode}
            onChange={(e) => onChange({ auth_mode: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          >
            {UDP2RAW_AUTH_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )
}

function ZapretForm({
  state,
  onChange,
}: {
  state: ZapretFormState
  onChange: (partial: Partial<ZapretFormState>) => void
}) {
  const { t } = useLanguage()
  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
        {t.tunnels.zapretHint}
      </p>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Desync Mode
          </label>
          <select
            value={state.desync_mode}
            onChange={(e) => onChange({ desync_mode: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          >
            {ZAPRET_DESYNC_MODES.map((mode) => (
              <option key={mode} value={mode}>{mode}</option>
            ))}
          </select>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            nfqws strategy (--dpi-desync). Try <code>fake</code> first.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Filter Ports (TCP)
          </label>
          <input
            type="text"
            value={state.filter_tcp}
            onChange={(e) => onChange({ filter_tcp: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="443"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Port(s) to desync, e.g. <code>443</code> or <code>443,8443</code>
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            L7 Filter
          </label>
          <select
            value={state.filter_l7}
            onChange={(e) => onChange({ filter_l7: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          >
            {ZAPRET_L7_FILTERS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Protocol layer (--filter-l7). Use <code>tls</code> for HTTPS/SNI.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Direction
          </label>
          <select
            value={state.direction}
            onChange={(e) => onChange({ direction: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          >
            {ZAPRET_DIRECTIONS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            <code>both</code> is recommended for outbound TLS servers.
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Fake TLS SNI
        </label>
        <input
          type="text"
          value={state.fake_tls_sni}
          onChange={(e) => onChange({ fake_tls_sni: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          placeholder="hcaptcha.com"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Decoy SNI sent in the fake ClientHello (--dpi-desync-fake-tls-mod=sni=). Use an allowed domain.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Fooling
          </label>
          <input
            type="text"
            value={state.desync_fooling}
            onChange={(e) => onChange({ desync_fooling: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="badseq,ts"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            --dpi-desync-fooling (e.g. <code>badseq,ts</code>, <code>md5sig</code>, <code>badsum</code>)
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            NFQUEUE Number (Optional)
          </label>
          <input
            type="number"
            value={state.queue_num}
            onChange={(e) => onChange({ queue_num: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
            placeholder="Auto"
            min={1}
            max={65535}
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Leave empty to auto-pick a unique queue per tunnel.
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Extra nfqws Args (Advanced)
        </label>
        <input
          type="text"
          value={state.extra_args}
          onChange={(e) => onChange({ extra_args: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
          placeholder="--dpi-desync-ttl=5 --dpi-desync-split-pos=2"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Optional raw flags appended to nfqws. Leave empty unless you know what you need.
        </p>
      </div>
    </div>
  )
}

function BackhaulAdvancedDrawer({
  open,
  onClose,
  state,
  onChange,
}: {
  open: boolean
  onClose: () => void
  state: BackhaulAdvancedState
  onChange: (next: BackhaulAdvancedState) => void
}) {
  if (!open) {
    return null
  }

  const updateServer = (key: keyof BackhaulAdvancedServerState, value: string | boolean) => {
    onChange({
      ...state,
      server: {
        ...state.server,
        [key]: value,
      },
    })
  }

  const updateClient = (key: keyof BackhaulAdvancedClientState, value: string | boolean) => {
    onChange({
      ...state,
      client: {
        ...state.client,
        [key]: value,
      },
    })
  }

  return (
    <div className="fixed inset-0 z-[100] flex">
      <div className="flex-1 bg-black bg-opacity-40" onClick={onClose} />
      <div className="w-full max-w-xl h-full bg-white dark:bg-gray-900 shadow-xl overflow-y-auto p-6">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Backhaul Advanced Settings</h3>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            Close
          </button>
        </div>

        <div className="space-y-6">
          <div>
            <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-3">
              Server Options
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Keepalive (s)</label>
                <input
                  type="number"
                  value={state.server.keepalive_period}
                  onChange={(e) => updateServer('keepalive_period', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Heartbeat (s)</label>
                <input
                  type="number"
                  value={state.server.heartbeat}
                  onChange={(e) => updateServer('heartbeat', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Channel Size</label>
                <input
                  type="number"
                  value={state.server.channel_size}
                  onChange={(e) => updateServer('channel_size', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Mux Concurrency</label>
                <input
                  type="number"
                  value={state.server.mux_con}
                  onChange={(e) => updateServer('mux_con', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Log Level</label>
                <select
                  value={state.server.log_level}
                  onChange={(e) => updateServer('log_level', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                >
                  <option value="panic">panic</option>
                  <option value="fatal">fatal</option>
                  <option value="error">error</option>
                  <option value="warn">warn</option>
                  <option value="info">info</option>
                  <option value="debug">debug</option>
                  <option value="trace">trace</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Web UI Port</label>
                <input
                  type="number"
                  value={state.server.web_port}
                  onChange={(e) => updateServer('web_port', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  placeholder="0 (disable)"
                  min={0}
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">Enable Sniffer</label>
                <input
                  type="checkbox"
                  checked={state.server.sniffer}
                  onChange={() => updateServer('sniffer', !state.server.sniffer)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Sniffer Log Path</label>
                <input
                  type="text"
                  value={state.server.sniffer_log}
                  onChange={(e) => updateServer('sniffer_log', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  placeholder="/var/log/backhaul.json"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">TLS Certificate Path</label>
                <input
                  type="text"
                  value={state.server.tls_cert}
                  onChange={(e) => updateServer('tls_cert', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">TLS Key Path</label>
                <input
                  type="text"
                  value={state.server.tls_key}
                  onChange={(e) => updateServer('tls_key', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">Disable Optimizations</label>
                <input
                  type="checkbox"
                  checked={state.server.skip_optz}
                  onChange={() => updateServer('skip_optz', !state.server.skip_optz)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">Enable Proxy Protocol</label>
                <input
                  type="checkbox"
                  checked={state.server.proxy_protocol}
                  onChange={() => updateServer('proxy_protocol', !state.server.proxy_protocol)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">TCP Nodelay</label>
                <input
                  type="checkbox"
                  checked={state.server.nodelay}
                  onChange={() => updateServer('nodelay', !state.server.nodelay)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>

          <div>
            <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-3">
              Client Options
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Connection Pool</label>
                <input
                  type="number"
                  value={state.client.connection_pool}
                  onChange={(e) => updateClient('connection_pool', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Retry Interval (s)</label>
                <input
                  type="number"
                  value={state.client.retry_interval}
                  onChange={(e) => updateClient('retry_interval', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Dial Timeout (s)</label>
                <input
                  type="number"
                  value={state.client.dial_timeout}
                  onChange={(e) => updateClient('dial_timeout', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Keepalive (s)</label>
                <input
                  type="number"
                  value={state.client.keepalive_period}
                  onChange={(e) => updateClient('keepalive_period', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Log Level</label>
                <select
                  value={state.client.log_level}
                  onChange={(e) => updateClient('log_level', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                >
                  <option value="panic">panic</option>
                  <option value="fatal">fatal</option>
                  <option value="error">error</option>
                  <option value="warn">warn</option>
                  <option value="info">info</option>
                  <option value="debug">debug</option>
                  <option value="trace">trace</option>
                </select>
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Edge IP (for WS/WSS)</label>
                <input
                  type="text"
                  value={state.client.edge_ip}
                  onChange={(e) => updateClient('edge_ip', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
                  placeholder="Optional CDN edge IP"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">Aggressive Pool</label>
                <input
                  type="checkbox"
                  checked={state.client.aggressive_pool}
                  onChange={() => updateClient('aggressive_pool', !state.client.aggressive_pool)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">TCP Nodelay</label>
                <input
                  type="checkbox"
                  checked={state.client.nodelay}
                  onChange={() => updateClient('nodelay', !state.client.nodelay)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">Disable Optimizations</label>
                <input
                  type="checkbox"
                  checked={state.client.skip_optz}
                  onChange={() => updateClient('skip_optz', !state.client.skip_optz)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300 dark:border-gray-600 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>

          <div>
            <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-3">
              Custom Ports
            </h4>
            <textarea
              value={state.customPorts}
              onChange={(e) => onChange({ ...state, customPorts: e.target.value })}
              className="w-full min-h-[120px] px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-800 dark:text-white"
              placeholder={`One entry per line. Examples:\n443\n443=127.0.0.1:8080\n443=[2001:db8::1]:8080\n2000-2100=127.0.0.1:22`}
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Format matches Backhaul ports syntax. Leave empty to use the single public port above.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function buildBackhaulSpec(
  base: BackhaulFormState,
  advanced: BackhaulAdvancedState,
  transportOverride?: BackhaulTransport,
): Record<string, any> {
  const transport = transportOverride ?? base.transport
  const controlPort = parseInt(base.control_port, 10)
  const publicPort = parseInt(base.public_port, 10)
  const targetPort = parseInt(base.target_port, 10)
  const listenIp = base.listen_ip.trim() || '0.0.0.0'
  const targetHost = base.target_host.trim() || '127.0.0.1'
  const token = base.token.trim()
  const panelHost = base.public_host.trim() || (typeof window !== 'undefined' ? window.location.hostname : '') || '127.0.0.1'

  const effectiveControlPort = !Number.isNaN(controlPort) && controlPort > 0
    ? controlPort
    : (!Number.isNaN(publicPort) && publicPort > 0
        ? publicPort
        : (!Number.isNaN(targetPort) && targetPort > 0 ? targetPort : 3080))
  
  // Parse comma-separated ports from public_port
  const parsePortsFromString = (portStr: string): number[] => {
    if (!portStr || typeof portStr !== 'string') {
      console.warn('parsePortsFromString: invalid input:', portStr, 'type:', typeof portStr)
      return []
    }
    const parsed = portStr
      .split(',')
      .map(p => p.trim())
      .filter(p => p)
      .map(p => parseInt(p, 10))
      .filter(p => !isNaN(p) && p > 0 && p <= 65535)
    console.log('parsePortsFromString: input:', portStr, '-> parsed:', parsed, 'count:', parsed.length)
    return parsed
  }
  
  // CRITICAL: Ensure base.public_port is a string before parsing
  const publicPortStr = String(base.public_port || '')
  console.log('buildBackhaulSpec: base.public_port (raw):', base.public_port, 'type:', typeof base.public_port, '-> string:', publicPortStr)
  const publicPorts = parsePortsFromString(publicPortStr)
  console.log('buildBackhaulSpec: parsed publicPorts:', publicPorts, 'count:', publicPorts.length)
  const effectivePublicPort = publicPorts.length > 0 ? publicPorts[0] : (!Number.isNaN(publicPort) && publicPort > 0 ? publicPort : effectiveControlPort)
  const effectiveTargetPort = publicPorts.length > 0 ? publicPorts[0] : (!Number.isNaN(targetPort) && targetPort > 0 ? targetPort : effectivePublicPort)

  const remoteAddr = base.remote_addr.trim() || `${panelHost}:${effectiveControlPort}`
  const listenedPort = listenIp !== '0.0.0.0' ? `${listenIp}:${effectivePublicPort}` : `${effectivePublicPort}`
  const defaultPortEntry = `${listenedPort}=${targetHost}:${effectiveTargetPort}`

  // Use customPorts if provided, otherwise build from comma-separated public_port
  let ports: string[] = []
  
  // CRITICAL: Check if customPorts is set AND has content
  // If customPorts is empty or just whitespace, use publicPorts instead
  const hasCustomPorts = advanced.customPorts && advanced.customPorts.trim().length > 0
  
  if (hasCustomPorts) {
    // User manually entered ports in CUSTOM PORTS field
    ports = advanced.customPorts
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
    console.log('buildBackhaulSpec: Using customPorts, count:', ports.length, 'ports:', ports)
  } else if (publicPorts.length > 0) {
    // Build ports array from comma-separated public_port (e.g., "8080,8081,8082")
    // This is the automatic conversion from Ports field to Backhaul format
    ports = publicPorts.map(p => {
      const listenedPort = listenIp !== '0.0.0.0' ? `${listenIp}:${p}` : `${p}`
      return `${listenedPort}=${targetHost}:${p}`
    })
    console.log('buildBackhaulSpec: Built ports from publicPorts:', publicPorts, '-> ports:', ports, 'count:', ports.length)
  }
  
  if (ports.length === 0) {
    ports.push(defaultPortEntry)
    console.log('buildBackhaulSpec: No ports found, using default:', defaultPortEntry)
  }
  
  // Final verification - ensure we have ports
  console.log('buildBackhaulSpec: Final ports array:', ports, 'count:', ports.length)

  const serverOptions: Record<string, any> = {}
  Object.entries(advanced.server).forEach(([key, value]) => {
    if (booleanServerKeys.has(key)) {
      if (value) {
        serverOptions[key] = true
      }
      return
    }
    if (numericServerKeys.has(key)) {
      const num = Number(value)
      if (!Number.isNaN(num) && value !== '') {
        serverOptions[key] = num
      }
      return
    }
    if (stringServerKeys.has(key)) {
      const val = typeof value === 'string' ? value.trim() : value
      if (val) {
        serverOptions[key] = val
      }
    }
  })

  const clientOptions: Record<string, any> = {}
  Object.entries(advanced.client).forEach(([key, value]) => {
    if (booleanClientKeys.has(key)) {
      if (value) {
        clientOptions[key] = true
      }
      return
    }
    if (numericClientKeys.has(key)) {
      const num = Number(value)
      if (!Number.isNaN(num) && value !== '') {
        clientOptions[key] = num
      }
      return
    }
    if (stringClientKeys.has(key)) {
      const val = typeof value === 'string' ? value.trim() : value
      if (val) {
        clientOptions[key] = val
      }
    }
  })

  const spec: Record<string, any> = {
    transport,
    bind_addr: `0.0.0.0:${effectiveControlPort}`,
    remote_addr: remoteAddr,
    listen_ip: listenIp,
    control_port: effectiveControlPort,
    public_port: effectivePublicPort,
    listen_port: effectivePublicPort,
    target_host: targetHost,
    target_port: effectiveTargetPort,
    target_addr: `${targetHost}:${effectiveTargetPort}`,
    public_host: panelHost,
    ports,
  }

  if (token) {
    spec.token = token
  }
  if (base.accept_udp && (transport === 'tcp' || transport === 'tcpmux')) {
    spec.accept_udp = true
  }
  if (Object.keys(serverOptions).length > 0) {
    spec.server_options = serverOptions
  }
  if (Object.keys(clientOptions).length > 0) {
    spec.client_options = clientOptions
  }

  return spec
}

function parseBackhaulSpec(spec: Record<string, any>, currentType: string): {
  state: BackhaulFormState
  advanced: BackhaulAdvancedState
} {
  const state = createDefaultBackhaulState()
  const advanced = createDefaultBackhaulAdvancedState()

  if (BACKHAUL_TRANSPORTS.includes(currentType as BackhaulTransport)) {
    state.transport = currentType as BackhaulTransport
  }

  if (!spec) {
    return { state, advanced }
  }

  const controlPortCandidate =
    spec.control_port ??
    extractPort(spec.bind_addr) ??
    extractPort(spec.remote_addr)
  if (controlPortCandidate) {
    state.control_port = String(controlPortCandidate)
  }

  state.listen_ip = spec.listen_ip ?? state.listen_ip

  const publicPortCandidate =
    spec.public_port ??
    spec.listen_port ??
    derivePortFromPorts(spec.ports)
  if (publicPortCandidate) {
    state.public_port = String(publicPortCandidate)
  }

  if (spec.target_host) {
    state.target_host = String(spec.target_host)
  } else if (typeof spec.target_addr === 'string') {
    const parsed = parseAddressPort(spec.target_addr)
    state.target_host = parsed.host
  }

  const targetPortCandidate =
    spec.target_port ??
    (typeof spec.target_addr === 'string'
      ? parseAddressPort(spec.target_addr).port
      : undefined)
  if (targetPortCandidate) {
    state.target_port = String(targetPortCandidate)
  }

  state.token = spec.token ?? ''
  state.public_host = spec.public_host ?? ''
  state.remote_addr = spec.remote_addr ?? ''
  state.accept_udp = Boolean(spec.accept_udp)

  if (Array.isArray(spec.ports) && spec.ports.length > 0) {
    advanced.customPorts = spec.ports.join('\n')
  }

  const serverOptions = spec.server_options || {}
  Object.entries(advanced.server).forEach(([key, defaultValue]) => {
    const value = serverOptions[key]
    if (value === undefined || value === null) {
      return
    }
    if (typeof defaultValue === 'boolean') {
      advanced.server[key as keyof BackhaulAdvancedServerState] = Boolean(value)
    } else {
      advanced.server[key as keyof BackhaulAdvancedServerState] = String(value)
    }
  })

  const clientOptions = spec.client_options || {}
  Object.entries(advanced.client).forEach(([key, defaultValue]) => {
    const value = clientOptions[key]
    if (value === undefined || value === null) {
      return
    }
    if (typeof defaultValue === 'boolean') {
      advanced.client[key as keyof BackhaulAdvancedClientState] = Boolean(value)
    } else {
      advanced.client[key as keyof BackhaulAdvancedClientState] = String(value)
    }
  })

  return { state, advanced }
}

function extractPort(value: unknown): string | undefined {
  if (typeof value === 'number') {
    return value.toString()
  }
  if (typeof value === 'string') {
    const parts = value.split(':')
    const port = parts[parts.length - 1]
    if (port && !Number.isNaN(Number(port))) {
      return port
    }
  }
  return undefined
}

function derivePortFromPorts(value: unknown): string | undefined {
  if (!Array.isArray(value) || value.length === 0) {
    return undefined
  }
  const first = value[0]
  if (typeof first !== 'string') {
    return undefined
  }
  const [left] = first.split('=')
  if (!left) {
    return undefined
  }
  const segments = left.split(':')
  const port = segments[segments.length - 1]
  return port && !Number.isNaN(Number(port)) ? port : undefined
}

export default Tunnels
