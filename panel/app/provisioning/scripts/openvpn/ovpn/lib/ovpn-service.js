const fs = require('fs');
const { execFileSync } = require('child_process');
const shell = require('shelljs');
const { applyClientFilters } = require('./client-filters');
const { resolveCreateVolume, resolveUpdateVolume } = require('./volume-params');

const OVPN_SCRIPT = process.env.OVPN_SCRIPT || '/home/ovpn/ovpn-manager.sh';
const PARAMS_FILE = process.env.OVPN_PARAMS || '/etc/openvpn/ovpn-manager/params';
const CLIENTS_DIR = process.env.OVPN_CLIENTS_DIR || '/etc/openvpn/ovpn-manager/clients';

const IPV4_RE = /^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
const ENDPOINT_RE = /^([^:\s/]+):([0-9]{1,5})$/;

// ── params file (KEY=VALUE) ──────────────────────────────────────────────────
function readServerParams() {
    if (!fs.existsSync(PARAMS_FILE)) {
        return {};
    }
    const params = {};
    for (const line of fs.readFileSync(PARAMS_FILE, 'utf8').split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) {
            continue;
        }
        const idx = trimmed.indexOf('=');
        if (idx === -1) {
            continue;
        }
        params[trimmed.slice(0, idx)] = trimmed.slice(idx + 1);
    }
    return params;
}

function writeServerParam(key, value) {
    let content = '';
    if (fs.existsSync(PARAMS_FILE)) {
        content = fs.readFileSync(PARAMS_FILE, 'utf8');
    }
    const line = `${key}=${value}`;
    const pattern = new RegExp(`^${key}=.*$`, 'm');
    if (pattern.test(content)) {
        content = content.replace(pattern, line);
    } else {
        content = content.trimEnd() + (content.endsWith('\n') ? '' : '\n') + line + '\n';
    }
    fs.writeFileSync(PARAMS_FILE, content, { mode: 0o600 });
}

// ── settings (GET via manager, PATCH writes params + applies) ────────────────
function getServerSettings() {
    const result = runScript(['get-settings']);
    const parsed = parseJsonOutput(result);
    if (parsed && parsed.success !== false) {
        return parsed;
    }
    return buildSettingsResponse();
}

function buildSettingsResponse(params = readServerParams()) {
    const serverEndpoint = params.SERVER_PUB_IP && params.SERVER_PORT
        ? `${params.SERVER_PUB_IP}:${params.SERVER_PORT}`
        : '';
    return {
        success: true,
        defaultDataLimitGB: params.DEFAULT_DATA_LIMIT_GB || '',
        clientDns1: params.CLIENT_DNS_1 || '1.1.1.1',
        clientDns2: params.CLIENT_DNS_2 || '1.0.0.1',
        clientEndpoint: params.CLIENT_ENDPOINT || '',
        serverEndpoint,
        effectiveEndpoint: params.CLIENT_ENDPOINT || serverEndpoint,
        clientMtu: params.CLIENT_MTU || '',
        protocol: params.SERVER_PROTOCOL || 'udp',
    };
}

function validateDns(value, label) {
    if (!value || typeof value !== 'string') {
        return `${label} is required`;
    }
    if (!IPV4_RE.test(value.trim())) {
        return `${label} must be a valid IPv4 address`;
    }
    return null;
}

function validateEndpoint(value) {
    if (value === '' || value === null || value === undefined) {
        return null;
    }
    const trimmed = String(value).trim();
    const match = ENDPOINT_RE.exec(trimmed);
    if (!match) {
        return 'clientEndpoint must be host:port or ip:port';
    }
    const port = Number(match[2]);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
        return 'clientEndpoint port must be between 1 and 65535';
    }
    return null;
}

function validateMtu(value) {
    if (value === '' || value === null || value === undefined) {
        return null;
    }
    const mtu = Number(value);
    if (!Number.isInteger(mtu) || mtu < 576 || mtu > 1500) {
        return 'clientMtu must be an integer between 576 and 1500, or empty';
    }
    return null;
}

function updateServerSettings(body = {}) {
    const updates = {};
    const errors = [];

    if (body.defaultDataLimitGB !== undefined && body.defaultDataLimitGB !== '') {
        const gb = Number(body.defaultDataLimitGB);
        if (!Number.isFinite(gb) || gb <= 0) {
            errors.push('defaultDataLimitGB must be a positive number');
        } else {
            updates.DEFAULT_DATA_LIMIT_GB = String(gb);
        }
    }

    if (body.clientDns1 !== undefined) {
        const err = validateDns(body.clientDns1, 'clientDns1');
        if (err) {
            errors.push(err);
        } else {
            updates.CLIENT_DNS_1 = String(body.clientDns1).trim();
        }
    }

    if (body.clientDns2 !== undefined) {
        const err = validateDns(body.clientDns2, 'clientDns2');
        if (err) {
            errors.push(err);
        } else {
            updates.CLIENT_DNS_2 = String(body.clientDns2).trim();
        }
    }

    if (body.clientEndpoint !== undefined) {
        const err = validateEndpoint(body.clientEndpoint);
        if (err) {
            errors.push(err);
        } else {
            updates.CLIENT_ENDPOINT = String(body.clientEndpoint || '').trim();
        }
    }

    if (body.clientMtu !== undefined) {
        const err = validateMtu(body.clientMtu);
        if (err) {
            errors.push(err);
        } else {
            updates.CLIENT_MTU = body.clientMtu === '' || body.clientMtu === null
                ? ''
                : String(Number(body.clientMtu));
        }
    }

    if (!Object.keys(updates).length) {
        return { success: false, error: 'No valid settings provided' };
    }
    if (errors.length) {
        return { success: false, error: errors.join('; ') };
    }

    for (const [key, value] of Object.entries(updates)) {
        writeServerParam(key, value);
    }

    // rebuild client template + all .ovpn, push new DNS, restart if DNS changed
    const applied = parseJsonOutput(runScript(['apply-settings']));
    const response = buildSettingsResponse(readServerParams());
    if (applied && applied.success !== false) {
        response.confRefresh = { count: Number(applied.count) || 0 };
    } else if (applied) {
        response.confRefresh = { count: 0, error: applied.error };
    }
    return response;
}

function setDefaultDataLimitGB(value) {
    return updateServerSettings({ defaultDataLimitGB: value });
}

// ── shell wrapper ────────────────────────────────────────────────────────────
function shellQuote(value) {
    return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function runScript(args) {
    const command = `${OVPN_SCRIPT} ${args.join(' ')}`;
    const result = shell.exec(command, { silent: true });
    return {
        code: result.code,
        stdout: (result.stdout || '').trim(),
        stderr: (result.stderr || '').trim(),
        command,
    };
}

function parseJsonOutput(result) {
    if (result.code !== 0) {
        return {
            success: false,
            error: result.stderr || result.stdout || 'Command failed',
            code: 500,
        };
    }
    try {
        return JSON.parse(result.stdout || '{}');
    } catch (e) {
        return {
            success: false,
            error: 'Invalid JSON from ovpn-manager.sh',
            raw: result.stdout,
            code: 500,
        };
    }
}

// ── client config files ─────────────────────────────────────────────────────
function resolveClientConfPath(name) {
    const filePath = `${CLIENTS_DIR}/${name}.ovpn`;
    return fs.existsSync(filePath) ? filePath : null;
}

function readClientConf(name) {
    const filePath = resolveClientConfPath(name);
    if (!filePath) {
        return null;
    }
    return fs.readFileSync(filePath, 'utf8');
}

function refreshClientConf(name) {
    return parseJsonOutput(runScript(['refresh-conf', shellQuote(name)]));
}

function refreshAllClientConfs() {
    return parseJsonOutput(runScript(['refresh-all-confs']));
}

// QR v40 at error-correction level L holds ~2953 binary bytes. An inline
// OpenVPN .ovpn (~3 KB, cert/key/tls-crypt-v2 embedded) exceeds this, so QR
// encoding is effectively never possible for OpenVPN. Short-circuit before
// spawning qrencode so we don't log a noisy "Input data too large" on every
// request — the admin UI already degrades to a "download the .ovpn" hint.
const QR_MAX_BYTES = 2900;

function generateClientQrPng(name) {
    const confPath = resolveClientConfPath(name);
    if (!confPath) {
        return { success: false, error: 'Config not found' };
    }
    const conf = fs.readFileSync(confPath, 'utf8');
    if (Buffer.byteLength(conf) > QR_MAX_BYTES) {
        return {
            success: false,
            error: 'Config is too large for a QR code (OpenVPN limitation); use the .ovpn download.',
        };
    }
    try {
        const png = execFileSync('qrencode', ['-t', 'PNG', '-l', 'L', '-o', '-'], {
            input: conf,
            maxBuffer: 4 * 1024 * 1024,
        });
        return { success: true, data: png };
    } catch (e) {
        return {
            success: false,
            error: 'QR generation failed. Install qrencode on the server.',
        };
    }
}

// ── expiry helpers (shared with WG behaviour) ────────────────────────────────
function normalizeExpiresAt(value) {
    if (value === undefined || value === null || value === '') {
        return null;
    }
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric > 0) {
        return numeric > 1e12 ? Math.floor(numeric / 1000) : Math.floor(numeric);
    }
    const parsed = Date.parse(String(value));
    if (Number.isFinite(parsed)) {
        return Math.floor(parsed / 1000);
    }
    return null;
}

function isTruthyFlag(value) {
    return value === true || value === 1 || value === '1' || value === 'true';
}

function buildAddArgs(name, options = {}) {
    const volume = resolveCreateVolume(options);
    const args = ['add', shellQuote(name)];
    if (volume.explicitLimit) {
        args.push('--explicit-limit');
        args.push('--limit-gb', shellQuote(volume.dataLimitGB ?? 0));
    } else if (options.dataLimitGB !== undefined && options.dataLimitGB !== '') {
        args.push('--limit-gb', shellQuote(options.dataLimitGB));
    }
    if (options.expiresInDays !== undefined && options.expiresInDays !== '') {
        args.push('--days', shellQuote(options.expiresInDays));
    }
    if (options.ip !== undefined && options.ip !== '') {
        args.push('--ip', shellQuote(options.ip));
    }
    return args;
}

function buildUpdateArgs(name, options = {}) {
    const volume = resolveUpdateVolume(options);
    const args = ['update', shellQuote(name)];
    if (volume.addDataGB !== undefined) {
        args.push('--add-gb', shellQuote(volume.addDataGB));
    }
    if (options.extendDays !== undefined && options.extendDays !== '') {
        args.push('--extend-days', shellQuote(options.extendDays));
    }
    if (volume.setDataLimitGB !== undefined) {
        args.push('--set-limit-gb', shellQuote(volume.setDataLimitGB));
    }
    const expiresAt = normalizeExpiresAt(options.setExpiresAt);
    if (expiresAt !== null) {
        args.push('--set-expires-at', shellQuote(expiresAt));
    }
    if (isTruthyFlag(options.clearExpires)) {
        args.push('--clear-expires');
    }
    return args;
}

// ── client lifecycle ────────────────────────────────────────────────────────
function addClient(name, options) {
    return parseJsonOutput(runScript(buildAddArgs(name, options)));
}

function updateClient(name, options) {
    return parseJsonOutput(runScript(buildUpdateArgs(name, options)));
}

function infoClient(name) {
    return parseJsonOutput(runScript(['info', shellQuote(name)]));
}

function disableClient(name, reason = 'manual') {
    return parseJsonOutput(runScript(['disable', shellQuote(name), shellQuote(reason)]));
}

function enableClient(name) {
    return parseJsonOutput(runScript(['enable', shellQuote(name)]));
}

function removeClient(name) {
    return parseJsonOutput(runScript(['remove', shellQuote(name)]));
}

function listClients(query = {}) {
    const raw = parseJsonOutput(runScript(['list']));
    return applyClientFilters(raw, query);
}

function enforceClients() {
    return parseJsonOutput(runScript(['enforce']));
}

function clientExists(name) {
    return resolveClientConfPath(name) !== null;
}

module.exports = {
    OVPN_SCRIPT,
    PARAMS_FILE,
    runScript,
    parseJsonOutput,
    readServerParams,
    getServerSettings,
    updateServerSettings,
    setDefaultDataLimitGB,
    readClientConf,
    resolveClientConfPath,
    refreshClientConf,
    refreshAllClientConfs,
    generateClientQrPng,
    addClient,
    updateClient,
    infoClient,
    disableClient,
    enableClient,
    removeClient,
    listClients,
    enforceClients,
    clientExists,
};
