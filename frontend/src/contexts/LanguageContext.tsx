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
  }
  servers: {
    title: string
    subtitle: string
    viewCACertificate: string
    downloadCA: string
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
    remoteIP: string
    remoteIPDescription: string
    selectForeignServer: string
    selectIranNode: string
    cancel: string
    loadingTunnels: string
    reapplyAll: string
    confirmReapplyAll: string
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
    updatePanelRow: string
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
      title: 'Panel',
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
    },
    servers: {
      title: 'Foreign Nodes',
      subtitle: 'Manage your Foreign servers',
      viewCACertificate: 'View CA Certificate',
      downloadCA: 'Download CA',
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
      remoteIP: 'Remote IP',
      remoteIPDescription: 'Target server IP address (IPv4 or IPv6)',
      selectForeignServer: 'Select a foreign server',
      selectIranNode: 'Select an Iran node',
      cancel: 'Cancel',
      loadingTunnels: 'Loading tunnels...',
      reapplyAll: 'Reapply All',
      confirmReapplyAll: 'Are you sure you want to reapply all tunnels?',
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
      updateConfirm: 'Update the panel and ALL nodes to {tag}? Services will restart during the update.',
      updateInProgress: 'Update in progress...',
      updateDone: 'Update finished',
      updateFailedTitle: 'Update failed',
      updateRelayNode: 'Relay node',
      updatePanelRow: 'Panel (this server)',
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
      title: 'پنل',
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
    },
    servers: {
      title: 'سرورهای خارج',
      subtitle: 'مدیریت سرورهای خارج',
      viewCACertificate: 'مشاهده گواهی CA',
      downloadCA: 'دانلود CA',
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
      remoteIP: 'ip مقصد',
      remoteIPDescription: 'آدرس IP سرور هدف (IPv4 یا IPv6)',
      selectForeignServer: 'یک سرور خارجی انتخاب کنید',
      selectIranNode: 'یک نود ایران انتخاب کنید',
      cancel: 'لغو',
      loadingTunnels: 'در حال بارگذاری تونل‌ها...',
      reapplyAll: 'اعمال مجدد همه',
      confirmReapplyAll: 'آیا از اعمال مجدد همه تونل‌ها مطمئن هستید؟',
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
      updateConfirm: 'پنل و همه نودها به {tag} به‌روزرسانی شوند؟ سرویس‌ها در حین به‌روزرسانی ری‌استارت می‌شوند.',
      updateInProgress: 'به‌روزرسانی در حال انجام است...',
      updateDone: 'به‌روزرسانی تمام شد',
      updateFailedTitle: 'به‌روزرسانی ناموفق بود',
      updateRelayNode: 'نود رله',
      updatePanelRow: 'پنل (این سرور)',
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

