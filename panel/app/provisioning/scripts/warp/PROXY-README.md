# نسخهٔ Proxy — خروجیِ ترافیک از پروکسیِ بالادست (residential / SOCKS / HTTP)

این یک **کپیِ جداگانه** از نصب‌کنندهٔ WireGuard است (نسخهٔ اصلی دست‌نخورده باقی مانده).
تفاوتش: بعد از نصبِ WireGuard، ترافیکِ TCPِ کلاینت‌ها را از یک پروکسیِ بالادست خارج
می‌کند تا **IP خروجیِ کاربر = IP پروکسی** شود (نه IP سرور).

## چطور کار می‌کند
- روی همین سرور یک `redsocks` (transparent redirector) نصب می‌شود.
- ترافیکِ TCP که از `wg0` فوروارد می‌شود، در `iptables nat/PREROUTING` به redsocks
  محلی (`127.0.0.1:12345`) REDIRECT می‌شود و redsocks آن را با user/pass به پروکسیِ
  بالادست تحویل می‌دهد.
- برای جلوگیری از دورزدنِ پروکسی توسط QUIC، `UDP/443` بسته می‌شود تا مرورگر به TCP برگردد.
- قوانین در `PostUp/PostDown` فایلِ `wg0.conf` درج می‌شوند → پس از ریبوت هم پایدارند.

> نکته: این روش برای ترافیکِ **TCP** (وب/HTTPS) است — که همان چیزی است که «IP پروکسی را
> نشان بده» به آن نیاز دارد. residential proxyها معمولاً SOCKS5/HTTP و فقط TCP هستند.
> DNS از NAT سرور می‌رود (نشتِ IP خروجی ندارد؛ اتصالِ واقعی از پروکسی است).

## پیکربندی
`wvpn/proxy.env.example` را ببینید. روی سرور:
```bash
sudo cp wvpn/proxy.env.example /etc/wvpn-proxy.env
sudo nano /etc/wvpn-proxy.env      # PROXY_PORT و PROXY_TYPE را پر کنید
sudo chmod 600 /etc/wvpn-proxy.env
```
مقادیر لازم: `PROXY_IP`, `PROXY_PORT`, `PROXY_TYPE` (socks5 یا http-connect),
`PROXY_USER`, `PROXY_PASS`.

## نصب
### الف) نصبِ کامل (WireGuard + پروکسی، خودکار)
اگر `/etc/wvpn-proxy.env` موجود باشد، نصب‌کننده در پایان خودکار پروکسی را راه می‌اندازد:
```bash
sudo ./install.sh
```

### ب) فقط افزودنِ پروکسی به سروری که WireGuard از قبل نصب است
```bash
sudo PROXY_IP=198.3.27.9 PROXY_PORT=<port> PROXY_TYPE=socks5 \
     PROXY_USER=14aee205b79db PROXY_PASS=03200cfd09 \
     bash wvpn/proxy-egress.sh
```
یا با فایلِ `/etc/wvpn-proxy.env`:
```bash
sudo bash wvpn/proxy-egress.sh
```

## بررسی
- روی سرور: `systemctl status wvpn-redsocks`
- IP خروجی از داخلِ کلاینتِ WireGuard: `curl https://api.ipify.org` → باید IP پروکسی باشد.
- اسکریپت خودش هم در پایان یک تستِ IP خروجیِ پروکسی چاپ می‌کند.

## بازگردانی (حذف پروکسی)
```bash
sudo /usr/local/bin/wvpn-proxy-rules.sh down
sudo systemctl disable --now wvpn-redsocks
# و خطوطِ PostUp/PostDown مربوط به wvpn-proxy-rules را از /etc/wireguard/wg0.conf بردارید
```
