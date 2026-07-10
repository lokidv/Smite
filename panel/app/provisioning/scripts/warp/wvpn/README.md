## نصب با یک دستور (بدون Docker)

روی سرور Ubuntu/Debian **خام** (حتی بدون Node.js و WireGuard)، با root:

```bash
curl -fsSL https://raw.githubusercontent.com/lokidv/wvpn/main/install.sh | sudo bash
```

یا:

```bash
curl -fsSL https://raw.githubusercontent.com/lokidv/wvpn/main/install_wire.sh -o install_wire.sh \
  && chmod +x install_wire.sh && sudo ./install_wire.sh
```

**پیش‌نیازها خودکار نصب می‌شوند** (نیازی به نصب دستی نیست):
- `ca-certificates` `curl` `gnupg` `git` `cron` `nano` `jq`
- Node.js 20 از NodeSource
- WireGuard + iptables + qrencode

بعد از نصب پیش‌نیازها، اسکریپت می‌پرسد:
- IP عمومی، اینترفیس شبکه، پورت UDP WireGuard
- DNS، AllowedIPs، حجم پیش‌فرض کاربران
- پورت پنل/API (پیش‌فرض 4000)
- ساخت کاربر تستی (اختیاری)

بعد از نصب، اطلاعات زیر نمایش داده می‌شود و در `/root/wvpn-install-info.txt` ذخیره می‌شود:
- آدرس پنل ادمین + رمز عبور
- API Key برای اتصال سایت
- پورت‌ها و تنظیمات WireGuard

---

## نصب دستی (قدیمی)

```
recommand
wget https://raw.githubusercontent.com/lokidv/wvpn/refs/heads/main/install_wire.sh && sudo chmod +x install_wire.sh && sudo ./install_wire.sh
wget https://raw.githubusercontent.com/lokidv/wvpn/refs/heads/main/tun.sh && sudo chmod +x tun.sh && sudo ./tun.sh
sudo apt update && sudo apt upgrade -y

for debug

nano /etc/resolv.conf

nameserver 1.1.1.1

حل مشکل دانلود نشدن از Github به دلیل قطعی IPv6

1️⃣فایل زیر را باز کنید:
nano /etc/hosts

دستور زیر را به آخر فایل اضافه کنید و آن را ذخیره کنید:
185.199.108.133 raw.githubusercontent.com


1️⃣وارد فایل زیر شوید
sudo nano /etc/sysctl.conf

2️⃣دستورات زیر رو داخل  اخر فایل اضافه کنید

net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1

3️⃣بعد از سیو کردن فایل دستور زیر رو اجرا کنید

sudo sysctl -p




sudo apt-get install -y ca-certificates curl gnupg
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
NODE_MAJOR=20
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update
sudo apt-get install nodejs -y

sudo apt install nano -y
sudo apt install git -y
sudo apt install cron -y




git clone https://github.com/lokidv/wvpn.git
mv wvpn/ /home
cd /home
cd wvpn




npm i

chmod +x wireguard-install.sh
./wireguard-install.sh
nano /etc/systemd/system/wvpn.service
```

```
[Unit]
Description=Tunnel WireGuard with udp2raw
After=network.target

[Service]
Type=simple
User=root
ExecStart=sudo node /home/wvpn/main.js
Restart=no

[Install]
WantedBy=multi-user.target
```
```
systemctl enable --now wvpn.service
```
```
systemctl status wvpn.service
```
when you want to restart
```
systemctl restart wvpn.service
```
cd
```
nano /etc/sysctl.d/99-sysctl.conf
```
بعد از زدن این دستور بای دنبال این خط بگردیم
#net.ipv4.ip_forward=1

و به این شکل تغییرش بدیم
net.ipv4.ip_forward=1
یعنی فقط ازکامنت درش بیاریم بعد ذخیره میکنیم میایم بیرون
```
rm /home/wvpn/wireguard-install.sh  && wget https://github.com/lokidv/wvpn/raw/main/wireguard-install.sh -O /home/wvpn/wireguard-install.sh && chmod +x /home/wvpn/wireguard-install.sh && sudo systemctl restart wvpn.service
```
export VISUAL=nano; crontab -e
crontab -e
```
* * * * * /bin/systemctl is-active --quiet udp2raw.service || /bin/systemctl 
```



for transfer
```
cd /
tar czvf openvpn_backup.tar.gz /etc/openvpn/ /etc/openvpn/easy-rsa/
scp openvpn_backup.tar.gz root@ip:/root
tar xzvf openvpn_backup.tar.gz
sudo systemctl stop openvpn@server.service
rm -r /etc/openvpn/
mv etc/openvpn /etc
nano /etc/systemd/system/udp2raw.service
```

