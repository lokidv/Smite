# Zapret (DPI Bypass / SNI Spoofing) — راهنمای کامل

> **خلاصه:** zapret یک «تونل» نیست. این روش با اجرای پردازشگر بسته `nfqws` روی **یک سرور**، دست‌دادن TLS را دی‌سینک (desync) می‌کند تا سیستم‌های DPI که بر اساس **SNI** فیلتر می‌کنند نتوانند ترافیک واقعی پورت `443` شما را تشخیص داده و ببندند. در Smite این روش به‌صورت یک «هسته» تک‌نودی به نام `zapret` اضافه شده و خود پنل، پراسس `nfqws` و قوانین NFQUEUE مربوط به iptables را مدیریت می‌کند.

---

## ۱) zapret چیست و برای چه حالت‌هایی مناسب است؟

سیستم‌های فیلترینگ مدرن (DPI) اغلب با خواندن فیلد **SNI** در پیام `ClientHello` پروتکل TLS تشخیص می‌دهند که به چه دامنه‌ای وصل می‌شوید و سپس اتصال را با ارسال RST یا drop می‌بندند. `nfqws` (بخشی از پروژهٔ [zapret](https://github.com/bol-van/zapret)) با تکنیک‌های زیر این تشخیص را خراب می‌کند:

- ارسال یک `ClientHello` **جعلی** با SNI بی‌خطر (مثلاً `hcaptcha.com`) قبل از بستهٔ واقعی، طوری که DPI گمراه شود ولی سرور مقصد آن را نادیده بگیرد (`--dpi-desync=fake`).
- تکه‌تکه‌کردن / به‌هم‌ریختن ترتیب بسته‌ها (`split`, `disorder`, ...).
- «گول‌زدن» DPI با دستکاری `seq`/`ttl`/`checksum` (`--dpi-desync-fooling`).

**مناسب برای این سناریوها:**

- شما یک سرور خارجی دارید که روی آن یک پروکسی (مثل **Xray/VLESS**) با خروجیِ **TLS+WebSocket روی پورت ۴۴۳** و **دامین‌فرانتینگ** (مثلاً به IP کلودفلر `104.19.229.21`) اجرا می‌شود، و این اتصال خروجی به‌خاطر فیلترینگ SNI بسته می‌شود.
- می‌خواهید بدون عوض‌کردن کل ساختار، فقط همان اتصال `443` را «نامرئی» کنید تا پایدار بماند.
- روی همان سروری که اتصالِ TLS را **باز می‌کند** اجرا می‌شود (سمت خروجی).

**برای این حالت‌ها مناسب نیست:**

- جابه‌جایی ترافیک بین نود ایران و خارج (برای آن از تونل‌ها استفاده کنید: GOST/Rathole/Backhaul/Chisel/FRP/udp2raw).
- جایی که مشکل، بلاک‌شدن کل IP باشد (zapret فقط فیلترینگ مبتنی بر محتوا/SNI را دور می‌زند، نه بلاک IP را).

---

## ۲) پیش‌نیازها

- نود باید با Smite ثبت شده باشد (نصب Docker یا نصب بومی).
- قابلیت‌های `NET_ADMIN` و `NET_RAW` (در ایمیج Docker و یونیت systemd از قبل تنظیم شده‌اند).
- باینری `nfqws` روی نود موجود باشد:
  - در نصب Docker: داخل ایمیج نود از قبل کپی شده است.
  - در نصب بومی آفلاین: داخل باندل قرار دارد و در `/usr/local/bin/nfqws` نصب می‌شود.
- ماژول‌های کرنل `nfnetlink_queue` و `xt_connbytes` (روی اکثر توزیع‌ها به‌صورت پیش‌فرض موجودند).

> **نکتهٔ مهم:** zapret در Smite **هرگز** کل iptables را `flush` نمی‌کند. برخلاف اسکریپت‌های دستی رایج، Smite قوانین را در چِین‌های اختصاصی per-tunnel (مثل `smite_zap_<hash>_o`) می‌سازد و موقع حذف، فقط همان‌ها را پاک می‌کند. به همین دلیل با تونل‌های دیگر (مثل udp2raw) روی همان سرور تداخل ندارد.

---

## ۳) روش پیشنهادی: از طریق پنل Smite

1. به صفحهٔ **Tunnels** بروید و **Create Tunnel** را بزنید.
2. در فیلد **Core**، گزینهٔ **Zapret (DPI bypass)** را انتخاب کنید.
3. در **Node**، سروری را انتخاب کنید که اتصال TLS خروجی روی آن باز می‌شود (معمولاً سرور خارجی/پروکسی). فهرست شامل همهٔ نودهای ایران و خارج است.
4. فیلدها را تنظیم کنید (پیش‌فرض‌ها برای SNI spoofing مناسب‌اند):

| فیلد | پیش‌فرض | توضیح |
|------|---------|-------|
| **Desync Mode** | `fake` | استراتژی nfqws (`--dpi-desync`). ابتدا `fake` را امتحان کنید. |
| **Filter Ports (TCP)** | `443` | پورت‌هایی که باید دی‌سینک شوند. می‌تواند `443` یا `443,8443` باشد. |
| **L7 Filter** | `tls` | لایهٔ پروتکل (`--filter-l7`). برای HTTPS/SNI همان `tls`. |
| **Fake TLS SNI** | `hcaptcha.com` | SNI بی‌خطری که در ClientHello جعلی فرستاده می‌شود. یک دامنهٔ مجاز بگذارید. |
| **Fooling** | `badseq,ts` | روش گول‌زدن DPI (`--dpi-desync-fooling`). مقادیر دیگر: `md5sig`, `badsum`, `datanoack`. |
| **Direction** | `both` | روی ترافیک خروجی (`out`)، ورودی (`in`) یا هر دو اعمال شود. برای سرورِ خروجیِ TLS، `both` توصیه می‌شود. |
| **Target IP** | — | (اختیاری) اگر پر شود، دی‌سینک فقط روی همین IP مقصد اعمال می‌شود (`-d <ip>` در خروجی و `-s <ip>` در ورودی). مناسب وقتی فقط اتصال به یک IP فرانت/CDN خاص باید دی‌سینک شود و بقیهٔ ترافیک ۴۴۳ سرور دست‌نخورده بماند. |
| **NFQUEUE Number** | خودکار | اگر خالی بگذارید، یک شمارهٔ صف یکتا برای هر تونل انتخاب می‌شود. |
| **Extra nfqws Args** | — | فلگ‌های خام اضافی (پیشرفته)، مثل `--dpi-desync-ttl=5`. |

5. **Create** را بزنید. Smite قوانین NFQUEUE را روی نود نصب و `nfqws` را با همان استراتژی اجرا می‌کند. وضعیت تونل باید **active** شود.

ویرایش/حذف از همان صفحه انجام می‌شود؛ حذف، هم پراسس `nfqws` و هم قوانین iptables را به‌طور تمیز برمی‌دارد. در بخش **Core Health** هم می‌توانید هستهٔ `zapret` را ری‌ست کنید.

---

## ۴) سناریوی کامل: zapret + Xray (VLESS روی سرور خارجی)

zapret فقط لایهٔ DPI را دور می‌زند؛ خودِ پروکسی را شما جدا راه می‌اندازید. سناریوی متداول:

- کاربران به **inbound VLESS** روی سرور خارجی وصل می‌شوند.
- خروجیِ سرور یک اتصال **WS + TLS روی پورت ۴۴۳** با **دامین‌فرانتینگ** به IP کلودفلر (مثل `104.19.229.21`) است.
- zapret روی همان سرور اجرا می‌شود تا اتصالِ خروجیِ ۴۴۳ به‌خاطر SNI بسته نشود.

### ۴.۱) نصب باینری xray (در صورت نیاز)

```bash
# باینری xray (نمونه؛ از منبع مورد اعتماد خودتان دانلود کنید)
mv xray /usr/local/bin/xray
chmod +x /usr/local/bin/xray
```

### ۴.۲) فایل `/root/config.json` (نمونه)

> مقادیر `UUID`، دامنهٔ فرانت و `path` را با مقادیر واقعی خود جایگزین کنید.

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "vless-in",
      "listen": "0.0.0.0",
      "port": 8443,
      "protocol": "vless",
      "settings": {
        "clients": [{ "id": "PUT-YOUR-UUID-HERE" }],
        "decryption": "none"
      },
      "streamSettings": { "network": "tcp" }
    }
  ],
  "outbounds": [
    {
      "tag": "front-out",
      "protocol": "vless",
      "settings": {
        "vnext": [
          {
            "address": "104.19.229.21",
            "port": 443,
            "users": [{ "id": "PUT-YOUR-UUID-HERE", "encryption": "none" }]
          }
        ]
      },
      "streamSettings": {
        "network": "ws",
        "security": "tls",
        "tlsSettings": {
          "serverName": "your-fronting-domain.com",
          "allowInsecure": false
        },
        "wsSettings": {
          "path": "/your-path",
          "headers": { "Host": "your-fronting-domain.com" }
        }
      }
    }
  ]
}
```

### ۴.۳) سرویس xray

```ini
# /etc/systemd/system/config.service
[Service]
ExecStart=/usr/local/bin/xray -c /root/config.json
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now config
```

### ۴.۴) فعال‌کردن zapret

zapret را از پنل Smite بسازید (بخش ۳). با این کار دیگر **نیازی به ساختن دستی `zapret.service`، ویرایش `rc.local` یا `iptables-save` ندارید** — همهٔ این‌ها را Smite مدیریت می‌کند و موقع حذف هم تمیز می‌شوند.

> **نکته:** اگر نمی‌خواهید `config.json` و سرویس xray را دستی بسازید، از هستهٔ **SNI Spoof** (بخش ۵) استفاده کنید که کل همین سناریو را خودکار انجام می‌دهد.

---

## ۵) هستهٔ SNI Spoof (snispoof) — فرانت‌پروکسی مدیریت‌شده

هستهٔ `snispoof` کل سناریوی بخش ۴ را به‌صورت یک تونل تک‌نودی مدیریت‌شده انجام می‌دهد. با ساختن آن، Smite روی نود انتخابی:

1. یک **فرانت‌پروکسی Xray** اجرا می‌کند: اینباند VLESS/TCP روی `127.0.0.1:<پورت محلی>` + اوتباند VLESS روی **WS+TLS** به آدرس فرانت (IP لبهٔ CDN مثل `104.19.229.21` یا دامنه) با SNI/Host واقعی بک‌اند. فایل کانفیگ به‌صورت خودکار در `/etc/smite-node/snispoof/<tunnel_id>.json` ساخته می‌شود.
2. همزمان **zapret/nfqws** را روی پورت فرانت (معمولاً ۴۴۳) اجرا می‌کند تا DPI به‌جای SNI واقعی، دامنهٔ بدلی (مثل `hcaptcha.com`) ببیند. اگر آدرس فرانت یک IP باشد، قوانین NFQUEUE به‌طور خودکار فقط به همان IP محدود می‌شوند.

### ۵.۱) ساخت از پنل

1. **Tunnels → Create Tunnel → Core: SNI Spoof (Xray + Zapret)** را انتخاب کنید.
2. نودی را انتخاب کنید که قرار است فرانت‌پروکسی روی آن اجرا شود (معمولاً سرور ایران که اوتباند سنایی روی آن است).
3. اگر لینک `vless://` بک‌اند WS/TLS را دارید، آن را در فیلد «پر کردن از لینک vless://» بچسبانید و **پر کن** را بزنید تا فیلدها خودکار پر شوند.

| فیلد | پیش‌فرض | توضیح |
|------|---------|-------|
| **Local Port** | `18443` | پورت اینباند VLESS محلی روی `127.0.0.1` که پنل پروکسی (سنایی و …) به آن وصل می‌شود. |
| **Inbound UUID** | خودکار | UUID اتصال به اینباند محلی؛ خودکار ساخته می‌شود و در ویرایش‌ها ثابت می‌ماند. |
| **Front IP / Address** | — | IP لبهٔ CDN (مثل `104.19.229.21`) یا دامنه‌ای که اوتباند به آن وصل می‌شود. |
| **Front Port** | `443` | پورت اتصال فرانت. |
| **Backend UUID** | — | UUID کاربر VLESS در بک‌اند WS/TLS شما. |
| **SNI / Host Domain** | — | دامنهٔ واقعی بک‌اند (هم SNI در TLS و هم هدر Host وب‌سوکت)، مثل `zprt.example.com`. |
| **WebSocket Path** | `/` | مسیر WS بک‌اند، مثل `/admin`. |
| **ALPN / Fingerprint** | `h2,http/1.1` / `chrome` | تنظیمات TLS اوتباند (اختیاری). |
| **Desync Mode / Fake TLS SNI / Fooling** | `fake` / `hcaptcha.com` / `badseq,ts` | همان تنظیمات zapret که روی پورت فرانت اعمال می‌شوند؛ دامنهٔ بدلی قابل ویرایش است. |

4. **Create** را بزنید. وضعیت باید **active** شود (هم پراسس xray و هم nfqws بالا می‌آیند).

### ۵.۲) اتصال پنل پروکسی (سنایی) به آن

در پنل سنایی یک **اوتباند VLESS** بسازید با:

```json
{
  "protocol": "vless",
  "settings": {
    "address": "127.0.0.1",
    "port": 18443,
    "id": "<Inbound UUID از فرم Smite>",
    "encryption": "none"
  },
  "streamSettings": { "network": "tcp", "security": "none" }
}
```

> `flow` نگذارید و security را `none` بگذارید — اینباند محلی TLS ندارد (ترافیک از همان سرور عبور می‌کند و TLS در اوتباند فرانت انجام می‌شود).

> **اشتباه رایج:** اینباند محلی **VLESS ساده روی TCP بدون TLS/WebSocket** است. تنظیمات WS/TLS و UUID بک‌اند (همان‌هایی که در فرم Smite برای فرانت وارد کرده‌اید) را در اوتباند سنایی **تکرار نکنید**؛ آن‌ها فقط سمت سرور لازم‌اند. اگر در سنایی Transmission را WebSocket یا Security را TLS بگذارید یا UUID بک‌اند را بزنید، خطای `invalid request version` می‌گیرید و وصل نمی‌شود. حتماً از **Inbound UUID** و `type=tcp` و `security=none` استفاده کنید. کادر «Client outbound» در فرم همین مقادیر درست را آماده و قابل‌کپی نشان می‌دهد.

### ۵.۳) تست اتصال و تنظیم خودکار (Auto-tune)

در فرم ویرایش یک تونل `snispoof` دو دکمه هست:

- **تست کن (Test):** زنجیرهٔ کامل (سنایی → اینباند محلی → اوتباند فرانت → بک‌اند) را دقیقاً مثل یک کلاینت تست می‌کند و می‌گوید وصل می‌شود یا نه و تأخیرش چقدر است.
- **تنظیم خودکار (Auto-tune):** همهٔ روش‌های دی‌سینک (`fake`, `fakedsplit`, `multidisorder`, `syndata`, …) را با fooling‌های مختلف (`badseq`, `badseq,ts`, `datanoack`, `md5sig`) روی همان تونل زنده امتحان می‌کند، نتیجهٔ هرکدام (موفق/ناموفق + تأخیر) را در یک جدول نشان می‌دهد، **بهترین حالت کارا را خودکار اعمال و ذخیره می‌کند**، و در پایان اوتباند آمادهٔ سنایی را می‌دهد. این کار روی نود انجام می‌شود و ممکن است ۱ تا ۳ دقیقه طول بکشد.

اگر تنظیم خودکار بگوید «حتی بدون دی‌سینک وصل می‌شود»، یعنی IP فرانت شما SNI-فیلتر نیست و zapret اینجا اختیاری است.

### ۵.۴) بررسی صحت کار

```bash
# هر دو پراسس باید بالا باشند
pgrep -a xray
pgrep -a nfqws

# SNI بدلی باید در ترافیک خروجی دیده شود (نه دامنهٔ واقعی)
tcpdump -i any -n -A 'tcp port 443' | grep -aiE 'hcaptcha|your-real-domain'

# لاگ‌ها
cat /etc/smite-node/snispoof/<tunnel_id>.log   # xray
cat /etc/smite-node/zapret/<tunnel_id>.log     # nfqws
```

---

## ۶) کدام Desync Mode را انتخاب کنم؟

DPIها فرق دارند؛ بهترین استراتژی را با آزمون پیدا کنید (از بالا به پایین امتحان کنید):

| Mode | کِی مناسب است |
|------|----------------|
| `fake` | شروع پیش‌فرض. ClientHello جعلی با SNI بی‌خطر. معمولاً برای SNI spoofing کافی است. |
| `fakedsplit` | fake + تکه‌کردن بستهٔ واقعی؛ وقتی `fake` تنها کافی نیست. |
| `multisplit` | تکه‌کردن چندنقطه‌ای ClientHello؛ مناسب DPIهای حساس به موقعیت SNI. |
| `multidisorder` | مثل multisplit ولی با ارسال بی‌ترتیب بسته‌ها. |
| `disorder2` / `split2` | روش‌های کلاسیک به‌هم‌ریختن/تکه‌کردن؛ روی برخی شبکه‌ها بهتر جواب می‌دهند. |
| `syndata` | تزریق دیتای جعلی در بستهٔ SYN؛ حالت خاص. |

برای **Fooling** هم اگر `badseq,ts` جواب نداد، `md5sig`، `badsum` یا ترکیب‌ها را امتحان کنید. اگر دیدید اتصال‌های مشروعِ دیگرِ سرور خراب می‌شود، `Direction` را روی `out` بگذارید.

> ابزار رسمی `blockcheck.sh` در ریپوی zapret می‌تواند بهترین استراتژی را برای شبکهٔ شما پیدا کند؛ سپس همان مقادیر را در فرم Smite وارد کنید.

---

## ۷) عیب‌یابی

- **تونل error شد:** لاگ نود را ببینید (`smite-node logs` یا `journalctl -u smite-node`). معمول‌ترین علت‌ها: نبودن `nfqws` در PATH، نبودن قابلیت‌های `NET_ADMIN`/`NET_RAW`، یا نبودن ماژول `nfnetlink_queue`.
- **لاگ خود nfqws:** روی نود در مسیر `/etc/smite-node/zapret/<tunnel_id>.log` قرار دارد.
- **بررسی نصب قوانین:** `iptables -t mangle -S | grep smite_zap` و `ip6tables -t mangle -S | grep smite_zap`.
- **هیچ تأثیری ندارد:** مطمئن شوید zapret روی سروری اجرا می‌شود که اتصال ۴۴۳ را **باز می‌کند**، نه روی نود ایران (مگر اینکه ایران همان نقطهٔ خروج TLS باشد). Desync Mode دیگری را امتحان کنید.
- **اتصال‌های دیگر ۴۴۳ مختل شد:** `Direction=out` و در صورت لزوم پورت فیلتر را دقیق‌تر کنید.

---

## ۸) مرجع: معادل دستی (فقط برای درک)

Smite کارهای زیر را خودکار انجام می‌دهد؛ این بخش صرفاً برای شفافیت است. **نیازی نیست این‌ها را دستی اجرا کنید** و برخلاف اسکریپت‌های رایج، Smite هرگز `iptables -F`/`-X` سراسری نمی‌زند.

برای هر تونل zapret، Smite در جدول `mangle`:

- چِین‌های اختصاصی `smite_zap_<hash>_o` (POSTROUTING) و `smite_zap_<hash>_i` (PREROUTING) می‌سازد.
- قوانینی برای `--dport/--sport 443` با `connbytes`، و پرچم‌های `fin/rst/syn,ack` اضافه می‌کند که به `NFQUEUE --queue-num <q> --queue-bypass` می‌روند.
- سپس `nfqws` را تقریباً این‌گونه اجرا می‌کند:

```bash
nfqws -q <queue> --filter-tcp=443 --filter-l7=tls \
      --dpi-desync=fake \
      --dpi-desync-fake-tls-mod=sni=hcaptcha.com \
      --dpi-desync-fooling=badseq,ts
```

موقع حذف تونل، فقط همان چِین‌ها flush/حذف و پراسس `nfqws` متوقف می‌شود.

---

## English Summary

**zapret is not a tunnel.** It runs `nfqws` on a **single node** to desync the TLS handshake (SNI spoofing / fake ClientHello) so SNI-based DPI cannot block your `:443` traffic. Run it on the host that **opens the outbound TLS connection** — e.g. a foreign server running an Xray VLESS proxy whose outbound is TLS+WS domain-fronting to a CDN IP (such as Cloudflare `104.19.229.21`).

Create it from **Tunnels → Create Tunnel → Core: Zapret**, pick the node, and tune the desync strategy (start with `fake` / `badseq,ts` / fake SNI `hcaptcha.com`). The optional **Target IP** field scopes the NFQUEUE rules to a single destination IP. Smite installs per-tunnel NFQUEUE `iptables` chains (never a global flush) and runs/stops `nfqws` for you. Requires `NET_ADMIN` + `NET_RAW`, which are pre-configured in both the Docker and native installs.

**SNI Spoof core (`snispoof`)** automates the full recipe: it generates and runs an Xray **front proxy** (local VLESS/TCP inbound on `127.0.0.1:<local port>` + a VLESS WS/TLS domain-fronting outbound to a CDN edge IP/domain with the real backend SNI/Host), and composes the zapret desync on the front port — all as one managed single-node tunnel. Point your proxy panel (e.g. Sanaei) outbound at `127.0.0.1:<local port>` with the generated inbound UUID (`security: none`, no flow). A pasted `vless://` share link can prefill the form. Configs live in `/etc/smite-node/snispoof/`, logs in `/etc/smite-node/snispoof/<tunnel_id>.log` (xray) and `/etc/smite-node/zapret/<tunnel_id>.log` (nfqws).
