import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

type Language = 'en' | 'fa'

interface Translations {
  login: {
    title: string
    subtitle: string
    username: string
    password: string
    usernamePlaceholder: string
    passwordPlaceholder: string
    signIn: string
    signingIn: string
    loginFailed: string
    checkCredentials: string
  }
  dashboard: {
    title: string
    subtitle: string
    totalNodes: string
    totalTunnels: string
    cpuUsage: string
    memoryUsage: string
    currentUsage: string
    active: string
    systemResources: string
    quickActions: string
    createNewTunnel: string
    addNode: string
    addServer: string
    loadingDashboard: string
  }
  navigation: {
    dashboard: string
    nodes: string
    servers: string
    installNode: string
    tunnels: string
    coreHealth: string
    logs: string
    settings: string
    logout: string
    light: string
    dark: string
  }
  nodes: {
    title: string
    subtitle: string
    addNode: string
    viewCACertificate: string
    downloadCA: string
    revokedTitle: string
    revokedDesc: string
    allowAgain: string
  }
  servers: {
    title: string
    subtitle: string
    viewCACertificate: string
    downloadCA: string
  }
  installNode: {
    title: string
    subtitle: string
    serverSection: string
    sshHost: string
    sshPort: string
    sshUsername: string
    sshPassword: string
    role: string
    roleIran: string
    roleForeign: string
    systemUpgrade: string
    systemUpgradeDesc: string
    nodeName: string
    panelSection: string
    panelHost: string
    panelHostHint: string
    panelApiPort: string
    componentsSection: string
    installSmiteNode: string
    installSmiteNodeDesc: string
    installXui: string
    installXuiDesc: string
    installWireguard: string
    installWireguardDesc: string
    wireguardForeignOnly: string
    xuiPort: string
    xuiUsername: string
    xuiPassword: string
    randomIfEmpty: string
    artifactsSection: string
    artifactsHint: string
    bundleArtifact: string
    xuiArtifact: string
    uploadBundle: string
    uploadXui: string
    uploading: string
    noArtifact: string
    requiredForIran: string
    startInstall: string
    installing: string
    selectComponent: string
    liveLog: string
    resultsSection: string
    statusPending: string
    statusRunning: string
    statusSuccess: string
    statusError: string
    nodeResult: string
    xuiResult: string
    wireguardResult: string
    copy: string
    copied: string
    fieldHost: string
    fieldMethod: string
    fieldNote: string
    fieldError: string
    panelUrl: string
    username: string
    password: string
    port: string
    webBasePath: string
    apiToken: string
    wgPort: string
    serverPublicKey: string
    serverEndpoint: string
    apiBaseUrl: string
    apiEndpoints: string
    apiKey: string
    apiKeyNote: string
    clientConfig: string
    checkNodesPage: string
    nodeRegistered: string
    nodeWaitingRegistration: string
    startFailed: string
    uploadFailed: string
    deleteFailed: string
  }
  health: {
    title: string
    subtitle: string
    allHealthy: string
    runCheck: string
    checking: string
    autoHeal: string
    autoHealHint: string
    fixNow: string
    resolve: string
    occurrences: string
    openProblems: string
    lastChecked: string
    healDone: string
    healFailed: string
  }
  tunnels: {
    title: string
    subtitle: string
    createTunnel: string
    name: string
    foreignServer: string
    iranNode: string
    type: string
    core: string
    ports: string
    portsDescription: string
    ratholeTransport?: string
    wgStealthLabel?: string
    wgStealthHint?: string
    fakeSni?: string
    fakeSniHint?: string
    remoteIP: string
    remoteIPDescription: string
    selectForeignServer: string
    selectIranNode: string
    cancel: string
    loadingTunnels: string
    reapplyAll: string
    confirmReapplyAll: string
    autoRestartTitle: string
    autoRestartOff: string
    restartService: string
    confirmRestart: string
    restartFailed: string
    healthLabel: string
    healthStates: Record<string, string>
    reapplyAllSuccess: string
    udp2rawHint: string
    trusttunnelHint: string
    zapretHint: string
    zapretNode: string
    selectZapretNode: string
    zapretNodeHint: string
    zapretTargetIp: string
    zapretTargetIpHint: string
    snispoofHint: string
    snispoofClientHint: string
    snispoofClientOutboundTitle: string
    snispoofClientOutboundHint: string
    snispoofCopyLink: string
    snispoofCopied: string
    snispoofTestSection: string
    snispoofTestHint: string
    snispoofTestNow: string
    snispoofTesting: string
    snispoofAutotune: string
    snispoofTuning: string
    snispoofTuningWait: string
    snispoofTestOk: string
    snispoofTestFail: string
    snispoofBestApplied: string
    snispoofNoneWorked: string
    snispoofDesyncOptional: string
    snispoofColMode: string
    snispoofColFooling: string
    snispoofColResult: string
    snispoofColLatency: string
    snispoofLocalPort: string
    snispoofLocalPortHint: string
    snispoofInboundUuid: string
    snispoofInboundUuidHint: string
    snispoofRegenerate: string
    snispoofFrontAddress: string
    snispoofFrontAddressHint: string
    snispoofFrontPort: string
    snispoofUuid: string
    snispoofUuidHint: string
    snispoofSni: string
    snispoofSniHint: string
    snispoofWsPath: string
    snispoofAlpn: string
    snispoofFingerprint: string
    snispoofPasteVless: string
    snispoofApplyVless: string
    snispoofDesyncSection: string
    hysteria2Hint: string
    hysteria2Ports: string
    hysteria2PortsHint: string
    hysteria2ControlPort: string
    hysteria2ControlPortHint: string
    hysteria2TargetHost: string
    hysteria2TargetHostHint: string
    hysteria2TargetPort: string
    hysteria2TargetPortHint: string
    hysteria2TargetPortPlaceholder: string
    hysteria2Sni: string
    hysteria2SniHint: string
    hysteria2Obfs: string
    hysteria2ObfsHint: string
    hysteria2ManualTitle: string
    hysteria2ManualBody: string
    hysteria2Autotune: string
    hysteria2Tuning: string
    hysteria2AutotuneHint: string
    hysteria2BestObfs: string
    hysteria2Applied: string
    hysteria2NoWorking: string
    tuicHint: string
    tuicUdpRelayMode: string
    tuicUdpRelayModeHint: string
    warpHint: string
    warpNode: string
    warpNodeHint: string
    warpSelectNode: string
    warpListenAddr: string
    warpListenAddrHint: string
    warpListenPort: string
    warpListenPortHint: string
    warpSni: string
    warpSniHint: string
    warpUsername: string
    warpPassword: string
    warpOptional: string
    warpAuthHint: string
    warpProxyTitle: string
    warpCopy: string
    warpCopied: string
    warpManualTitle: string
    warpManualBody: string
    warpTestNow: string
    warpTesting: string
    warpTestHint: string
    warpTestFail: string
    obfs4Hint: string
    obfs4Ports: string
    obfs4PortsHint: string
    obfs4ControlPort: string
    obfs4ControlPortHint: string
    obfs4TargetHost: string
    obfs4TargetHostHint: string
    obfs4TargetPort: string
    obfs4TargetPortHint: string
    obfs4TargetPortPlaceholder: string
    obfs4IatMode: string
    obfs4IatModeHint: string
    obfs4IatOff: string
    obfs4IatEnabled: string
    obfs4IatParanoid: string
    obfs4ManualBody: string
    coreChangeHint: string
    bulkSelectedCount: string
    bulkApply: string
    bulkChange: string
    bulkDelete: string
    bulkConfirmDelete: string
    bulkResultsTitle: string
    bulkNewCore: string
    bulkNewType: string
    bulkKeepType: string
    bulkRun: string
    bulkRunning: string
    benchmarkButton: string
    benchmarkTitle: string
    benchmarkHint: string
    benchmarkRun: string
    benchmarkRunning: string
    benchmarkLatency: string
    benchmarkThroughput: string
    benchmarkLoss: string
    benchmarkFailed: string
    benchmarkUseConfig: string
    benchmarkCoreMode: string
    benchmarkScore: string
  }
  coreHealth: {
    title: string
    subtitle: string
  }
  logs: {
    title: string
    subtitle: string
  }
  settings: {
    title: string
    frpCommunication: string
    frpDescription: string
    enableFrp: string
    frpPort: string
    frpPortDescription: string
    frpToken: string
    frpTokenOptional: string
    frpTokenDescription: string
    telegramBot: string
    telegramDescription: string
    enableTelegram: string
    botToken: string
    botTokenDescription: string
    adminUserIds: string
    adminUserIdsDescription: string
    addAdminId: string
    remove: string
    automaticBackup: string
    enableBackup: string
    backupInterval: string
    intervalUnit: string
    minutes: string
    hours: string
    backupDescription: string
    saveSettings: string
    saving: string
    loadingSettings: string
    settingsSaved: string
    failedToLoad: string
    failedToSave: string
    enterAdminId: string
    tunnelAutoReapply: string
    enableTunnelAutoReapply: string
    tunnelAutoReapplyDescription: string
    tunnelReapplyInterval: string
    panelUpdate: string
    panelUpdateDescription: string
    currentVersion: string
    loadReleases: string
    loadingReleases: string
    selectRelease: string
    noReleases: string
    startUpdate: string
    updateConfirm: string
    updateInProgress: string
    updateDone: string
    updateFailedTitle: string
    updateRelayNode: string
    updateDirectSource: string
    accountSecurity: string
    accountSecurityDesc: string
    currentPasswordLabel: string
    currentPasswordHint: string
    newPasswordLabel: string
    confirmPasswordLabel: string
    changePasswordBtn: string
    newUsernameLabel: string
    changeUsernameBtn: string
    passwordChanged: string
    usernameChanged: string
    passwordMismatch: string
    fillAllFields: string
    panelPortTitle: string
    panelPortDesc: string
    panelPortLabel: string
    panelPortWarning: string
    applyPort: string
    panelPortDockerNote: string
    panelPortInvalid: string
    panelPortConfirm: string
    panelPortSaved: string
    updatePanelRow: string
    updateTargets: string
    updateNoTargets: string
    updateRefresh: string
    statusPending: string
    statusUploading: string
    statusApplying: string
    statusWaiting: string
    statusUpdated: string
    statusFailed: string
    statusSkipped: string
  }
  common: {
    loading: string
  }
}

const translations: Record<Language, Translations> = {
  en: {
    login: {
      title: 'Loki',
      subtitle: 'Tunnel Management Platform',
      username: 'Username',
      password: 'Password',
      usernamePlaceholder: 'Enter your username',
      passwordPlaceholder: 'Enter your password',
      signIn: 'Sign In',
      signingIn: 'Signing in...',
      loginFailed: 'Login failed. Please check your credentials.',
      checkCredentials: 'Login failed. Please check your credentials.',
    },
    dashboard: {
      title: 'Dashboard',
      subtitle: 'Overview of your system status and resources',
      totalNodes: 'Total Nodes',
      totalTunnels: 'Total Tunnels',
      cpuUsage: 'CPU Usage',
      memoryUsage: 'Memory Usage',
      currentUsage: 'Current usage',
      active: 'active',
      systemResources: 'System Resources',
      quickActions: 'Quick Actions',
      createNewTunnel: 'Create New Tunnel',
      addNode: 'Add Iran Server',
      addServer: 'Add Foreign Server',
      loadingDashboard: 'Loading dashboard...',
    },
    navigation: {
      dashboard: 'Dashboard',
      nodes: 'Iran Nodes',
      servers: 'Foreign Nodes',
      installNode: 'Install Node',
      tunnels: 'Tunnels',
      coreHealth: 'Core Health',
      logs: 'Logs',
      settings: 'Settings',
      logout: 'Logout',
      light: 'Light',
      dark: 'Dark',
    },
    nodes: {
      title: 'Iran Nodes',
      subtitle: 'Manage your iran nodes',
      addNode: 'Add Iran Server',
      viewCACertificate: 'View CA Certificate',
      downloadCA: 'Download CA',
      revokedTitle: 'Blocked (deleted) nodes',
      revokedDesc: 'These servers were deleted and are blocked from auto-registering again. Allow one to let its agent re-enroll (within ~60s).',
      allowAgain: 'Allow again',
    },
    servers: {
      title: 'Foreign Nodes',
      subtitle: 'Manage your Foreign servers',
      viewCACertificate: 'View CA Certificate',
      downloadCA: 'Download CA',
    },
    installNode: {
      title: 'Install Node',
      subtitle: 'Install Loki node, 3x-ui panel or WireGuard on a remote server over SSH',
      serverSection: 'Target Server (SSH)',
      sshHost: 'Server IP / Host',
      sshPort: 'SSH Port',
      sshUsername: 'SSH Username',
      sshPassword: 'SSH Password',
      role: 'Server Role',
      roleIran: 'Iran Server',
      roleForeign: 'Foreign Server',
      systemUpgrade: 'Update & upgrade the server first',
      systemUpgradeDesc: 'Runs apt-get update and upgrade and installs prerequisites (python3, venv, curl) before installing. Recommended; adds a few minutes.',
      nodeName: 'Node Name',
      panelSection: 'Panel Address (given to the node)',
      panelHost: 'Panel Host / IP',
      panelHostHint: 'The address the node will use to reach this panel',
      panelApiPort: 'Panel API Port',
      componentsSection: 'Components to Install',
      installSmiteNode: 'Install Loki Node',
      installSmiteNodeDesc: 'Installs the node and registers it in the panel automatically (Iran under Nodes, Foreign under Servers)',
      installXui: 'Install 3x-ui Panel (v2.9.4)',
      installXuiDesc: 'Installs the Sanaei panel automatically and returns the login credentials',
      installWireguard: 'Install WireGuard (wginstaller)',
      installWireguardDesc: 'Installs WireGuard + wvpn management API (port 4000) and returns all details',
      wireguardForeignOnly: 'WireGuard is only available for foreign servers',
      xuiPort: '3x-ui Port',
      xuiUsername: '3x-ui Username',
      xuiPassword: '3x-ui Password',
      randomIfEmpty: 'Random if empty',
      artifactsSection: 'Artifacts (required for Iran servers)',
      artifactsHint: 'The panel has no internet access, so for Iran servers upload these files once: the Loki offline bundle (smite-offline-<arch>-<os>-py<XY>.tar.gz) and the 3x-ui release tarball (x-ui-linux-<arch>.tar.gz). Upload the bundle that matches the server Python (py310 for Ubuntu 22.04, py311 for Debian 12, py312 for Ubuntu 24.04) — its wheels are built per Python version. You can upload several bundles; the panel picks the matching one automatically. Foreign servers download directly from GitHub.',
      bundleArtifact: 'Loki Offline Bundle',
      xuiArtifact: '3x-ui Release Tarball',
      uploadBundle: 'Upload Bundle',
      uploadXui: 'Upload 3x-ui Tarball',
      uploading: 'Uploading...',
      noArtifact: 'No file uploaded',
      requiredForIran: 'Required for Iran servers',
      startInstall: 'Start Installation',
      installing: 'Installing...',
      selectComponent: 'Select at least one component to install',
      liveLog: 'Live Installation Log',
      resultsSection: 'Installation Results',
      statusPending: 'Pending',
      statusRunning: 'Running',
      statusSuccess: 'Success',
      statusError: 'Failed',
      nodeResult: 'Loki Node',
      xuiResult: '3x-ui Panel',
      wireguardResult: 'WireGuard',
      copy: 'Copy',
      copied: 'Copied!',
      fieldHost: 'Host',
      fieldMethod: 'Install Method',
      fieldNote: 'Note',
      fieldError: 'Error',
      panelUrl: 'Panel URL',
      username: 'Username',
      password: 'Password',
      port: 'Port',
      webBasePath: 'Web Base Path',
      apiToken: 'API Token',
      wgPort: 'WireGuard Port (UDP)',
      serverPublicKey: 'Server Public Key',
      serverEndpoint: 'Server Endpoint',
      apiBaseUrl: 'Management API URL',
      apiEndpoints: 'API Endpoints',
      apiKey: 'API Key',
      apiKeyNote: 'API Key',
      clientConfig: 'Default Client Config',
      checkNodesPage: 'The node registers itself with the panel shortly after install — check the Nodes/Servers page',
      nodeRegistered: 'Node registered in the panel',
      nodeWaitingRegistration: 'Waiting for the node to register in the panel...',
      startFailed: 'Failed to start installation',
      uploadFailed: 'Upload failed',
      deleteFailed: 'Delete failed',
    },
    health: {
      title: 'Health & Self-Healing',
      subtitle: 'Automatic detection and repair of tunnel problems',
      allHealthy: 'All tunnels healthy. No problems detected.',
      runCheck: 'Run check now',
      checking: 'Checking...',
      autoHeal: 'Automatic self-healing',
      autoHealHint: 'Detects disconnected/conflicting tunnels and fixes them automatically.',
      fixNow: 'Fix now',
      resolve: 'Resolve',
      occurrences: 'times',
      openProblems: 'Open problems',
      lastChecked: 'Last checked',
      healDone: 'Repair triggered',
      healFailed: 'Repair failed (check node connectivity)',
    },
    tunnels: {
      title: 'Tunnels',
      subtitle: 'Manage your tunnel connections',
      createTunnel: 'Create Tunnel',
      name: 'Name',
      foreignServer: 'Foreign Server',
      iranNode: 'Iran Node',
      type: 'Type',
      core: 'Core',
      ports: 'Ports',
      portsDescription: 'Ports (comma-separated, same for panel and target server)',
      ratholeTransport: 'Transport',
      wgStealthLabel: 'WireGuard Stealth (TLS + fake SNI)',
      wgStealthHint: 'Reverse TLS tunnel on the Iran node, disguised as HTTPS. Carries WireGuard UDP. Use port 8581.',
      fakeSni: 'Fake SNI (camouflage domain)',
      fakeSniHint: 'The TLS handshake presents this name, so the firewall sees normal traffic to that site.',
      remoteIP: 'Remote IP',
      remoteIPDescription: 'Target server IP address (IPv4 or IPv6)',
      selectForeignServer: 'Select a foreign server',
      selectIranNode: 'Select an Iran node',
      cancel: 'Cancel',
      loadingTunnels: 'Loading tunnels...',
      reapplyAll: 'Reapply All',
      confirmReapplyAll: 'Are you sure you want to reapply all tunnels?',
      autoRestartTitle: 'Auto-restart this tunnel on a schedule',
      autoRestartOff: 'Off',
      restartService: 'Restart service (full stop + start)',
      confirmRestart: 'Restart this tunnel? It fully stops and starts the service on both nodes (a few seconds of downtime).',
      restartFailed: 'Failed to restart the tunnel (check node connectivity).',
      healthLabel: 'Live',
      healthStates: {
        healthy: 'Connected',
        connecting: 'Connecting',
        degraded: 'Degraded',
        disconnected: 'Disconnected',
        conflict: 'Conflict',
        node_offline: 'Node offline',
        stopped: 'Stopped',
        unknown: 'Unknown',
      },
      reapplyAllSuccess: 'Success',
      udp2rawHint: 'udp2raw wraps UDP traffic in raw FakeTCP / ICMP / UDP packets between the Iran node (entry) and the foreign server (exit).',
      trusttunnelHint: 'TrustTunnel (rstun) is a QUIC-based reverse tunnel. The Iran node runs the server (public entry ports) and the foreign server dials in over QUIC/UDP and forwards traffic to its local service.',
      zapretHint: 'zapret runs nfqws on a single node to desync DPI (SNI spoofing) so TLS on :443 is not blocked. Run it on the server that opens the outbound TLS connection (e.g. an Xray VLESS host doing domain-fronting). It does NOT tunnel traffic between nodes.',
      coreChangeHint: 'Core change: exposed ports ({ports}) are preserved. Internal settings (tokens, control ports) are regenerated for the new core.',
      bulkSelectedCount: 'selected',
      bulkApply: 'Apply selected',
      bulkChange: 'Change core/type',
      bulkDelete: 'Delete selected',
      bulkConfirmDelete: 'Delete the selected tunnels?',
      bulkResultsTitle: 'Bulk operation results',
      bulkNewCore: 'New core',
      bulkNewType: 'New type',
      bulkKeepType: 'Keep current / default',
      bulkRun: 'Apply change',
      bulkRunning: 'Working...',
      benchmarkButton: 'Test between nodes',
      benchmarkTitle: 'Tunnel quality test between nodes',
      benchmarkHint: 'Tests every tunnel core and mode between the selected Iran and foreign node, then ranks them by quality. This runs real tunnels sequentially on dedicated test ports and can take several minutes.',
      benchmarkRun: 'Run test',
      benchmarkRunning: 'Testing...',
      benchmarkLatency: 'Latency',
      benchmarkThroughput: 'Throughput',
      benchmarkLoss: 'Loss',
      benchmarkFailed: 'Failed',
      benchmarkUseConfig: 'Use this config',
      benchmarkCoreMode: 'Core / Mode',
      benchmarkScore: 'Score',
      zapretNode: 'Node',
      selectZapretNode: 'Select a node',
      zapretNodeHint: 'The single server where nfqws + NFQUEUE rules will run (usually the foreign / proxy server).',
      zapretTargetIp: 'Target IP (Optional)',
      zapretTargetIpHint: 'Scope the desync to one destination IP only (e.g. the CDN / front IP). Leave empty to desync all traffic on the filter ports.',
      snispoofHint: 'SNI Spoof runs an Xray front proxy on this node: a local VLESS inbound (127.0.0.1:port) whose outbound goes to a front IP/domain over WS+TLS, while zapret/nfqws replaces the SNI seen by DPI with a decoy domain. Point your panel (e.g. Sanaei) outbound at the local port.',
      snispoofClientHint: 'In your proxy panel, create a VLESS TCP outbound to 127.0.0.1:{port} with UUID {uuid} (security: none).',
      snispoofClientOutboundTitle: 'Client outbound (paste into Sanaei/your panel)',
      snispoofClientOutboundHint: 'Plain VLESS over TCP, no TLS, no WebSocket, no SNI/Host. Use the inbound UUID below — NOT the backend UUID.',
      snispoofCopyLink: 'Copy link',
      snispoofCopied: 'Copied!',
      snispoofTestSection: 'Connection test & auto-tune',
      snispoofTestHint: 'Test the chain as a client would, or auto-tune to find the best desync settings.',
      snispoofTestNow: 'Test now',
      snispoofTesting: 'Testing…',
      snispoofAutotune: 'Auto-tune',
      snispoofTuning: 'Tuning…',
      snispoofTuningWait: 'Trying every desync method through the live tunnel — this can take 1–3 minutes.',
      snispoofTestOk: 'Connected — the chain works ({ms} ms).',
      snispoofTestFail: 'Not connected: {err}',
      snispoofBestApplied: 'Best applied: {mode} / {fooling} ({ms} ms). Saved to this tunnel.',
      snispoofNoneWorked: 'No desync method passed. Check the front IP / backend, then try again.',
      snispoofDesyncOptional: 'It connects even without desync — your front IP is not SNI-filtered, so zapret is optional here. Desync was kept as-is.',
      snispoofColMode: 'Mode',
      snispoofColFooling: 'Fooling',
      snispoofColResult: 'Result',
      snispoofColLatency: 'Latency',
      snispoofLocalPort: 'Local Port',
      snispoofLocalPortHint: 'The local VLESS inbound port your proxy panel connects to (127.0.0.1).',
      snispoofInboundUuid: 'Inbound UUID',
      snispoofInboundUuidHint: 'UUID your proxy panel uses to connect to the local inbound. Auto-generated.',
      snispoofRegenerate: 'Regenerate',
      snispoofFrontAddress: 'Front IP / Address',
      snispoofFrontAddressHint: 'The CDN edge IP (e.g. 104.19.229.21) or domain the outbound connects to.',
      snispoofFrontPort: 'Front Port',
      snispoofUuid: 'Backend UUID',
      snispoofUuidHint: 'The VLESS user UUID of your WS/TLS backend.',
      snispoofSni: 'SNI / Host Domain',
      snispoofSniHint: 'The real backend domain used for TLS SNI and the WS Host header (e.g. zprt.example.com).',
      snispoofWsPath: 'WebSocket Path',
      snispoofAlpn: 'ALPN (Optional)',
      snispoofFingerprint: 'TLS Fingerprint (Optional)',
      snispoofPasteVless: 'Prefill from vless:// link',
      snispoofApplyVless: 'Fill',
      snispoofDesyncSection: 'DPI desync (zapret) on the front port',
      hysteria2Hint: 'Hysteria2 is a QUIC/HTTP3 carrier. The foreign server runs the QUIC server and reaches its local service (e.g. WireGuard on 8581); the Iran node runs the client and exposes the same public ports to users, while DPI only sees an encrypted QUIC/TLS handshake. Ideal for tunneling WireGuard UDP — and V2Ray TCP — without being fingerprinted.',
      hysteria2Ports: 'Public Ports',
      hysteria2PortsHint: 'Ports exposed on the Iran node (comma-separated). For WireGuard use the same UDP port as the foreign WG, e.g. 8581.',
      hysteria2ControlPort: 'QUIC Port (foreign)',
      hysteria2ControlPortHint: 'UDP/QUIC port the foreign server listens on (looks like HTTP/3). 443 blends in best.',
      hysteria2TargetHost: 'Target Host (foreign)',
      hysteria2TargetHostHint: 'Where the foreign server forwards traffic. 127.0.0.1 if WireGuard/V2Ray runs on the same foreign server.',
      hysteria2TargetPort: 'Target Port (optional)',
      hysteria2TargetPortHint: 'Service port on the foreign side. Leave empty to reuse the public port (recommended for WireGuard).',
      hysteria2TargetPortPlaceholder: 'Same as public port',
      hysteria2Sni: 'SNI (camouflage)',
      hysteria2SniHint: 'Domain shown in the TLS handshake. A common, unblocked domain blends in best.',
      hysteria2Obfs: 'Salamander obfuscation',
      hysteria2ObfsHint: 'Hides the QUIC handshake so DPI cannot fingerprint it. Keep ON for Iran; auto-tune can verify.',
      hysteria2ManualTitle: 'On the foreign server, make sure:',
      hysteria2ManualBody: '• Open UDP port {control_port} in the firewall (QUIC).\n• The target service is reachable at {target} (e.g. WireGuard listening on 8581).\n• Open the public port(s) {ports} on the Iran node so users can connect.',
      hysteria2Autotune: 'Auto-tune',
      hysteria2Tuning: 'Tuning…',
      hysteria2AutotuneHint: 'Measures real throughput/latency with obfuscation ON vs OFF and keeps the best.',
      hysteria2BestObfs: 'Best',
      hysteria2Applied: 'applied',
      hysteria2NoWorking: 'No working profile found — check the foreign QUIC port and firewall.',
      tuicHint: 'TUIC is a second QUIC carrier alongside Hysteria2, with a different QUIC/TLS fingerprint. Use it for protocol diversity: if Hysteria2 ever gets flagged, switch the same WireGuard/V2Ray ports onto TUIC without re-provisioning. The foreign server runs the TUIC server (self-signed TLS, auto uuid+password); the Iran node runs the client and exposes the public ports.',
      tuicUdpRelayMode: 'UDP relay mode',
      tuicUdpRelayModeHint: 'native = QUIC datagrams (fastest, best for WireGuard). quic = lossless over QUIC streams (use if datagrams are dropped).',
      warpHint: 'WARP-MASQUE egress (usque). Runs a local SOCKS5 proxy on one node (normally the foreign server) whose traffic exits through Cloudflare WARP over MASQUE/HTTP3. Point a proxy outbound (V2Ray/Xray, or the SNI-Spoof outbound) at this SOCKS5 to hide the server\'s real IP behind a Cloudflare IP. The panel auto-registers a WARP account on first apply.',
      warpNode: 'Node (runs the proxy)',
      warpNodeHint: 'Pick the server whose egress IP you want to mask — normally the foreign server. usque registers + runs there.',
      warpSelectNode: 'Select a node…',
      warpListenAddr: 'SOCKS listen address',
      warpListenAddrHint: '127.0.0.1 keeps the proxy local-only (recommended). Use 0.0.0.0 + username/password to share it.',
      warpListenPort: 'SOCKS port',
      warpListenPortHint: 'Local SOCKS5 port other services connect to. Default 1080.',
      warpSni: 'MASQUE SNI (optional)',
      warpSniHint: 'Leave empty for the Cloudflare default. A custom domain can help if the default SNI is blocked.',
      warpUsername: 'Username',
      warpPassword: 'Password',
      warpOptional: 'optional',
      warpAuthHint: 'Set username + password only if you expose the proxy on 0.0.0.0; for 127.0.0.1 leave both empty.',
      warpProxyTitle: 'Proxy URL (use as an outbound in your panel):',
      warpCopy: 'Copy',
      warpCopied: 'Copied',
      warpManualTitle: 'To actually route traffic through WARP:',
      warpManualBody: '• In your V2Ray/Xray (e.g. Sanaei) panel, add a SOCKS outbound: {proxy}\n• Route the inbounds/users you want hidden to that outbound.\n• No firewall change needed if the address is 127.0.0.1 (the proxy is local to this node).\n• First apply may take a few seconds while a WARP account is registered.',
      warpTestNow: 'Test WARP',
      warpTesting: 'Testing…',
      warpTestHint: 'Fetches Cloudflare\'s trace through the proxy and shows the masked egress IP.',
      warpTestFail: 'Test failed: {err}',
      obfs4Hint: 'obfs4 is the severe-crisis TCP fallback: it defeats active probing and randomises the byte stream so DPI sees no signature. Use it only when QUIC/UDP (Hysteria2/TUIC) is fully blocked and just TCP survives. The foreign server runs the obfs4 server (auto-generates its key/cert); the Iran node runs the client and exposes the public TCP port. obfs4 carries any TCP-based V2Ray transport (raw/WS/gRPC/XHTTP). The panel exchanges the cert automatically.',
      obfs4Ports: 'Public Ports (TCP)',
      obfs4PortsHint: 'TCP ports exposed on the Iran node that users connect to (comma-separated). 443 blends in best.',
      obfs4ControlPort: 'obfs4 Port (foreign)',
      obfs4ControlPortHint: 'TCP port the foreign obfs4 server listens on. Pick something free, e.g. 8443.',
      obfs4TargetHost: 'Target Host (foreign)',
      obfs4TargetHostHint: 'Where the foreign server forwards traffic. 127.0.0.1 if V2Ray runs on the same foreign server.',
      obfs4TargetPort: 'Target Port (optional)',
      obfs4TargetPortHint: 'Service port on the foreign side (e.g. the V2Ray inbound). Leave empty to reuse the public port.',
      obfs4TargetPortPlaceholder: 'Same as public port',
      obfs4IatMode: 'IAT mode',
      obfs4IatModeHint: '0 = fastest (no inter-arrival timing obfuscation). 1/2 add timing obfuscation for stronger evasion at the cost of speed. Keep 0 unless probing is severe.',
      obfs4IatOff: 'off (fastest)',
      obfs4IatEnabled: 'enabled',
      obfs4IatParanoid: 'paranoid',
      obfs4ManualBody: '• Open TCP port {control_port} in the foreign firewall (the obfs4 listener).\n• The target service must be reachable at {target} (e.g. your V2Ray inbound).\n• Open the public TCP port(s) {ports} on the Iran node so users can connect.\n• Point your V2Ray/WireGuard clients at the Iran node IP on the public port.',
    },
    coreHealth: {
      title: 'Core Health',
      subtitle: 'Monitor and manage reverse tunnel cores',
    },
    logs: {
      title: 'Logs',
      subtitle: 'View system and application logs',
    },
    settings: {
      title: 'Settings',
      frpCommunication: 'FRP Communication',
      frpDescription: 'Use FRP reverse tunnel for panel-node communication instead of direct HTTP.',
      enableFrp: 'Enable FRP Communication',
      frpPort: 'FRP Port',
      frpPortDescription: 'Port where FRP server listens for node connections',
      frpToken: 'FRP Token (Optional)',
      frpTokenOptional: 'FRP Token (Optional)',
      frpTokenDescription: 'Optional authentication token for FRP connections',
      telegramBot: 'Telegram Bot',
      telegramDescription: 'Configure Telegram bot for remote panel management via Telegram.',
      enableTelegram: 'Enable Telegram Bot',
      botToken: 'Bot Token',
      botTokenDescription: 'Get your bot token from @BotFather on Telegram',
      adminUserIds: 'Admin User IDs',
      adminUserIdsDescription: 'User IDs of Telegram users who can use the bot. Get your ID from @userinfobot',
      addAdminId: 'Add Admin ID',
      remove: 'Remove',
      automaticBackup: 'Automatic Backup',
      enableBackup: 'Enable Automatic Backup',
      backupInterval: 'Backup Interval',
      intervalUnit: 'Interval Unit',
      minutes: 'Minutes',
      hours: 'Hours',
      backupDescription: 'Panel will automatically send backup files to all admin users at the specified interval.',
      tunnelAutoReapply: 'Tunnel Auto Reapply',
      enableTunnelAutoReapply: 'Enable Automatic Tunnel Reapply',
      tunnelAutoReapplyDescription: 'Automatically reapply all tunnels at specified intervals',
      tunnelReapplyInterval: 'Reapply Interval',
      panelUpdate: 'Panel Update',
      panelUpdateDescription: 'Update the panel and all nodes from GitHub releases. A foreign node with internet access is used as the relay, so the panel itself does not need GitHub access.',
      currentVersion: 'Current version',
      loadReleases: 'Check for updates',
      loadingReleases: 'Loading releases...',
      selectRelease: 'Select release',
      noReleases: 'No releases found',
      startUpdate: 'Update panel & nodes',
      updateConfirm: 'Update the selected targets to {tag}? Services will restart during the update.',
      updateInProgress: 'Update in progress...',
      updateDone: 'Update finished',
      updateFailedTitle: 'Update failed',
      updateRelayNode: 'Relay node',
      updateDirectSource: 'direct from GitHub',
      accountSecurity: 'Account & Security',
      accountSecurityDesc: 'Change the username and password you use to sign in to the panel.',
      currentPasswordLabel: 'Current password',
      currentPasswordHint: 'Required to change your password or username.',
      newPasswordLabel: 'New password',
      confirmPasswordLabel: 'Confirm new password',
      changePasswordBtn: 'Change password',
      newUsernameLabel: 'New username',
      changeUsernameBtn: 'Change username',
      passwordChanged: 'Password changed successfully.',
      usernameChanged: 'Username changed successfully.',
      passwordMismatch: 'New password and confirmation do not match.',
      fillAllFields: 'Please fill in all required fields.',
      panelPortTitle: 'Panel Port',
      panelPortDesc: 'Change the port this panel listens on.',
      panelPortLabel: 'Port',
      panelPortWarning: 'Warning: registered nodes connect to the panel on this port. After changing it you must update each node and reopen the panel at the new URL. On native installs the panel restarts automatically.',
      applyPort: 'Apply & restart',
      panelPortDockerNote: 'Docker install detected: the new port is saved, but run `smite restart` on the host to apply it.',
      panelPortInvalid: 'Enter a valid port (1-65535).',
      panelPortConfirm: 'Change the panel port now? The panel will restart and its URL will change; nodes pointing at the old port will need updating.',
      panelPortSaved: 'Panel port saved.',
      updatePanelRow: 'Panel (this server)',
      updateTargets: 'What to update',
      updateNoTargets: 'Select at least one target to update',
      updateRefresh: 'Refresh status',
      statusPending: 'Pending',
      statusUploading: 'Uploading bundle...',
      statusApplying: 'Installing...',
      statusWaiting: 'Restarting...',
      statusUpdated: 'Updated',
      statusFailed: 'Failed',
      statusSkipped: 'Skipped',
      saveSettings: 'Save Settings',
      saving: 'Saving...',
      loadingSettings: 'Loading settings...',
      settingsSaved: 'Settings saved successfully',
      failedToLoad: 'Failed to load settings',
      failedToSave: 'Failed to save settings',
      enterAdminId: 'Enter admin user ID:',
    },
    common: {
      loading: 'Loading...',
    },
  },
  fa: {
    login: {
      title: 'لوکی',
      subtitle: 'پلتفرم مدیریت تونل',
      username: 'نام کاربری',
      password: 'رمز عبور',
      usernamePlaceholder: 'نام کاربری خود را وارد کنید',
      passwordPlaceholder: 'رمز عبور خود را وارد کنید',
      signIn: 'ورود',
      signingIn: 'در حال ورود...',
      loginFailed: 'ورود ناموفق بود. لطفاً اطلاعات خود را بررسی کنید.',
      checkCredentials: 'ورود ناموفق بود. لطفاً اطلاعات خود را بررسی کنید.',
    },
    dashboard: {
      title: 'داشبورد',
      subtitle: 'نمای کلی وضعیت سیستم و منابع',
      totalNodes: 'کل نودها',
      totalTunnels: 'کل تونل‌ها',
      cpuUsage: 'استفاده از CPU',
      memoryUsage: 'استفاده از حافظه',
      currentUsage: 'استفاده فعلی',
      active: 'فعال',
      systemResources: 'منابع سیستم',
      quickActions: 'اقدامات سریع',
      createNewTunnel: 'ایجاد تونل جدید',
      addNode: 'افزودن سرور ایران',
      addServer: 'افزودن سرور خارجی',
      loadingDashboard: 'در حال بارگذاری داشبورد...',
    },
    navigation: {
      dashboard: 'داشبورد',
      nodes: 'نودهای ایران',
      servers: 'سرورهای خارج',
      installNode: 'نصب نود',
      tunnels: 'تونل‌ها',
      coreHealth: 'سلامت هسته',
      logs: 'لاگ‌ها',
      settings: 'تنظیمات',
      logout: 'خروج',
      light: 'روشن',
      dark: 'تاریک',
    },
    nodes: {
      title: 'نودهای ایران',
      subtitle: 'مدیریت نودهای ایران',
      addNode: 'افزودن سرور ایران',
      viewCACertificate: 'مشاهده گواهی CA',
      downloadCA: 'دانلود CA',
      revokedTitle: 'نودهای مسدود (حذف‌شده)',
      revokedDesc: 'این سرورها حذف شده‌اند و از ثبت‌نام خودکار مجدد مسدودند. برای اجازه‌ی دوباره، آزاد کنید تا ایجنت آن (ظرف حدود ۶۰ ثانیه) دوباره ثبت شود.',
      allowAgain: 'اجازه‌ی دوباره',
    },
    servers: {
      title: 'سرورهای خارج',
      subtitle: 'مدیریت سرورهای خارج',
      viewCACertificate: 'مشاهده گواهی CA',
      downloadCA: 'دانلود CA',
    },
    installNode: {
      title: 'نصب نود',
      subtitle: 'نصب نود Loki، پنل 3x-ui یا وایرگارد روی سرور از راه دور از طریق SSH',
      serverSection: 'سرور هدف (SSH)',
      sshHost: 'آی‌پی / هاست سرور',
      sshPort: 'پورت SSH',
      sshUsername: 'نام کاربری SSH',
      sshPassword: 'رمز عبور SSH',
      role: 'نقش سرور',
      roleIran: 'سرور ایران',
      roleForeign: 'سرور خارج',
      systemUpgrade: 'ابتدا سرور را آپدیت و آپگرید کن',
      systemUpgradeDesc: 'قبل از نصب، apt-get update و upgrade را اجرا و پیش‌نیازها (python3، venv، curl) را نصب می‌کند. توصیه می‌شود؛ چند دقیقه زمان می‌برد.',
      nodeName: 'نام نود',
      panelSection: 'آدرس پنل (به نود داده می‌شود)',
      panelHost: 'هاست / آی‌پی پنل',
      panelHostHint: 'آدرسی که نود برای رسیدن به این پنل استفاده می‌کند',
      panelApiPort: 'پورت API پنل',
      componentsSection: 'موارد قابل نصب',
      installSmiteNode: 'نصب نود Loki',
      installSmiteNodeDesc: 'نود را نصب و به‌صورت خودکار در پنل ثبت می‌کند (ایران زیر نودها، خارج زیر سرورها)',
      installXui: 'نصب پنل 3x-ui (نسخه v2.9.4)',
      installXuiDesc: 'پنل سنایی را خودکار نصب می‌کند و اطلاعات ورود را برمی‌گرداند',
      installWireguard: 'نصب وایرگارد (wginstaller)',
      installWireguardDesc: 'وایرگارد + API مدیریتی wvpn (پورت 4000) را نصب و همه اطلاعات را برمی‌گرداند',
      wireguardForeignOnly: 'وایرگارد فقط برای سرورهای خارج قابل نصب است',
      xuiPort: 'پورت 3x-ui',
      xuiUsername: 'نام کاربری 3x-ui',
      xuiPassword: 'رمز عبور 3x-ui',
      randomIfEmpty: 'در صورت خالی بودن تصادفی',
      artifactsSection: 'فایل‌های نصب (برای سرورهای ایران لازم است)',
      artifactsHint: 'پنل به اینترنت دسترسی ندارد؛ برای سرورهای ایران این فایل‌ها را یک‌بار آپلود کنید: باندل آفلاین Loki (smite-offline-<arch>-<os>-py<XY>.tar.gz) و تارابال ریلیز 3x-ui (x-ui-linux-<arch>.tar.gz). باندلی را آپلود کنید که با نسخه پایتون سرور هم‌خوان باشد (py310 برای Ubuntu 22.04، py311 برای Debian 12، py312 برای Ubuntu 24.04) چون wheelهای آن مخصوص هر نسخه پایتون است. می‌توانید چند باندل آپلود کنید؛ پنل خودش باندل مناسب را انتخاب می‌کند. سرورهای خارج مستقیم از گیت‌هاب دانلود می‌کنند.',
      bundleArtifact: 'باندل آفلاین Loki',
      xuiArtifact: 'تارابال ریلیز 3x-ui',
      uploadBundle: 'آپلود باندل',
      uploadXui: 'آپلود تارابال 3x-ui',
      uploading: 'در حال آپلود...',
      noArtifact: 'فایلی آپلود نشده',
      requiredForIran: 'برای سرورهای ایران الزامی است',
      startInstall: 'شروع نصب',
      installing: 'در حال نصب...',
      selectComponent: 'حداقل یک مورد را برای نصب انتخاب کنید',
      liveLog: 'لاگ زنده نصب',
      resultsSection: 'نتایج نصب',
      statusPending: 'در انتظار',
      statusRunning: 'در حال اجرا',
      statusSuccess: 'موفق',
      statusError: 'ناموفق',
      nodeResult: 'نود Loki',
      xuiResult: 'پنل 3x-ui',
      wireguardResult: 'وایرگارد',
      copy: 'کپی',
      copied: 'کپی شد!',
      fieldHost: 'هاست',
      fieldMethod: 'روش نصب',
      fieldNote: 'توضیح',
      fieldError: 'خطا',
      panelUrl: 'آدرس پنل',
      username: 'نام کاربری',
      password: 'رمز عبور',
      port: 'پورت',
      webBasePath: 'مسیر وب',
      apiToken: 'توکن API',
      wgPort: 'پورت وایرگارد (UDP)',
      serverPublicKey: 'کلید عمومی سرور',
      serverEndpoint: 'اندپوینت سرور',
      apiBaseUrl: 'آدرس API مدیریتی',
      apiEndpoints: 'اندپوینت‌های API',
      apiKey: 'کلید API',
      apiKeyNote: 'کلید API',
      clientConfig: 'کانفیگ کلاینت پیش‌فرض',
      checkNodesPage: 'نود کمی بعد از نصب خودش را در پنل ثبت می‌کند — صفحه نودها/سرورها را بررسی کنید',
      nodeRegistered: 'نود در پنل ثبت شد',
      nodeWaitingRegistration: 'در انتظار ثبت نود در پنل...',
      startFailed: 'شروع نصب ناموفق بود',
      uploadFailed: 'آپلود ناموفق بود',
      deleteFailed: 'حذف ناموفق بود',
    },
    health: {
      title: 'سلامت و خودترمیمی',
      subtitle: 'تشخیص و رفع خودکار مشکلات تونل‌ها',
      allHealthy: 'همه‌ی تونل‌ها سالم‌اند. مشکلی یافت نشد.',
      runCheck: 'بررسی همین حالا',
      checking: 'در حال بررسی...',
      autoHeal: 'ترمیم خودکار هوشمند',
      autoHealHint: 'تونل‌های قطع‌شده/متداخل را تشخیص می‌دهد و خودکار رفع می‌کند.',
      fixNow: 'رفع کن',
      resolve: 'بستن',
      occurrences: 'بار',
      openProblems: 'مشکلات باز',
      lastChecked: 'آخرین بررسی',
      healDone: 'ترمیم اجرا شد',
      healFailed: 'ترمیم ناموفق بود (اتصال نود را بررسی کنید)',
    },
    tunnels: {
      title: 'تونل‌ها',
      subtitle: 'مدیریت اتصالات تونل',
      createTunnel: 'ایجاد تونل',
      name: 'نام',
      foreignServer: 'سرور خارجی',
      iranNode: 'نود ایران',
      type: 'نوع',
      core: 'هسته',
      ports: 'پورت‌ها',
      portsDescription: 'پورت‌ها (جدا شده با کاما، یکسان برای پنل و سرور هدف)',
      ratholeTransport: 'ترنسپورت',
      wgStealthLabel: 'WireGuard Stealth (TLS + SNI جعلی)',
      wgStealthHint: 'تونل TLS معکوس روی نود ایران، با پوشش HTTPS. ترافیک UDP وایرگارد را حمل می‌کند. پورت 8581 را وارد کنید.',
      fakeSni: 'SNI جعلی (دامنهٔ استتار)',
      fakeSniHint: 'دست‌دادن TLS این نام را نشان می‌دهد تا فایروال آن را ترافیک عادی به آن سایت ببیند.',
      remoteIP: 'ip مقصد',
      remoteIPDescription: 'آدرس IP سرور هدف (IPv4 یا IPv6)',
      selectForeignServer: 'یک سرور خارجی انتخاب کنید',
      selectIranNode: 'یک نود ایران انتخاب کنید',
      cancel: 'لغو',
      loadingTunnels: 'در حال بارگذاری تونل‌ها...',
      reapplyAll: 'اعمال مجدد همه',
      confirmReapplyAll: 'آیا از اعمال مجدد همه تونل‌ها مطمئن هستید؟',
      autoRestartTitle: 'ری‌استارت خودکار این تونل طبق زمان‌بندی',
      autoRestartOff: 'خاموش',
      restartService: 'ری‌استارت سرویس (توقف کامل و شروع دوباره)',
      confirmRestart: 'این تونل ری‌استارت شود؟ سرویس روی هر دو نود کامل متوقف و دوباره شروع می‌شود (چند ثانیه قطعی).',
      restartFailed: 'ری‌استارت تونل ناموفق بود (اتصال نود را بررسی کنید).',
      healthLabel: 'وضعیت زنده',
      healthStates: {
        healthy: 'متصل',
        connecting: 'در حال اتصال',
        degraded: 'ناقص',
        disconnected: 'قطع',
        conflict: 'تداخل',
        node_offline: 'نود آفلاین',
        stopped: 'متوقف',
        unknown: 'نامشخص',
      },
      reapplyAllSuccess: 'موفقیت',
      udp2rawHint: 'udp2raw ترافیک UDP را بین نود ایران (ورودی) و سرور خارجی (خروجی) در بسته‌های خام FakeTCP / ICMP / UDP کپسوله می‌کند.',
      trusttunnelHint: 'TrustTunnel (rstun) یک تونل معکوس مبتنی بر QUIC است. نود ایران سرور را اجرا می‌کند (پورت‌های عمومی ورودی) و سرور خارجی از طریق QUIC/UDP به آن وصل شده و ترافیک را به سرویس محلی خود هدایت می‌کند.',
      zapretHint: 'zapret با اجرای nfqws روی یک نود، DPI را با دی‌سینک (جعل SNI) دور می‌زند تا TLS روی پورت ۴۴۳ بسته نشود. آن را روی همان سروری اجرا کنید که اتصال TLS خروجی را باز می‌کند (مثلاً سرور Xray/VLESS با دامین‌فرانتینگ). این روش بین دو نود تونل نمی‌سازد.',
      coreChangeHint: 'تغییر هسته: پورت‌های عمومی ({ports}) حفظ می‌شوند. تنظیمات داخلی (توکن‌ها، پورت‌های کنترل) برای هسته جدید دوباره ساخته می‌شوند.',
      bulkSelectedCount: 'انتخاب شده',
      bulkApply: 'اعمال موارد انتخابی',
      bulkChange: 'تغییر هسته/نوع',
      bulkDelete: 'حذف موارد انتخابی',
      bulkConfirmDelete: 'تونل‌های انتخاب‌شده حذف شوند؟',
      bulkResultsTitle: 'نتایج عملیات گروهی',
      bulkNewCore: 'هسته جدید',
      bulkNewType: 'نوع جدید',
      bulkKeepType: 'حفظ فعلی / پیش‌فرض',
      bulkRun: 'اعمال تغییر',
      bulkRunning: 'در حال انجام...',
      benchmarkButton: 'تست بین نودها',
      benchmarkTitle: 'تست کیفیت تونل بین نودها',
      benchmarkHint: 'تمام هسته‌ها و حالت‌های تونل بین نود ایران و سرور خارجی انتخاب‌شده تست و بر اساس کیفیت رتبه‌بندی می‌شوند. تست‌ها به صورت متوالی روی پورت‌های آزمایشی اجرا می‌شوند و ممکن است چند دقیقه طول بکشد.',
      benchmarkRun: 'شروع تست',
      benchmarkRunning: 'در حال تست...',
      benchmarkLatency: 'تاخیر',
      benchmarkThroughput: 'پهنای باند',
      benchmarkLoss: 'از دست رفتن بسته',
      benchmarkFailed: 'ناموفق',
      benchmarkUseConfig: 'استفاده از این تنظیمات',
      benchmarkCoreMode: 'هسته / حالت',
      benchmarkScore: 'امتیاز',
      zapretNode: 'نود',
      selectZapretNode: 'یک نود انتخاب کنید',
      zapretNodeHint: 'تنها سروری که nfqws و قوانین NFQUEUE روی آن اجرا می‌شود (معمولاً سرور خارجی/پروکسی).',
      zapretTargetIp: 'آی‌پی مقصد (اختیاری)',
      zapretTargetIpHint: 'دی‌سینک فقط روی همین آی‌پی مقصد اعمال می‌شود (مثلاً آی‌پی CDN/فرانت). خالی بگذارید تا همه ترافیک پورت‌های فیلتر دی‌سینک شود.',
      snispoofHint: 'SNI Spoof یک فرانت‌پروکسی Xray روی این نود اجرا می‌کند: یک اینباند VLESS محلی (127.0.0.1:پورت) که اوتباند آن با WS+TLS به یک آی‌پی/دامنه فرانت می‌رود و همزمان zapret/nfqws دامنه SNI را برای DPI با یک دامنه بدلی جایگزین می‌کند. اوتباند پنل خود (مثلاً سنایی) را به همین پورت محلی وصل کنید.',
      snispoofClientHint: 'در پنل پروکسی خود یک اوتباند VLESS TCP به 127.0.0.1:{port} با UUID {uuid} بسازید (security: none).',
      snispoofClientOutboundTitle: 'اوتباند کلاینت (در سنایی/پنل خود وارد کنید)',
      snispoofClientOutboundHint: 'VLESS ساده روی TCP، بدون TLS، بدون WebSocket، بدون SNI/Host. از Inbound UUID زیر استفاده کنید — نه UUID بک‌اند.',
      snispoofCopyLink: 'کپی لینک',
      snispoofCopied: 'کپی شد!',
      snispoofTestSection: 'تست اتصال و تنظیم خودکار',
      snispoofTestHint: 'زنجیره را مثل یک کلاینت تست کنید، یا تنظیم خودکار را بزنید تا بهترین تنظیمات دی‌سینک پیدا شود.',
      snispoofTestNow: 'تست کن',
      snispoofTesting: 'در حال تست…',
      snispoofAutotune: 'تنظیم خودکار',
      snispoofTuning: 'در حال تنظیم…',
      snispoofTuningWait: 'همهٔ روش‌های دی‌سینک از مسیر تونل زنده تست می‌شوند — ممکن است ۱ تا ۳ دقیقه طول بکشد.',
      snispoofTestOk: 'وصل شد — زنجیره کار می‌کند ({ms} میلی‌ثانیه).',
      snispoofTestFail: 'وصل نشد: {err}',
      snispoofBestApplied: 'بهترین حالت اعمال شد: {mode} / {fooling} ({ms} میلی‌ثانیه). روی این تونل ذخیره شد.',
      snispoofNoneWorked: 'هیچ روش دی‌سینکی جواب نداد. ایپی فرانت / بک‌اند را بررسی کنید و دوباره امتحان کنید.',
      snispoofDesyncOptional: 'حتی بدون دی‌سینک هم وصل می‌شود — ایپی فرانت شما SNI-فیلتر نیست، پس zapret اینجا اختیاری است. دی‌سینک بدون تغییر ماند.',
      snispoofColMode: 'حالت',
      snispoofColFooling: 'Fooling',
      snispoofColResult: 'نتیجه',
      snispoofColLatency: 'تأخیر',
      snispoofLocalPort: 'پورت محلی',
      snispoofLocalPortHint: 'پورت اینباند VLESS محلی که پنل پروکسی شما به آن وصل می‌شود (127.0.0.1).',
      snispoofInboundUuid: 'UUID اینباند',
      snispoofInboundUuidHint: 'UUID اتصال پنل پروکسی به اینباند محلی. خودکار ساخته می‌شود.',
      snispoofRegenerate: 'ساخت مجدد',
      snispoofFrontAddress: 'آی‌پی / آدرس فرانت',
      snispoofFrontAddressHint: 'آی‌پی لبه CDN (مثل 104.19.229.21) یا دامنه‌ای که اوتباند به آن وصل می‌شود.',
      snispoofFrontPort: 'پورت فرانت',
      snispoofUuid: 'UUID بک‌اند',
      snispoofUuidHint: 'UUID کاربر VLESS در بک‌اند WS/TLS شما.',
      snispoofSni: 'دامنه SNI / Host',
      snispoofSniHint: 'دامنه واقعی بک‌اند برای SNI در TLS و هدر Host وب‌سوکت (مثل zprt.example.com).',
      snispoofWsPath: 'مسیر وب‌سوکت',
      snispoofAlpn: 'ALPN (اختیاری)',
      snispoofFingerprint: 'فینگرپرینت TLS (اختیاری)',
      snispoofPasteVless: 'پر کردن از لینک vless://',
      snispoofApplyVless: 'پر کن',
      snispoofDesyncSection: 'دی‌سینک DPI (zapret) روی پورت فرانت',
      hysteria2Hint: 'Hysteria2 یک حامل QUIC/HTTP3 است. سرور خارج، سرور QUIC را اجرا می‌کند و به سرویس محلی خود (مثلاً وایرگارد روی 8581) می‌رسد؛ نود ایران نقش کلاینت را دارد و همان پورت‌های عمومی را برای کاربران باز می‌کند، در حالی‌که DPI فقط یک هندشیک رمزشدهٔ QUIC/TLS می‌بیند. برای تونل‌کردن وایرگارد (UDP) و همچنین V2Ray (TCP) بدون شناسایی، ایده‌آل است.',
      hysteria2Ports: 'پورت‌های عمومی',
      hysteria2PortsHint: 'پورت‌هایی که روی نود ایران باز می‌شوند (با کاما جدا کنید). برای وایرگارد همان پورت UDP سرور خارج را بزنید، مثلاً 8581.',
      hysteria2ControlPort: 'پورت QUIC (خارج)',
      hysteria2ControlPortHint: 'پورت UDP/QUIC که سرور خارج روی آن گوش می‌دهد (شبیه HTTP/3). مقدار 443 بهترین استتار را دارد.',
      hysteria2TargetHost: 'هاست مقصد (خارج)',
      hysteria2TargetHostHint: 'جایی که سرور خارج ترافیک را به آن می‌فرستد. اگر وایرگارد/V2Ray روی همان سرور خارج است، 127.0.0.1 بگذارید.',
      hysteria2TargetPort: 'پورت مقصد (اختیاری)',
      hysteria2TargetPortHint: 'پورت سرویس در سمت خارج. خالی بگذارید تا همان پورت عمومی استفاده شود (برای وایرگارد پیشنهاد می‌شود).',
      hysteria2TargetPortPlaceholder: 'مثل پورت عمومی',
      hysteria2Sni: 'SNI (استتار)',
      hysteria2SniHint: 'دامنه‌ای که در هندشیک TLS نشان داده می‌شود. یک دامنهٔ پرکاربرد و بازنشده بهترین استتار را دارد.',
      hysteria2Obfs: 'مبهم‌سازی Salamander',
      hysteria2ObfsHint: 'هندشیک QUIC را پنهان می‌کند تا DPI نتواند آن را شناسایی کند. برای ایران روشن نگه دارید؛ اتوتیون می‌تواند بررسی کند.',
      hysteria2ManualTitle: 'روی سرور خارج مطمئن شوید که:',
      hysteria2ManualBody: '• پورت UDP شمارهٔ {control_port} در فایروال باز است (QUIC).\n• سرویس مقصد روی {target} در دسترس است (مثلاً وایرگارد روی 8581).\n• پورت(های) عمومی {ports} روی نود ایران باز است تا کاربران وصل شوند.',
      hysteria2Autotune: 'اتوتیون',
      hysteria2Tuning: 'در حال تنظیم…',
      hysteria2AutotuneHint: 'سرعت و تأخیر واقعی را با مبهم‌سازی روشن و خاموش می‌سنجد و بهترین را نگه می‌دارد.',
      hysteria2BestObfs: 'بهترین',
      hysteria2Applied: 'اعمال شد',
      hysteria2NoWorking: 'پروفایل کارآمدی پیدا نشد — پورت QUIC خارج و فایروال را بررسی کنید.',
      tuicHint: 'TUIC حامل QUIC دومی در کنار Hysteria2 است با اثرانگشت QUIC/TLS متفاوت. برای تنوع پروتکل استفاده کنید: اگر روزی Hysteria2 شناسایی شد، همان پورت‌های وایرگارد/V2Ray را بدون تنظیم مجدد روی TUIC منتقل کنید. سرور خارج، سرور TUIC را اجرا می‌کند (TLS خودامضا، uuid+رمز خودکار)؛ نود ایران کلاینت را اجرا کرده و پورت‌های عمومی را باز می‌کند.',
      tuicUdpRelayMode: 'حالت رله UDP',
      tuicUdpRelayModeHint: 'native = دیتاگرام QUIC (سریع‌ترین، مناسب وایرگارد). quic = بدون اتلاف روی استریم QUIC (اگر دیتاگرام‌ها افت کردند).',
      warpHint: 'خروجی WARP-MASQUE (usque). روی یک نود (معمولاً سرور خارج) یک پروکسی SOCKS5 محلی اجرا می‌کند که ترافیکش از طریق Cloudflare WARP روی MASQUE/HTTP3 خارج می‌شود. خروجی یک پروکسی (V2Ray/Xray یا خروجی SNI-Spoof) را به این SOCKS5 وصل کنید تا IP واقعی سرور پشت یک IP کلودفلر پنهان شود. پنل در اولین اعمال، خودش یک حساب WARP ثبت می‌کند.',
      warpNode: 'نود (اجراکنندهٔ پروکسی)',
      warpNodeHint: 'سروری را که می‌خواهید IP خروجی‌اش پنهان شود انتخاب کنید — معمولاً سرور خارج. usque همان‌جا ثبت و اجرا می‌شود.',
      warpSelectNode: 'یک نود انتخاب کنید…',
      warpListenAddr: 'آدرس شنود SOCKS',
      warpListenAddrHint: '۱۲۷.۰.۰.۱ پروکسی را فقط محلی نگه می‌دارد (توصیه‌شده). برای اشتراک‌گذاری از 0.0.0.0 + نام‌کاربری/رمز استفاده کنید.',
      warpListenPort: 'پورت SOCKS',
      warpListenPortHint: 'پورت SOCKS5 محلی که سرویس‌های دیگر به آن وصل می‌شوند. پیش‌فرض ۱۰۸۰.',
      warpSni: 'SNI برای MASQUE (اختیاری)',
      warpSniHint: 'برای حالت پیش‌فرض کلودفلر خالی بگذارید. اگر SNI پیش‌فرض بلاک شد، یک دامنهٔ سفارشی کمک می‌کند.',
      warpUsername: 'نام کاربری',
      warpPassword: 'رمز عبور',
      warpOptional: 'اختیاری',
      warpAuthHint: 'نام‌کاربری و رمز را فقط وقتی بگذارید که پروکسی را روی 0.0.0.0 باز می‌کنید؛ برای ۱۲۷.۰.۰.۱ هر دو را خالی بگذارید.',
      warpProxyTitle: 'آدرس پروکسی (به‌عنوان outbound در پنل خود استفاده کنید):',
      warpCopy: 'کپی',
      warpCopied: 'کپی شد',
      warpManualTitle: 'برای این‌که ترافیک واقعاً از WARP عبور کند:',
      warpManualBody: '• در پنل V2Ray/Xray (مثلاً سنایی)، یک outbound از نوع SOCKS اضافه کنید: {proxy}\n• inboundها/کاربرانی را که می‌خواهید پنهان شوند به همان outbound مسیر دهید.\n• اگر آدرس ۱۲۷.۰.۰.۱ است نیازی به تغییر فایروال نیست (پروکسی محلیِ همین نود است).\n• اولین اعمال ممکن است چند ثانیه طول بکشد چون یک حساب WARP ثبت می‌شود.',
      warpTestNow: 'تست WARP',
      warpTesting: 'در حال تست…',
      warpTestHint: 'تریس کلودفلر را از مسیر پروکسی می‌گیرد و IP خروجیِ پنهان‌شده را نشان می‌دهد.',
      warpTestFail: 'تست ناموفق: {err}',
      obfs4Hint: 'obfs4 فال‌بکِ TCP برای بحران شدید است: در برابر پروب فعال مقاوم است و جریان بایت‌ها را تصادفی می‌کند تا DPI هیچ امضایی نبیند. فقط وقتی استفاده کنید که QUIC/UDP (هیستریا۲/TUIC) کاملاً بلاک شده و فقط TCP کار می‌کند. سرور خارج، سرور obfs4 را اجرا می‌کند (کلید/گواهی را خودکار می‌سازد)؛ نود ایران کلاینت را اجرا و پورت عمومی TCP را باز می‌کند. obfs4 هر انتقال TCPـیِ V2Ray (خام/WS/gRPC/XHTTP) را حمل می‌کند. پنل گواهی را خودکار رد و بدل می‌کند.',
      obfs4Ports: 'پورت‌های عمومی (TCP)',
      obfs4PortsHint: 'پورت‌های TCP باز روی نود ایران که کاربران به آن وصل می‌شوند (با کاما جدا کنید). ۴۴۳ بهترین استتار است.',
      obfs4ControlPort: 'پورت obfs4 (خارج)',
      obfs4ControlPortHint: 'پورت TCP که سرور obfs4 خارج روی آن گوش می‌دهد. یک پورت آزاد مثل ۸۴۴۳ بگذارید.',
      obfs4TargetHost: 'هاست مقصد (خارج)',
      obfs4TargetHostHint: 'جایی که سرور خارج ترافیک را به آن می‌رساند. اگر V2Ray روی همان سرور خارج است، ۱۲۷.۰.۰.۱.',
      obfs4TargetPort: 'پورت مقصد (اختیاری)',
      obfs4TargetPortHint: 'پورت سرویس سمت خارج (مثلاً inbound وی‌تورِی). خالی بگذارید تا برابر پورت عمومی شود.',
      obfs4TargetPortPlaceholder: 'برابر پورت عمومی',
      obfs4IatMode: 'حالت IAT',
      obfs4IatModeHint: '۰ = سریع‌ترین (بدون مخفی‌سازی زمان‌بندی بسته‌ها). ۱/۲ مخفی‌سازی زمان‌بندی را اضافه می‌کنند (مقاوم‌تر ولی کندتر). جز در پروب شدید روی ۰ بماند.',
      obfs4IatOff: 'خاموش (سریع‌ترین)',
      obfs4IatEnabled: 'فعال',
      obfs4IatParanoid: 'حداکثری',
      obfs4ManualBody: '• پورت TCP {control_port} را در فایروال خارج باز کنید (شنوندهٔ obfs4).\n• سرویس مقصد باید روی {target} در دسترس باشد (مثلاً inbound وی‌تورِی).\n• پورت(های) عمومی TCP یعنی {ports} را روی نود ایران باز کنید تا کاربران وصل شوند.\n• کلاینت‌های V2Ray/وایرگارد را روی IP نود ایران و همان پورت عمومی تنظیم کنید.',
    },
    coreHealth: {
      title: 'سلامت هسته',
      subtitle: 'نظارت و مدیریت هسته‌های تونل معکوس',
    },
    logs: {
      title: 'لاگ‌ها',
      subtitle: 'مشاهده لاگ‌های سیستم و برنامه',
    },
    settings: {
      title: 'تنظیمات',
      frpCommunication: 'ارتباط FRP',
      frpDescription: 'استفاده از تونل معکوس FRP برای ارتباط پنل-نود به جای HTTP مستقیم.',
      enableFrp: 'فعال‌سازی ارتباط FRP',
      frpPort: 'پورت FRP',
      frpPortDescription: 'پورتی که سرور FRP برای اتصالات نود به آن گوش می‌دهد',
      frpToken: 'توکن FRP (اختیاری)',
      frpTokenOptional: 'توکن FRP (اختیاری)',
      frpTokenDescription: 'توکن احراز هویت اختیاری برای اتصالات FRP',
      telegramBot: 'ربات تلگرام',
      telegramDescription: 'پیکربندی ربات تلگرام برای مدیریت از راه دور پنل از طریق تلگرام.',
      enableTelegram: 'فعال‌سازی ربات تلگرام',
      botToken: 'توکن ربات',
      botTokenDescription: 'توکن ربات خود را از @BotFather در تلگرام دریافت کنید',
      adminUserIds: 'شناسه‌های کاربری ادمین',
      adminUserIdsDescription: 'شناسه‌های کاربری کاربران تلگرام که می‌توانند از ربات استفاده کنند. شناسه خود را از @userinfobot دریافت کنید',
      addAdminId: 'افزودن شناسه ادمین',
      remove: 'حذف',
      automaticBackup: 'پشتیبان‌گیری خودکار',
      enableBackup: 'فعال‌سازی پشتیبان‌گیری خودکار',
      backupInterval: 'فاصله پشتیبان‌گیری',
      intervalUnit: 'واحد فاصله',
      minutes: 'دقیقه',
      hours: 'ساعت',
      backupDescription: 'پنل به طور خودکار فایل‌های پشتیبان را در فاصله مشخص شده به همه کاربران ادمین ارسال می‌کند.',
      tunnelAutoReapply: 'اعمال مجدد خودکار تونل',
      enableTunnelAutoReapply: 'فعال کردن اعمال مجدد خودکار تونل',
      tunnelAutoReapplyDescription: 'به صورت خودکار همه تونل‌ها را در فواصل زمانی مشخص اعمال مجدد کنید',
      tunnelReapplyInterval: 'فاصله اعمال مجدد',
      panelUpdate: 'به‌روزرسانی پنل',
      panelUpdateDescription: 'به‌روزرسانی پنل و همه نودها از ریلیزهای گیت‌هاب. یک نود خارجی با دسترسی اینترنت به عنوان رله استفاده می‌شود، بنابراین خود پنل نیازی به دسترسی گیت‌هاب ندارد.',
      currentVersion: 'نسخه فعلی',
      loadReleases: 'بررسی به‌روزرسانی‌ها',
      loadingReleases: 'در حال دریافت ریلیزها...',
      selectRelease: 'انتخاب ریلیز',
      noReleases: 'ریلیزی یافت نشد',
      startUpdate: 'به‌روزرسانی پنل و نودها',
      updateConfirm: 'موارد انتخاب‌شده به {tag} به‌روزرسانی شوند؟ سرویس‌ها در حین به‌روزرسانی ری‌استارت می‌شوند.',
      updateInProgress: 'به‌روزرسانی در حال انجام است...',
      updateDone: 'به‌روزرسانی تمام شد',
      updateFailedTitle: 'به‌روزرسانی ناموفق بود',
      updateRelayNode: 'نود رله',
      updateDirectSource: 'مستقیم از گیت‌هاب',
      accountSecurity: 'حساب و امنیت',
      accountSecurityDesc: 'نام کاربری و رمز عبوری که با آن وارد پنل می‌شوید را تغییر دهید.',
      currentPasswordLabel: 'رمز عبور فعلی',
      currentPasswordHint: 'برای تغییر رمز عبور یا نام کاربری لازم است.',
      newPasswordLabel: 'رمز عبور جدید',
      confirmPasswordLabel: 'تکرار رمز عبور جدید',
      changePasswordBtn: 'تغییر رمز عبور',
      newUsernameLabel: 'نام کاربری جدید',
      changeUsernameBtn: 'تغییر نام کاربری',
      passwordChanged: 'رمز عبور با موفقیت تغییر کرد.',
      usernameChanged: 'نام کاربری با موفقیت تغییر کرد.',
      passwordMismatch: 'رمز عبور جدید و تکرار آن یکسان نیستند.',
      fillAllFields: 'لطفاً همه فیلدهای لازم را پر کنید.',
      panelPortTitle: 'پورت پنل',
      panelPortDesc: 'پورتی که پنل روی آن گوش می‌دهد را تغییر دهید.',
      panelPortLabel: 'پورت',
      panelPortWarning: 'هشدار: نودها روی این پورت به پنل وصل می‌شوند. پس از تغییر باید هر نود را به‌روزرسانی کنید و پنل را با آدرس/پورت جدید باز کنید. در نصب بومی، پنل به‌صورت خودکار ری‌استارت می‌شود.',
      applyPort: 'اعمال و ری‌استارت',
      panelPortDockerNote: 'نصب داکر شناسایی شد: پورت جدید ذخیره شد ولی برای اعمال باید روی هاست دستور `smite restart` را اجرا کنید.',
      panelPortInvalid: 'یک پورت معتبر وارد کنید (۱ تا ۶۵۵۳۵).',
      panelPortConfirm: 'پورت پنل همین حالا تغییر کند؟ پنل ری‌استارت می‌شود و آدرسش عوض می‌شود؛ نودهایی که به پورت قبلی وصل‌اند باید به‌روزرسانی شوند.',
      panelPortSaved: 'پورت پنل ذخیره شد.',
      updatePanelRow: 'پنل (این سرور)',
      updateTargets: 'چه چیزی به‌روزرسانی شود؟',
      updateNoTargets: 'حداقل یک مورد را برای به‌روزرسانی انتخاب کنید',
      updateRefresh: 'تازه‌سازی وضعیت',
      statusPending: 'در انتظار',
      statusUploading: 'در حال ارسال بسته...',
      statusApplying: 'در حال نصب...',
      statusWaiting: 'در حال ری‌استارت...',
      statusUpdated: 'به‌روزرسانی شد',
      statusFailed: 'ناموفق',
      statusSkipped: 'رد شد',
      saveSettings: 'ذخیره تنظیمات',
      saving: 'در حال ذخیره...',
      loadingSettings: 'در حال بارگذاری تنظیمات...',
      settingsSaved: 'تنظیمات با موفقیت ذخیره شد',
      failedToLoad: 'بارگذاری تنظیمات ناموفق بود',
      failedToSave: 'ذخیره تنظیمات ناموفق بود',
      enterAdminId: 'شناسه کاربری ادمین را وارد کنید:',
    },
    common: {
      loading: 'در حال بارگذاری...',
    },
  },
}

interface LanguageContextType {
  language: Language
  setLanguage: (lang: Language) => void
  t: Translations
  dir: 'ltr' | 'rtl'
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined)

export const LanguageProvider = ({ children }: { children: ReactNode }) => {
  const [language, setLanguageState] = useState<Language>(() => {
    const saved = localStorage.getItem('language')
    return (saved as Language) || 'en'
  })

  const setLanguage = (lang: Language) => {
    setLanguageState(lang)
    localStorage.setItem('language', lang)
    document.documentElement.setAttribute('dir', lang === 'fa' ? 'rtl' : 'ltr')
    document.documentElement.setAttribute('lang', lang)
    if (lang === 'fa') {
      document.body.style.fontFamily = "'Vazirmatn', sans-serif"
    } else {
      document.body.style.fontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    }
  }

  useEffect(() => {
    document.documentElement.setAttribute('dir', language === 'fa' ? 'rtl' : 'ltr')
    document.documentElement.setAttribute('lang', language)
    if (language === 'fa') {
      document.body.style.fontFamily = "'Vazirmatn', sans-serif"
    } else {
      document.body.style.fontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    }
  }, [language])

  const value: LanguageContextType = {
    language,
    setLanguage,
    t: translations[language],
    dir: language === 'fa' ? 'rtl' : 'ltr',
  }

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export const useLanguage = () => {
  const context = useContext(LanguageContext)
  if (context === undefined) {
    throw new Error('useLanguage must be used within a LanguageProvider')
  }
  return context
}

