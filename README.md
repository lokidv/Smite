# Smite - پنل مدیریت تانل

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/SmiteD.png"/>
    <source media="(prefers-color-scheme: light)" srcset="assets/SmiteL.png"/>
    <img src="assets/SmiteL.png" alt="Smite Logo" width="200"/>
  </picture>
  
  **مدیریت مدرن تانل بر پایه GOST ،Backhaul ،Rathole ،Chisel ،FRP و udp2raw — با معماری دو‌نودی، رابط وب ساده، نمایش لحظه‌ای وضعیت اتصال و متن‌باز.**
  
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
  [![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
  [![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)
  [![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg)](https://www.typescriptlang.org/)
  [![Docker](https://img.shields.io/badge/Docker-24.0+-2496ED.svg)](https://www.docker.com/)
  [![Nginx](https://img.shields.io/badge/Nginx-1.25+-009639.svg)](https://www.nginx.com/)
  [![SQLite](https://img.shields.io/badge/SQLite-3.42+-003B57.svg)](https://www.sqlite.org/)
</div>

---

<div dir="rtl">

> 🇬🇧 **English version: [README.en.md](README.en.md)**

> **درباره این فورک** ([`lokidv/Smite`](https://github.com/lokidv/Smite) — فورک‌شده از [`zZedix/Smite`](https://github.com/zZedix/Smite)): این نسخه سه قابلیت اصلی به Smite اضافه می‌کند: **نصب کاملاً آفلاین و بدون داکر** برای سرورهای ایران/محدودشده، هسته تانل **udp2raw** (حالت‌های FakeTCP / ICMP / UDP) و هسته **zapret** برای دور زدن DPI (جعل SNI).

### کدام روش نصب مناسب من است؟

| وضعیت شما | روش پیشنهادی |
| --- | --- |
| 🇮🇷 سرور **داکر ندارد / به گیت‌هاب دسترسی ندارد / اینترنت بین‌الملل ندارد** | **[نصب بومی آفلاین](#-نصب-بومی-آفلاین-بدون-داکر)** (پیشنهادی) |
| سرور به Docker Hub و GitHub دسترسی دارد | **[نصب با داکر](#-نصب-پنل-داکر)** |

---

## ❗ سرور بدون دسترسی به GitHub

اگر سرور شما (مثلاً سرور ایران) به گیت‌هاب، Docker Hub، PyPI یا اینترنت بین‌الملل دسترسی ندارد، **هیچ چیزی لازم نیست روی خود سرور دانلود شود.** همه‌چیز — سورس پنل و نود، فرانت‌اند آماده، تمام پکیج‌های پایتون و تمام باینری‌های تانل (`gost`, `rathole`, `chisel`, `frpc`, `frps`, `backhaul`, `udp2raw`, `nfqws`/zapret, `rstund`/`rstunc`, `xray`) — داخل **یک فایل فشرده آفلاین** قرار دارد.

این فایل‌ها به‌صورت خودکار توسط GitHub Actions ساخته می‌شوند و در بخش **[Releases همین مخزن](https://github.com/lokidv/Smite/releases/latest)** قرار می‌گیرند. کافی است:

۱. از یک سیستم که اینترنت دارد (لپ‌تاپ خودتان، یک سرور خارج و...) فایل باندل مناسب سرورتان را از صفحه Releases دانلود کنید؛

۲. فایل را با `scp` (یا هر روش دیگری) به سرور منتقل کنید؛

۳. روی سرور extract کنید و اسکریپت نصب را اجرا کنید. تمام!

جزئیات کامل در بخش **[نصب بومی آفلاین](#-نصب-بومی-آفلاین-بدون-داکر)** آمده است.

</div>

---

<div dir="rtl">

## 🚀 امکانات

- **انواع تانل**: پشتیبانی از TCP ،UDP ،WebSocket ،gRPC و TCPMux از طریق GOST ،Backhaul ،Rathole ،Chisel ،FRP و udp2raw (حالت‌های FakeTCP / ICMP / UDP)
- **دور زدن DPI (zapret)**: اجرای `nfqws` به‌صورت تک‌نودی برای desync کردن ترافیک TLS / جعل SNI تا فیلترینگ مبتنی بر SNI روی پورت ۴۴۳ بی‌اثر شود + امکان محدودکردن به یک IP مقصد (راهنمای کامل: [docs/ZAPRET.md](docs/ZAPRET.md))
- **SNI Spoof (فرانت‌پروکسی)**: هسته `snispoof` که فرانت‌پروکسی Xray (اینباند VLESS محلی + اوتباند WS/TLS با domain fronting) را همراه دی‌سینک zapret به‌صورت یک تانل مدیریت‌شده اجرا می‌کند
- **مدیریت یکپارچه نودها**: نودهای ایران و خارج برای تانل‌های معکوس از یک پنل واحد مدیریت می‌شوند
- **رابط وب**: رابط کاربری مدرن و ساده با نمایش لحظه‌ای وضعیت اتصال
- **ابزارهای CLI**: ابزارهای خط فرمان قدرتمند برای مدیریت
- **ربات تلگرام**: آمار پنل و بکاپ خودکار از طریق تلگرام
- **فورواردینگ GOST**: انتقال ترافیک از نود ایران به سرور خارج با پشتیبانی از TCP ،UDP ،WebSocket ،gRPC و TCPMux
- **نصب بومی آفلاین**: نصب پنل و نودها بدون داکر، بدون گیت‌هاب و بدون اینترنت بین‌الملل با یک باندل از پیش ساخته‌شده (systemd + Python venv)

---

## 📋 پیش‌نیازها

- برای نصب مبتنی بر داکر: Docker و Docker Compose
- روی سرورهای ایران، اول داکر را نصب کنید:

</div>

```bash
curl -fsSL https://raw.githubusercontent.com/manageitir/docker/main/install-ubuntu.sh | sh
```

<div dir="rtl">

- **داکر یا اینترنت ندارید؟** از [نصب بومی آفلاین](#-نصب-بومی-آفلاین-بدون-داکر) استفاده کنید — روی سرور مقصد فقط `python3` و `openssl` لازم است (هر دو به‌صورت پیش‌فرض روی اوبونتو نصب هستند).

---

## 🔧 نصب پنل (داکر)

> برای سرورهایی که به Docker Hub و GitHub دسترسی دارند. اگر سرورتان در ایران است یا فیلترینگ شدید دارد، مستقیم بروید سراغ **[نصب بومی آفلاین](#-نصب-بومی-آفلاین-بدون-داکر)**.

### نصب سریع

</div>

```bash
sudo bash -c "$(curl -sL https://raw.githubusercontent.com/lokidv/Smite/main/scripts/install.sh)"
```

<details>
<summary><strong>نصب دستی</strong></summary>

<div dir="rtl">

۱. کلون کردن مخزن:

</div>

```bash
git clone https://github.com/lokidv/Smite.git
cd Smite
```

<div dir="rtl">

۲. کپی فایل تنظیمات و ویرایش آن:

</div>

```bash
cp .env.example .env
# فایل .env را مطابق نیاز خود ویرایش کنید
```

<div dir="rtl">

۳. نصب ابزارهای CLI:

</div>

```bash
sudo bash cli/install_cli.sh
```

<div dir="rtl">

۴. اجرای سرویس‌ها:

</div>

```bash
docker compose up -d
```

<div dir="rtl">

۵. ساخت کاربر ادمین:

</div>

```bash
smite admin create
```

<div dir="rtl">

۶. رابط وب در آدرس `http://localhost:8000` در دسترس است.

</div>

</details>

---

<div dir="rtl">

## 🖥️ نصب نود (داکر)

> نصب نود مبتنی بر داکر. برای سرورهای آفلاین/ایران از **[نصب بومی آفلاین ← گام ۴](#گام-۴--نصب-نودها-سرورهای-آفلاین)** استفاده کنید.

### معماری

- **نودهای ایران**: تانل‌های معکوس (Rathole ،Backhaul ،Chisel ،FRP ،udp2raw) و فورواردرهای GOST را اجرا می‌کنند
- **نودهای خارج**: طرف دیگر تانل‌های معکوس هستند و ترافیک فورواردشده از نودهای ایران را دریافت می‌کنند

### نصب سریع

</div>

```bash
sudo bash -c "$(curl -sL https://raw.githubusercontent.com/lokidv/Smite/main/scripts/smite-node.sh)"
```

<details>
<summary><strong>نصب دستی</strong></summary>

<div dir="rtl">

۱. رفتن به پوشه node:

</div>

```bash
cd node
```

<div dir="rtl">

۲. کپی گواهی CA پنل:

</div>

```bash
mkdir -p certs
# برای نودهای ایران از ca.crt استفاده کنید
cp /path/to/panel/ca.crt certs/ca.crt
# برای سرورهای خارج از ca-server.crt استفاده کنید
# cp /path/to/panel/ca-server.crt certs/ca.crt
```

<div dir="rtl">

۳. ساخت فایل `.env`:

</div>

```bash
cat > .env << EOF
NODE_API_PORT=8888
NODE_NAME=node-1
PANEL_CA_PATH=/etc/smite-node/certs/ca.crt
PANEL_ADDRESS=panel.example.com:443
EOF
```

<div dir="rtl">

> **نکته**: پنل هنگام ثبت نود، نقش آن را اعتبارسنجی می‌کند. هر نود باید نقش ثابتی (iran یا foreign) داشته باشد تا تداخلی پیش نیاید.

۴. اجرای نود:

</div>

```bash
docker compose up -d
```

</details>

---

<div dir="rtl">

## 📦 نصب بومی آفلاین (بدون داکر)

برای سرورهایی که **به داکر، گیت‌هاب، PyPI ،npm یا اینترنت بین‌الملل دسترسی ندارند** (مثل سرورهای ایران در شرایط محدودیت شدید)، Smite به‌صورت بومی با `systemd` + Python `venv` و از روی **یک فایل tar.gz از پیش ساخته‌شده** نصب می‌شود. تنها پیش‌نیاز روی سرور مقصد `python3` (با `venv`) و `openssl` است — هر دو به‌صورت پیش‌فرض روی اوبونتو وجود دارند.

### گام ۱ — دریافت باندل آفلاین

**روش الف (پیشنهادی) — دانلود باندل آماده از [GitHub Releases](https://github.com/lokidv/Smite/releases/latest):**

باندل‌ها برای هر نسخه (تگ) به‌صورت خودکار توسط GitHub Actions ساخته می‌شوند (فایل `.github/workflows/offline-bundle.yml`). از یک سیستم که اینترنت دارد، فایل مناسب با **معماری و سیستم‌عامل سرورتان** را دانلود کنید:

| سیستم‌عامل سرور | پایتون | فایل |
| --- | --- | --- |
| Ubuntu 22.04 (amd64) | 3.10 | `smite-offline-amd64-ubuntu22.04-py310.tar.gz` |
| Debian 12 (amd64) | 3.11 | `smite-offline-amd64-debian12-py311.tar.gz` |
| Ubuntu 24.04 (amd64) | 3.12 | `smite-offline-amd64-ubuntu24.04-py312.tar.gz` |
| Ubuntu 22.04 (arm64) | 3.10 | `smite-offline-arm64-ubuntu22.04-py310.tar.gz` |
| Debian 12 (arm64) | 3.11 | `smite-offline-arm64-debian12-py311.tar.gz` |
| Ubuntu 24.04 (arm64) | 3.12 | `smite-offline-arm64-ubuntu24.04-py312.tar.gz` |

> ⚠️ پکیج‌های پایتون داخل باندل باید با نسخه پایتون سرور یکی باشند — فایل مربوط به سیستم‌عامل خودتان را بردارید. نسخه پایتون سرور را با `python3 -V` بررسی کنید. فارغ از اسم فایل، پوشه‌ای که extract می‌شود `smite-offline-<arch>` نام دارد.

> 💡 اگر سیستم‌عامل سرور شما در جدول نیست، با «روش ب» باندل را خودتان روی یک ماشین با همان سیستم‌عامل و نسخه پایتون بسازید. همچنین می‌توانید بدون ساخت تگ، از تب **Actions** مخزن، workflow با نام «Build Offline Bundle» را به‌صورت دستی (Run workflow) اجرا کنید و خروجی را از بخش Artifacts همان اجرا بردارید.

**روش ب — ساخت باندل توسط خودتان (روی یک ماشین با اینترنت):**

</div>

```bash
git clone https://github.com/lokidv/Smite.git
cd Smite
bash scripts/build-offline-bundle.sh
```

<div dir="rtl">

خروجی، فایل `smite-offline-<arch>.tar.gz` است که شامل سورس پنل/نود، فرانت‌اند بیلدشده، تمام wheelهای pip، تمام باینری‌های تانل (`gost`, `rathole`, `chisel`, `frpc`, `frps`, `backhaul`, `udp2raw`, `nfqws`/zapret, `rstund`/`rstunc`, `xray`)، یونیت‌های systemd، ابزارهای CLI و اسکریپت‌های نصب بومی است.

گزینه‌ها (متغیرهای محیطی):

</div>

```bash
TARGET_ARCH=arm64 bash scripts/build-offline-bundle.sh          # ساخت برای سرورهای arm64
TARGET_PY=311 TARGET_PLATFORM=manylinux2014_x86_64 \
  bash scripts/build-offline-bundle.sh                          # دانلود wheel برای پایتون/سیستم‌عامل دیگر
SKIP_FRONTEND=1 bash scripts/build-offline-bundle.sh            # استفاده از frontend/dist موجود
```

<div dir="rtl">

> **نکته**: باندل را روی همان سیستم‌عامل/نسخه پایتونِ سرور مقصد بسازید (مثلاً Ubuntu 22.04 ← پایتون 3.10) یا `TARGET_PY`/`TARGET_PLATFORM` را تنظیم کنید تا wheelها سازگار باشند.

### گام ۲ — انتقال باندل به سرور آفلاین

</div>

```bash
scp smite-offline-amd64-ubuntu22.04-py310.tar.gz root@your-server:/root/
```

<div dir="rtl">

### گام ۳ — نصب پنل (روی سرور آفلاین)

</div>

```bash
tar -xzf smite-offline-amd64-*.tar.gz
cd smite-offline-amd64
sudo bash scripts/install-native.sh
```

<div dir="rtl">

اسکریپت نصب، `/opt/smite` را با یک venv پایتون راه‌اندازی می‌کند (نصب پکیج‌ها کاملاً آفلاین با `pip --no-index`)، تمام باینری‌های تانل را در `/usr/local/bin` کپی می‌کند، فرانت‌اند آماده را نصب می‌کند، بهینه‌سازی‌های شبکه (BBR ،sysctl ،limits) را اعمال می‌کند، فایل `.env` را به‌صورت تعاملی می‌سازد و سرویس `smite-panel` را با systemd بالا می‌آورد. در پایان، کاربر ادمین را بسازید:

</div>

```bash
smite admin create
```

<div dir="rtl">

### گام ۴ — نصب نودها (سرورهای آفلاین)

روی هر سرور نود (ایران یا خارج)، همان باندل را extract کنید و اجرا کنید:

</div>

```bash
tar -xzf smite-offline-amd64-*.tar.gz
cd smite-offline-amd64
sudo bash scripts/install-node-native.sh
```

<div dir="rtl">

اسکریپت نصب، نام نود، نقش (`iran`/`foreign`)، آدرس پنل و گواهی CA را می‌پرسد و سپس سرویس `smite-node` را با تمام دسترسی‌های لازم برای تانل‌ها (`NET_ADMIN` ،`NET_RAW` ،`/dev/net/tun` — برای سوکت‌های خام udp2raw ضروری است) راه‌اندازی می‌کند.

### مدیریت نصب بومی

ابزارهای `smite` و `smite-node` به‌صورت خودکار تشخیص می‌دهند که نصب بومی (systemd) است و دستورها را مطابق آن اجرا می‌کنند:

</div>

```bash
smite status / restart / logs / edit-env      # از systemctl + journalctl استفاده می‌کند
smite-node status / restart / logs / edit-env
```

<div dir="rtl">

سرویس‌ها را مستقیم هم می‌توانید مدیریت کنید:

</div>

```bash
systemctl status smite-panel    # یا smite-node
journalctl -u smite-panel -f
```

<div dir="rtl">

### بروزرسانی نصب آفلاین

یک باندل تازه را روی ماشین دارای اینترنت بسازید (یا از Releases دانلود کنید)، به سرور منتقل کنید، روی پوشه قبلی extract کنید و همان اسکریپت نصب را دوباره اجرا کنید — داده‌ها (`/opt/smite/panel/data`، گواهی‌ها و `.env`) حفظ می‌شوند.

---

## 🛠 ابزارهای CLI

### CLI پنل (`smite`)

**مدیریت ادمین:**

</div>

```bash
smite admin create      # ساخت کاربر ادمین
smite admin update      # تغییر رمز ادمین
```

<div dir="rtl">

**مدیریت پنل:**

</div>

```bash
smite status            # نمایش وضعیت سیستم
smite update            # بروزرسانی پنل (دریافت ایمیج‌ها و ساخت دوباره)
smite restart           # ری‌استارت پنل (اعمال تغییرات .env)
smite logs              # مشاهده لاگ‌های پنل
```

<div dir="rtl">

**پیکربندی:**

</div>

```bash
smite edit              # ویرایش docker-compose.yml
smite edit-env          # ویرایش فایل .env
```

<div dir="rtl">

### CLI نود (`smite-node`)

**مدیریت نود:**

</div>

```bash
smite-node status       # نمایش وضعیت نود
smite-node update       # بروزرسانی نود (دریافت ایمیج‌ها و ساخت دوباره)
smite-node restart      # ری‌استارت نود (اعمال تغییرات .env)
smite-node logs         # مشاهده لاگ‌های نود
```

<div dir="rtl">

**پیکربندی:**

</div>

```bash
smite-node edit         # ویرایش docker-compose.yml
smite-node edit-env     # ویرایش فایل .env
```

---

<div dir="rtl">

## 📚 مستندات و راهنماها

- **[نصب بومی آفلاین (بدون داکر)](#-نصب-بومی-آفلاین-بدون-داکر)** — دانلود باندل آماده از Releases (یا ساخت آن) و نصب پنل/نودها روی سرورهای محدودشده/ایران با `systemd` + Python `venv`.
- **[انواع تانل](#-انواع-تانل)** — GOST ،Backhaul ،Rathole ،Chisel ،FRP و نحوه کار هر کدام.
- **تانل udp2raw** — ابهام‌سازی UDP دو‌نودی (FakeTCP / ICMP / UDP) — در بخش انواع تانل.
- **[Zapret — دور زدن DPI / جعل SNI](docs/ZAPRET.md)** — راهنمای کامل (فارسی + انگلیسی): چه زمانی استفاده کنیم، استراتژی‌های desync و راه‌اندازی `xray` / `config.json` همراه آن.
- **[ابزارهای CLI](#-ابزارهای-cli)** — مدیریت پنل و نودها از خط فرمان (هم برای نصب داکری، هم بومی).

---

## 📖 انواع تانل

### تانل GOST (فوروارد از نود ایران)

- **TCP**: فوروارد ساده TCP
- **UDP**: فوروارد بسته‌های UDP
- **WebSocket (WS)**: فوروارد با پروتکل وب‌سوکت
- **gRPC**: فوروارد با پروتکل gRPC
- **TCPMux**: مالتی‌پلکس TCP برای چندین اتصال

تانل‌های GOST روی نودهای ایران اجرا می‌شوند و ترافیک را به سرورهای خارج می‌فرستند. هنگام ساخت تانل GOST هم نود ایران و هم سرور خارج را مشخص می‌کنید. نود ایران روی پورت تعیین‌شده گوش می‌دهد و تمام ترافیک را به IP و پورت سرور خارج فوروارد می‌کند.

### تانل Backhaul (تانل معکوس)

- **TCP / UDP**: تانل معکوس کم‌تاخیر با قابلیت UDP-over-TCP
- **WS / WSMux**: ترنسپورت وب‌سوکت برای استقرار پشت CDN
- **TCPMux**: پشتیبانی از مالتی‌پلکس TCP
- **تنظیمات پیشرفته**: پیکربندی mux ،keepalive ،sniffer و نگاشت پورت سفارشی برای هر تانل

پنل هنگام ساخت تانل، هر دو نود ایران و خارج را به‌صورت خودکار پیکربندی می‌کند.

### تانل Rathole (تانل معکوس)

- **TCP**: تانل معکوس استاندارد TCP
- **WebSocket (WS)**: پشتیبانی از ترنسپورت وب‌سوکت

با تانل Rathole می‌توانید سرویس‌های در حال اجرا روی شبکه نود خارج را از طریق نود ایران در دسترس قرار دهید.

### تانل Chisel (تانل معکوس)

تانل Chisel یک تانل معکوس TCP سریع است که سرویس‌های شبکه نود خارج را با کارایی بالا از طریق نود ایران در دسترس قرار می‌دهد.

### تانل FRP (تانل معکوس)

FRP (پروکسی معکوس سریع) تانل معکوس TCP/UDP پایدار ارائه می‌دهد. FRP از هر دو پروتکل TCP و UDP پشتیبانی می‌کند و به‌صورت اختیاری IPv6 را هم روی بستر IPv4 تانل می‌کند.

### تانل udp2raw (ابهام‌سازی UDP — دو نود)

- **FakeTCP**: ترافیک UDP را داخل بسته‌های خامی که شبیه TCP هستند می‌پیچد — مسدودسازی/محدودیت QoS روی UDP در اکثر ISPها را دور می‌زند
- **ICMP**: ترافیک UDP را داخل بسته‌های ICMP (پینگ) می‌پیچد
- **UDP**: حالت UDP ساده همراه با رمزنگاری و anti-replay خود udp2raw

تانل udp2raw روی هر دو نود اجرا می‌شود: **نود ایران** کلاینت udp2raw را اجرا می‌کند و یک پورت UDP عمومی باز می‌کند (کاربران به همین‌جا وصل می‌شوند) و **نود خارج** سرور udp2raw را اجرا می‌کند که ترافیک را باز کرده و به سرویس UDP مقصد (مثل WireGuard ،Hysteria ،OpenVPN) تحویل می‌دهد. ترافیک بین دو نود رمزنگاری‌شده (به‌صورت پیش‌فرض AES-128-CBC) و احرازهویت‌شده است. کلید مشترک، پورت raw و قوانین iptables همگی به‌صورت خودکار توسط پنل مدیریت می‌شوند.

> **نکته**: udp2raw از سوکت خام (raw socket) استفاده می‌کند، بنابراین هر دو نود به دسترسی‌های `NET_RAW`/`NET_ADMIN` نیاز دارند — این دسترسی‌ها هم در نصب داکری و هم در نصب بومی (systemd) از قبل تنظیم شده‌اند.

### Zapret (دور زدن DPI / جعل SNI — تک نود)

برخلاف هسته‌های بالا، **zapret تانل نیست** — ترافیکی بین دو نود جابه‌جا نمی‌کند. zapret پردازشگر بسته `nfqws` را روی **یک نود** اجرا می‌کند و هندشیک TLS را به‌هم می‌ریزد (جعل SNI، ارسال ClientHello تقلبی و...) تا سیستم‌های DPI که بر اساس SNI فیلتر می‌کنند، نتوانند ترافیک واقعی شما روی پورت ۴۴۳ را تشخیص دهند.

آن را روی سروری فعال کنید که **اتصال TLS خروجی را برقرار می‌کند** — معمولاً سرور خارج/رله‌ای که یک پروکسی Xray VLESS دارد و خروجی آن یک اتصال TLS+WebSocket با domain fronting روی پورت ۴۴۳ است. Smite پروسه `nfqws` و قوانین NFQUEUE در iptables را برای هر تانل به‌صورت جدا مدیریت می‌کند (هیچ flush سراسری انجام نمی‌شود؛ بنابراین با udp2raw و بقیه هسته‌ها بدون تداخل کار می‌کند).

- **حالت‌های desync**: ‏`fake` ،`fakedsplit` ،`multisplit` ،`multidisorder` ،`disorder2` ،`split2` ،`syndata`
- **قابل تنظیم**: پورت‌های فیلتر (پیش‌فرض `443`)، فیلتر L7 (‏`tls`)، SNI جعلی (مثل `hcaptcha.com`)، روش fooling (‏`badseq,ts`)، جهت ترافیک، شماره صف و **IP مقصد (اختیاری)** برای محدودکردن دی‌سینک به یک مقصد خاص
- **نیازمندی‌ها**: ‏`NET_ADMIN` + `NET_RAW` و باینری `nfqws` (هم در ایمیج داکر و هم در باندل آفلاین موجود است)

راهنمای کامل — شامل راه‌اندازی `xray` / `config.json` همراه آن و این‌که کدام استراتژی desync را کجا استفاده کنید — در **[docs/ZAPRET.md](docs/ZAPRET.md)** آمده است.

### SNI Spoof (فرانت‌پروکسی Xray + Zapret — تک نود)

هسته `snispoof` نسخه کاملاً خودکار سناریوی بالا است: با یک تانل، Smite روی نود انتخابی یک **فرانت‌پروکسی Xray** (اینباند VLESS/TCP روی `127.0.0.1:<پورت محلی>` + اوتباند VLESS روی WS+TLS به IP/دامنه فرانت با SNI واقعی بک‌اند) اجرا می‌کند و همزمان **zapret/nfqws** را روی پورت فرانت فعال می‌کند تا DPI به‌جای SNI واقعی، دامنه بدلی ببیند. کافی است اوتباند پنل پروکسی خود (مثل سنایی) را به `127.0.0.1:<پورت محلی>` با UUID تولیدشده وصل کنید. فرم پنل از لینک `vless://` هم به‌صورت خودکار پر می‌شود. (جزئیات در [docs/ZAPRET.md](docs/ZAPRET.md))

---

## 📝 لایسنس

این پروژه تحت لایسنس MIT منتشر شده است — جزئیات در فایل [LICENSE](LICENSE).

---

## 💰 حمایت مالی

اگر Smite برایتان مفید بود و می‌خواهید از توسعه آن حمایت کنید:

### حمایت با ارز دیجیتال

- **Bitcoin (BTC)**: `bc1q637gahjssmv9g3903j88tn6uyy0w2pwuvsp5k0`
- **Ethereum (ETH)**: `0x5B2eE8970E3B233F79D8c765E75f0705278098a0`
- **Tron (TRX)**: `TSAsosG9oHMAjAr3JxPQStj32uAgAUmMp3`
- **USDT (BEP20)**: `0x5B2eE8970E3B233F79D8c765E75f0705278098a0`
- **TON**: `UQA-95WAUn_8pig7rsA9mqnuM5juEswKONSlu-jkbUBUhku6`

### راه‌های دیگر حمایت

- ⭐ اگر پروژه مفید بود، به مخزن ستاره بدهید
- 🐛 باگ‌ها را گزارش کنید و پیشنهاد بهبود بدهید
- 📖 در بهبود مستندات و ترجمه‌ها مشارکت کنید
- 🔗 پروژه را با دیگران به اشتراک بگذارید

</div>

---

<div align="center">
  
  **Originally made with ❤️ by [zZedix](https://github.com/zZedix)** · This fork (offline install, udp2raw, zapret) maintained by [lokidv](https://github.com/lokidv)
  
  *Securing the digital world, one line of code at a time!*
  
</div>
