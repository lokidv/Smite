const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const bcrypt = require('bcrypt');

const CONFIG_DIR = process.env.WVPN_CONFIG_DIR || '/etc/wvpn';
const CONFIG_PATH = path.join(CONFIG_DIR, 'wvpn.json');
const BCRYPT_ROUNDS = 14;

function generateAdminPath() {
    const slug = crypto.randomBytes(18).toString('base64url').replace(/[^a-zA-Z0-9]/g, '');
    return `p-${slug.slice(0, 22)}`;
}

function main() {
    if (fs.existsSync(CONFIG_PATH)) {
        const existing = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
        if (!existing.adminPath) {
            existing.adminPath = generateAdminPath();
            fs.writeFileSync(CONFIG_PATH, JSON.stringify(existing, null, 2), { mode: 0o600 });
            console.log('ADMIN_PATH=' + existing.adminPath);
        }
        console.log(`Config already exists: ${CONFIG_PATH}`);
        return;
    }

    fs.mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
    const apiKey = crypto.randomBytes(32).toString('hex');
    const adminPassword = crypto.randomBytes(24).toString('base64url');
    const adminPath = generateAdminPath();
    const config = {
        apiKey,
        adminPath,
        adminPasswordHash: bcrypt.hashSync(adminPassword, BCRYPT_ROUNDS),
        sessionSecret: crypto.randomBytes(32).toString('hex'),
        adminAllowIps: [],
        createdAt: new Date().toISOString(),
        rateLimit: {
            apiPerMinute: 60,
            loginPer15Min: 3,
            loginLockoutMinutes: 30,
        },
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), { mode: 0o600 });
    console.log('WVPN security config created.');
    console.log('CONFIG_PATH=' + CONFIG_PATH);
    console.log('API_KEY=' + apiKey);
    console.log('ADMIN_PASSWORD=' + adminPassword);
    console.log('ADMIN_PATH=' + adminPath);
    const port = process.env.WVPN_PORT || '4000';
    console.log('ADMIN_PANEL=http://<server-ip>:' + port + '/' + adminPath + '/');
}

main();
