const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const bcrypt = require('bcrypt');

const CONFIG_DIR = process.env.WVPN_CONFIG_DIR || '/etc/wvpn';
const CONFIG_PATH = path.join(CONFIG_DIR, 'wvpn.json');
const CONFIG_MODE = 0o600;
const BCRYPT_ROUNDS = 14;

function ensureConfigDir() {
    if (!fs.existsSync(CONFIG_DIR)) {
        fs.mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
    }
}

function randomToken(bytes = 32) {
    return crypto.randomBytes(bytes).toString('hex');
}

function generateAdminPath() {
    const slug = crypto.randomBytes(18).toString('base64url').replace(/[^a-zA-Z0-9]/g, '');
    return `p-${slug.slice(0, 22)}`;
}

function generateAdminPassword() {
    return crypto.randomBytes(24).toString('base64url');
}

function normalizeAdminPath(value) {
    return String(value || '')
        .trim()
        .replace(/^\/+|\/+$/g, '')
        .replace(/[^a-zA-Z0-9_-]/g, '');
}

function defaultConfig() {
    const apiKey = randomToken(32);
    const adminPassword = generateAdminPassword();
    const adminPasswordHash = bcrypt.hashSync(adminPassword, BCRYPT_ROUNDS);
    return {
        apiKey,
        adminPath: generateAdminPath(),
        adminPasswordHash,
        sessionSecret: randomToken(32),
        adminAllowIps: [],
        createdAt: new Date().toISOString(),
        rateLimit: {
            apiPerMinute: 60,
            loginPer15Min: 3,
            loginLockoutMinutes: 30,
        },
        _initialAdminPassword: adminPassword,
    };
}

function loadConfig() {
    ensureConfigDir();
    if (!fs.existsSync(CONFIG_PATH)) {
        const generated = defaultConfig();
        const initialPassword = generated._initialAdminPassword;
        delete generated._initialAdminPassword;
        fs.writeFileSync(CONFIG_PATH, JSON.stringify(generated, null, 2), { mode: CONFIG_MODE });
        console.log('[wvpn] Config created at', CONFIG_PATH);
        console.log('[wvpn] Save these credentials securely:');
        console.log('[wvpn] API Key:', generated.apiKey);
        console.log('[wvpn] Admin password:', initialPassword);
        console.log('[wvpn] Admin path:', generated.adminPath);
        const port = process.env.WVPN_PORT || '4000';
        console.log('[wvpn] Admin panel: http://<server-ip>:' + port + '/' + generated.adminPath + '/');
        return generated;
    }
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
}

function ensureSecurityConfig() {
    const config = loadConfig();
    let changed = false;

    if (!config.adminPath || !normalizeAdminPath(config.adminPath)) {
        config.adminPath = generateAdminPath();
        changed = true;
    } else {
        config.adminPath = normalizeAdminPath(config.adminPath);
    }

    if (!Array.isArray(config.adminAllowIps)) {
        config.adminAllowIps = [];
        changed = true;
    }

    if (!config.rateLimit) {
        config.rateLimit = {
            apiPerMinute: 60,
            loginPer15Min: 3,
            loginLockoutMinutes: 30,
        };
        changed = true;
    }

    if (changed) {
        saveConfig(config);
    }
    return config;
}

function getAdminPath(config = loadConfig()) {
    return normalizeAdminPath(config.adminPath) || generateAdminPath();
}

function saveConfig(config) {
    ensureConfigDir();
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), { mode: CONFIG_MODE });
}

function getApiKey() {
    return loadConfig().apiKey;
}

function verifyApiKey(provided) {
    if (!provided || typeof provided !== 'string') {
        return false;
    }
    const expected = getApiKey();
    if (provided.length !== expected.length) {
        return false;
    }
    return crypto.timingSafeEqual(Buffer.from(provided), Buffer.from(expected));
}

function verifyAdminPassword(password) {
    const config = loadConfig();
    return bcrypt.compareSync(password, config.adminPasswordHash);
}

function rotateAdminPassword(newPassword) {
    const config = loadConfig();
    config.adminPasswordHash = bcrypt.hashSync(newPassword, BCRYPT_ROUNDS);
    saveConfig(config);
}

module.exports = {
    CONFIG_PATH,
    loadConfig,
    ensureSecurityConfig,
    getAdminPath,
    saveConfig,
    verifyApiKey,
    verifyAdminPassword,
    rotateAdminPassword,
    randomToken,
    generateAdminPath,
    normalizeAdminPath,
};
