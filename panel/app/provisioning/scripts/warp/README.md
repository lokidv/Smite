مشکل ساده است: اسکریپت ریشه (install.sh) فقط یک واسطه است و اسکریپت اصلی یعنی wvpn/install.sh را اجرا می‌کند، ولی آن فایل مجوز اجرا (execute) ندارد. شما فقط به install.sh ریشه chmod +x زدید، نه به فایل داخل wvpn.

روی سرور این را اجرا کنید:
```
git clone https://github.com/lokidv/wginstaller.git
cd wginstaller
sudo ./install.sh



chmod +x wvpn/install.sh
./install.sh
```
یا برای اطمینان، به همه اسکریپت‌ها مجوز بدهید:

```
chmod +x install.sh wvpn/install.sh wireguard-install/*.sh 2>/dev/null
./install.sh
```
راه جایگزین (بدون نیاز به chmod):
```
bash wvpn/install.sh
```
علت اینکه فایل‌ها بدون مجوز اجرا منتقل شده‌اند معمولاً این است که از ویندوز کپی/آپلود شده‌اند (مثلاً با scp یا zip)، چون ویندوز بیت اجرای لینوکس را نگه نمی‌دارد.
