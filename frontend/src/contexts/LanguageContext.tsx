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
    zapretHint: string
    zapretNode: string
    selectZapretNode: string
    zapretNodeHint: string
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
    }
  common: {
    loading: string
  }
}

const translations: Record<Language, Translations> = {
  en: {
    login: {
      title: 'Smite',
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
      zapretHint: 'zapret runs nfqws on a single node to desync DPI (SNI spoofing) so TLS on :443 is not blocked. Run it on the server that opens the outbound TLS connection (e.g. an Xray VLESS host doing domain-fronting). It does NOT tunnel traffic between nodes.',
      zapretNode: 'Node',
      selectZapretNode: 'Select a node',
      zapretNodeHint: 'The single server where nfqws + NFQUEUE rules will run (usually the foreign / proxy server).',
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
      title: 'اسمیت',
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
      zapretHint: 'zapret با اجرای nfqws روی یک نود، DPI را با دی‌سینک (جعل SNI) دور می‌زند تا TLS روی پورت ۴۴۳ بسته نشود. آن را روی همان سروری اجرا کنید که اتصال TLS خروجی را باز می‌کند (مثلاً سرور Xray/VLESS با دامین‌فرانتینگ). این روش بین دو نود تونل نمی‌سازد.',
      zapretNode: 'نود',
      selectZapretNode: 'یک نود انتخاب کنید',
      zapretNodeHint: 'تنها سروری که nfqws و قوانین NFQUEUE روی آن اجرا می‌شود (معمولاً سرور خارجی/پروکسی).',
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

