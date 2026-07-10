# OVPN Installer — پنل مدیریت OpenVPN (حجم + تاریخ انقضا + API)

این پروژه معادلِ OpenVPN نسخه‌ی پروژه‌ی «wginstaller» است. یعنی نصب خودکار
OpenVPN + تمام پیش‌نیازها + یک **پنل ادمین و API** برای مدیریت کاربران با
**حجم (Data Limit)**، **تاریخ انقضای خودکار**، فعال/غیرفعال‌سازی، QR کد و
اعمال خودکار محدودیت‌ها (Enforce).

اسکریپت پایه‌ی OpenVPN از [angristan/openvpn-install](https://github.com/angristan/openvpn-install)
گرفته شده و یک لایه‌ی مدیریت (`ovpn-manager.sh`) + پنل Node.js روی آن نشسته است.

---

## نصب با یک دستور

روی یک سرور **Ubuntu/Debian خام** (حتی بدون Node.js و OpenVPN)، با root:

```bash
sudo ./install.sh
```

یا از راه‌دور (بعد از آپلود به سرور):

```bash
curl -fsSL https://raw.githubusercontent.com/<you>/ovpn-installer/main/install.sh | sudo bash
```

نصب **کاملاً خودکار و بدون پرسش** است. همه‌ی پیش‌نیازها به‌صورت خودکار نصب می‌شوند:
`openvpn`، `easy-rsa`، `qrencode`، `jq`، `socat`، `iptables` و **Node.js 20**.

بعد از نصب، آدرس پنل، رمز ادمین و API Key چاپ و در `/root/ovpn-install-info.txt`
ذخیره می‌شود.

### متغیرهای محیطی (اختیاری)

| متغیر | پیش‌فرض | توضیح |
|------|---------|-------|
| `OVPN_PORT` | `4000` | پورت پنل/API |
| `OVPN_VPN_PORT` | `1194` | پورت OpenVPN |
| `OVPN_PROTOCOL` | `udp` | `udp` یا `tcp` |
| `OVPN_DNS1` / `OVPN_DNS2` | `1.1.1.1` / `1.0.0.1` | DNS کلاینت‌ها |
| `OVPN_ENDPOINT` | IP سرور | Remote کلاینت (برای NAT) |
| `OVPN_DEFAULT_LIMIT_GB` | نامحدود | حجم پیش‌فرض کاربران جدید |
| `OVPN_TEST_CLIENT` | — | ساخت یک کاربر تستی بعد از نصب |
| `OVPN_NONINTERACTIVE` | `1` | `0` برای حالت تعاملی |

مثال:

```bash
sudo OVPN_VPN_PORT=443 OVPN_PROTOCOL=tcp OVPN_DEFAULT_LIMIT_GB=30 \
     OVPN_TEST_CLIENT=alice ./install.sh
```

---

## امکانات (دقیقاً مشابه نسخه‌ی WireGuard)

- ✅ **نصب خودکار** OpenVPN + Easy-RSA + تمام پیش‌نیازها
- ✅ **پنل ادمین** (HTML، RTL، فارسی) با ورود رمزدار، CSRF، Rate-Limit و IP Allowlist
- ✅ **API عمومی** با API Key برای اتصال سایت/ربات
- ✅ **مدیریت حجم**: تعیین سقف مصرف به GB، خرید/افزایش حجم، تنظیم مطلق سقف
- ✅ **تاریخ انقضای خودکار**: تعیین به روز، تمدید، تاریخ دقیق، یا نامحدود
- ✅ **اعمال خودکار (Enforce)** هر ۳۰ ثانیه (پنل) + هر ۱ دقیقه (کرون پشتیبان): قطع کاربرِ منقضی یا پُر-volume
- ✅ **غیرفعال/فعال** قابل‌معکوس (بدون ابطال گواهی، با `client-config-dir`)
- ✅ **حسابداری ترافیک** دقیق بر اساس `client-disconnect` + وضعیت زنده‌ی OpenVPN
- ✅ **QR کد** و دانلود فایل `.ovpn` برای هر کاربر
- ✅ فیلتر/جستجوی پیشرفته‌ی لیست کاربران (وضعیت، انقضا، مصرف، سقف، ...)

---

## API (با API Key)

همه‌ی روت‌های عمومی با هدر `X-API-Key` (یا `?apiKey=`) کار می‌کنند:

```bash
KEY="..."            # از /root/ovpn-install-info.txt

# ساخت کاربر (خروجی: محتوای فایل .ovpn)
curl -s "http://SERVER:4000/create?apiKey=$KEY&name=alice&dataLimitGB=30&expiresInDays=60"

# اطلاعات یک کاربر
curl -s "http://SERVER:4000/info?apiKey=$KEY&name=alice"

# افزایش حجم و تمدید
curl -s "http://SERVER:4000/update?apiKey=$KEY&name=alice&addDataGB=10&extendDays=30"

# غیرفعال / فعال / حذف
curl -s "http://SERVER:4000/disable?apiKey=$KEY&name=alice&reason=manual"
curl -s "http://SERVER:4000/enable?apiKey=$KEY&name=alice"
curl -s "http://SERVER:4000/remove?apiKey=$KEY&name=alice"

# لیست کاربران (با فیلتر)
curl -s "http://SERVER:4000/list?apiKey=$KEY&status=active&sort=usedBytes&order=desc"
```

پارامترهای حجم/انقضا چند نام پشتیبانی می‌کنند (مثل `volume`، `data_limit_gb`،
`volumeBytes` و ...).

---

## ساختار پروژه

```
ovpn-installer/
├── install.sh                     # نصب‌کننده‌ی ریشه (خودکار)
├── openvpn-install/
│   └── openvpn-install.sh         # پایه‌ی angristan (PKI / سرور)
├── tests/
│   └── test_enforce_jq.sh         # تست رگرسیون منطق enforce
└── ovpn/                          # پنل + مدیر
    ├── install.sh                 # bootstrap نصب
    ├── main.js                    # سرور HTTP و مسیریابی
    ├── admin.html                 # پنل ادمین
    ├── ovpn-manager.sh            # لایه‌ی مدیریت (JSON subcommands + volume + enforce)
    ├── ovpn-connect.sh            # رد کلاینت غیرمجاز در زمان اتصال
    ├── ovpn-disconnect.sh         # ثبت مصرف هر سشن
    ├── package.json
    ├── lib/  (config, security, http-utils, ovpn-service, volume-params, client-filters)
    └── scripts/init-config.js
```

### نحوه‌ی کار

- پنل Node (`main.js`) فرمان‌ها را به `ovpn-manager.sh` می‌دهد و خروجی JSON می‌گیرد.
- `ovpn-manager.sh` برای PKI از `openvpn-install.sh` استفاده می‌کند و وضعیت هر
  کاربر را در `/etc/openvpn/ovpn-manager/state.json` نگه می‌دارد.
- **حسابداری حجم**: هر قطع اتصال، بایت‌های سشن را در `usage-events.log` ثبت
  می‌کند و `enforce` آن‌ها را در `state.usedBytes` جمع می‌کند؛ مصرف زنده‌ی
  سشن جاری هم از `status.log` خوانده می‌شود.
- **Enforce**: کاربر منقضی یا پُر-volume با مکانیزم بومی `ccd` مسدود و در صورت
  اتصالِ زنده، از طریق management socket قطع می‌شود. اگر مصرف یک کاربر به‌دلیل
  هم‌پوشانیِ لحظه‌ایِ رویداد قطع با `status.log` یک‌بار بیشتر از حد محاسبه شود،
  enforce در سیکل بعد به‌محض پایین‌آمدن مصرفِ واقعی به زیر سقف، خودکار کاربر را
  دوباره فعال می‌کند (به‌شرط اینکه واقعاً پُر-volume نباشد).

---

## نکات و محدودیت‌ها

- **QR Code**: کانفیگِ inline مربوط به OpenVPN (شامل ca/cert/key/tls-crypt-v2،
  حدود ۳ کیلوبایت) از ظرفیت QR نسخهٔ ۴۰ بزرگ‌تر است؛ بنابراین QR تقریباً همیشه
  ممکن نیست. پنل به‌جای شکست، پیام «از دانلود `.ovpn` استفاده کنید» نشان می‌دهد.
  دکمهٔ دانلود همیشه کار می‌کند.
- **اعمال تنظیمات DNS**: تغییر DNS در پنل، یک‌بار OpenVPN را ری‌استارت می‌کند
  (پوشش DNS جدید به کلاینت‌ها). این ری‌استارت اتصالِ کلاینت‌های فعلی را قطع
  می‌کند و آن‌ها باید دوباره وصل شوند.

---

## تست

یک تست رگرسیون برای منطق enforce (سهمیه/انقضا و خود‌ترمیمی) در `tests/` قرار دارد:

```bash
bash tests/test_enforce_jq.sh        # نیازمند jq روی مسیر
```

روی سرور، می‌توان مسیرها را مستقیم هم بررسی کرد:

```bash
/home/ovpn/ovpn-manager.sh list                       # لیست و حالت کاربران
/home/ovpn/ovpn-manager.sh enforce                     # اجرای دستی enforce
```

---

## دستورات مفید روی سرور

```bash
systemctl status ovpn.service                # وضعیت پنل
systemctl status openvpn-server@server       # وضعیت OpenVPN
journalctl -u ovpn.service -f                # لاگ پنل
tail -f /home/ovpn/ovpn.log
cat /root/ovpn-install-info.txt              # اطلاعات دسترسی

# تست مستقیم مدیر
/home/ovpn/ovpn-manager.sh list
/home/ovpn/ovpn-manager.sh enforce
```
