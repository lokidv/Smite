const http = require('http');
const fs = require('fs');
const path = require('path');
const eURL = require('url');
const logger = require('logger').createLogger('vpn.log');

const { ensureSecurityConfig, getAdminPath, verifyApiKey, verifyAdminPassword } = require('./lib/config');
const {
    getClientIp,
    isAdminIpAllowed,
    createSession,
    getSessionFromRequest,
    buildSessionCookie,
    clearSessionCookie,
    destroySession,
    verifyCsrf,
    checkApiRateLimit,
    checkLoginAllowed,
    recordFailedLogin,
    clearLoginAttempts,
    setSecurityHeaders,
    sendNotFound,
    extractApiKey,
} = require('./lib/security');
const { sendJson, sendText, sendHtml, sendBinary, readJsonBody } = require('./lib/http-utils');
const wg = require('./lib/wg-service');
const { resolveCreateVolume, resolveUpdateVolume } = require('./lib/volume-params');

const httpPort = Number(process.env.WVPN_PORT || 4000);
const ENFORCE_INTERVAL_MS = Number(process.env.WVPN_ENFORCE_INTERVAL_MS || 30_000);
const ADMIN_HTML = path.join(__dirname, 'admin.html');
const LOGIN_FAILURE_DELAY_MS = 750;

const config = ensureSecurityConfig();
const ADMIN_PATH = getAdminPath(config);
const site_server = http.createServer();

function getClientName(query) {
    return query.publicKey || query.name || '';
}

function adminApiPath(suffix) {
    return `${ADMIN_PATH}/api/${suffix.replace(/^\//, '')}`;
}

function requireApiAuth(req, res, query) {
    const ip = getClientIp(req);
    const limit = config.rateLimit?.apiPerMinute || 60;
    if (!checkApiRateLimit(ip, limit)) {
        sendJson(res, { success: false, error: 'Too many requests' }, 429);
        return false;
    }
    const apiKey = extractApiKey(req, query);
    if (!verifyApiKey(apiKey)) {
        logger.info('blocked unauthorized api request from', ip);
        sendJson(res, { success: false, error: 'Unauthorized' }, 401);
        return false;
    }
    return true;
}

function requireAdminIp(req, res) {
    const ip = getClientIp(req);
    if (!isAdminIpAllowed(ip, config)) {
        logger.info('blocked admin access from disallowed ip', ip);
        sendNotFound(res);
        return false;
    }
    return true;
}

function requireAdminSession(req, res, requireCsrf) {
    const session = getSessionFromRequest(req, ADMIN_PATH);
    if (!session) {
        sendJson(res, { success: false, error: 'Unauthorized' }, 401);
        return null;
    }
    if (requireCsrf && !verifyCsrf(session, req)) {
        sendJson(res, { success: false, error: 'Invalid CSRF token' }, 403);
        return null;
    }
    return session;
}

function normalizePath(pathname) {
    return pathname.replace(/^\/|\/$/g, '');
}

function matchAdminClientRoute(pathname) {
    const prefix = `${ADMIN_PATH}/api/clients/`;
    if (!pathname.startsWith(prefix)) {
        return null;
    }
    const rest = pathname.slice(prefix.length);
    const parts = rest.split('/');
    const name = decodeURIComponent(parts[0] || '');
    const action = parts.slice(1).join('/') || '';
    if (!name) {
        return null;
    }
    return { name, action };
}

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function addVpn(req, res, query) {
    const name = getClientName(query);
    if (!name) {
        return sendJson(res, { success: false, error: 'publicKey is required' }, 400);
    }

    const existingConf = wg.readClientConf(name);
    if (existingConf) {
        return sendText(res, existingConf);
    }

    const result = wg.addClient(name, {
        ...resolveCreateVolume(query),
        expiresInDays: query.expiresInDays,
        ip: query.ip,
    });
    if (!result.success) {
        return sendJson(res, result, result.code || 400);
    }

    let conf = null;
    if (result.confPath && fs.existsSync(result.confPath)) {
        conf = fs.readFileSync(result.confPath, 'utf8');
    } else {
        conf = wg.readClientConf(name);
    }
    if (!conf) {
        return sendJson(res, { success: false, error: 'Client created but config file not found' }, 500);
    }
    return sendText(res, conf);
}

async function handlePublicApi(req, res, pathname, query) {
    if (!requireApiAuth(req, res, query)) {
        return;
    }

    switch (pathname) {
        case 'create':
            return addVpn(req, res, query);
        case 'update': {
            const result = wg.updateClient(getClientName(query), {
                ...resolveUpdateVolume(query),
                extendDays: query.extendDays,
                setExpiresAt: query.setExpiresAt,
                clearExpires: query.clearExpires,
            });
            return sendJson(res, result, result.success === false ? 400 : 200);
        }
        case 'info': {
            const result = wg.infoClient(getClientName(query));
            return sendJson(res, result, result.success === false ? 404 : 200);
        }
        case 'disable': {
            const result = wg.disableClient(getClientName(query), query.reason || 'manual');
            return sendJson(res, result, result.success === false ? 400 : 200);
        }
        case 'enable': {
            const result = wg.enableClient(getClientName(query));
            return sendJson(res, result, result.success === false ? 400 : 200);
        }
        case 'remove': {
            const result = wg.removeClient(getClientName(query));
            return sendJson(res, result, result.success === false ? 400 : 200);
        }
        case 'list': {
            const result = wg.listClients(query);
            return sendJson(res, result, result.success === false ? 500 : 200);
        }
        case 'check': {
            const name = getClientName(query);
            return sendText(res, wg.clientExists(name) ? 'true' : 'false');
        }
        default:
            return sendNotFound(res);
    }
}

async function handleAdminApi(req, res, pathname, query = {}) {
    if (!requireAdminIp(req, res)) {
        return;
    }

    if (pathname === adminApiPath('login') && req.method === 'POST') {
        const ip = getClientIp(req);
        const maxAttempts = config.rateLimit?.loginPer15Min || 3;
        const allowed = checkLoginAllowed(ip, maxAttempts, config);
        if (!allowed.allowed) {
            return sendJson(
                res,
                { success: false, error: `Too many login attempts. Retry in ${allowed.retryAfterSec}s` },
                429
            );
        }

        let body;
        try {
            body = await readJsonBody(req);
        } catch (e) {
            return sendJson(res, { success: false, error: 'Invalid JSON body' }, 400);
        }

        if (!verifyAdminPassword(body.password || '')) {
            recordFailedLogin(ip, allowed.attempt, config);
            await delay(LOGIN_FAILURE_DELAY_MS);
            return sendJson(res, { success: false, error: 'Invalid credentials' }, 401);
        }

        clearLoginAttempts(ip);
        const session = createSession(ADMIN_PATH);
        res.setHeader('Set-Cookie', buildSessionCookie(session.sessionId, session.expiresAt, ADMIN_PATH));
        return sendJson(res, { success: true, csrfToken: session.csrfToken });
    }

    if (pathname === adminApiPath('logout') && req.method === 'POST') {
        const session = requireAdminSession(req, res, true);
        if (!session) {
            return;
        }
        destroySession(session.sessionId);
        res.setHeader('Set-Cookie', clearSessionCookie(ADMIN_PATH));
        return sendJson(res, { success: true });
    }

    if (pathname === adminApiPath('session') && req.method === 'GET') {
        const session = requireAdminSession(req, res, false);
        if (!session) {
            return;
        }
        return sendJson(res, { success: true, csrfToken: session.csrfToken });
    }

    if (pathname === adminApiPath('clients') && req.method === 'GET') {
        const session = requireAdminSession(req, res, false);
        if (!session) {
            return;
        }
        const result = wg.listClients(query);
        return sendJson(res, result, result.success === false ? 500 : 200);
    }

    if (pathname === adminApiPath('clients') && req.method === 'POST') {
        const session = requireAdminSession(req, res, true);
        if (!session) {
            return;
        }
        const body = await readJsonBody(req);
        const name = body.name || body.publicKey;
        if (!name) {
            return sendJson(res, { success: false, error: 'name is required' }, 400);
        }
        const result = wg.addClient(name, {
            ...resolveCreateVolume(body),
            expiresInDays: body.expiresInDays,
            ip: body.ip,
        });
        return sendJson(res, result, result.success === false ? 400 : 200);
    }

    if (pathname === adminApiPath('enforce') && req.method === 'POST') {
        const session = requireAdminSession(req, res, true);
        if (!session) {
            return;
        }
        const result = wg.enforceClients();
        return sendJson(res, result, result.success === false ? 500 : 200);
    }

    if (pathname === adminApiPath('settings') && req.method === 'GET') {
        const session = requireAdminSession(req, res, false);
        if (!session) {
            return;
        }
        return sendJson(res, wg.getServerSettings(), 200);
    }

    if (pathname === adminApiPath('settings') && req.method === 'PATCH') {
        const session = requireAdminSession(req, res, true);
        if (!session) {
            return;
        }
        const body = await readJsonBody(req);
        const result = wg.updateServerSettings(body);
        return sendJson(res, result, result.success === false ? 400 : 200);
    }

    const route = matchAdminClientRoute(pathname);
    if (route) {
        const session = requireAdminSession(req, res, req.method !== 'GET');
        if (!session) {
            return;
        }

        if (route.action === 'conf/download' && req.method === 'GET') {
            const conf = wg.readClientConf(route.name);
            if (!conf) {
                return sendJson(res, { success: false, error: 'Config not found' }, 404);
            }
            const params = wg.readServerParams();
            const nic = params.SERVER_WG_NIC || 'wg0';
            const filename = `${nic}-client-${route.name}.conf`;
            return sendBinary(res, Buffer.from(conf, 'utf8'), 'application/octet-stream', {
                disposition: `attachment; filename="${filename}"`,
            });
        }

        if (route.action === 'conf' && req.method === 'GET') {
            const conf = wg.readClientConf(route.name);
            if (!conf) {
                return sendJson(res, { success: false, error: 'Config not found' }, 404);
            }
            return sendJson(res, { success: true, name: route.name, conf });
        }

        if (route.action === 'qrcode' && req.method === 'GET') {
            const result = wg.generateClientQrPng(route.name);
            if (!result.success) {
                return sendJson(res, result, 404);
            }
            return sendBinary(res, result.data, 'image/png');
        }

        if (route.action === 'refresh-conf' && req.method === 'POST') {
            const result = wg.refreshClientConf(route.name);
            return sendJson(res, result, result.success === false ? 400 : 200);
        }

        if (route.action === 'disable' && req.method === 'POST') {
            return sendJson(res, wg.disableClient(route.name, 'manual'), 200);
        }

        if (route.action === 'enable' && req.method === 'POST') {
            return sendJson(res, wg.enableClient(route.name), 200);
        }

        if (!route.action && req.method === 'PATCH') {
            const body = await readJsonBody(req);
            const result = wg.updateClient(route.name, {
                ...resolveUpdateVolume(body),
                extendDays: body.extendDays,
                setExpiresAt: body.setExpiresAt,
                clearExpires: body.clearExpires,
            });
            return sendJson(res, result, result.success === false ? 400 : 200);
        }

        if (!route.action && req.method === 'DELETE') {
            return sendJson(res, wg.removeClient(route.name), 200);
        }
    }

    return sendNotFound(res);
}

function serveAdminPanel(req, res) {
    if (!requireAdminIp(req, res)) {
        return;
    }
    if (!fs.existsSync(ADMIN_HTML)) {
        return sendNotFound(res);
    }
    let html = fs.readFileSync(ADMIN_HTML, 'utf8');
    const inject = `<script>window.WVPN_ADMIN_BASE='/${ADMIN_PATH}';</script>`;
    html = html.includes('</head>') ? html.replace('</head>', `${inject}</head>`) : inject + html;
    setSecurityHeaders(res, { admin: true });
    return sendHtml(res, html);
}

function runEnforce() {
    const result = wg.runScript(['enforce']);
    if (result.stdout) {
        try {
            const payload = JSON.parse(result.stdout);
            if (payload.disabled && payload.disabled.length > 0) {
                logger.info('enforce disabled clients', JSON.stringify(payload.disabled));
            }
        } catch (e) {
            logger.info('enforce output', result.stdout);
        }
    }
    if (result.stderr) {
        logger.error('enforce stderr', result.stderr);
    }
}

function startEnforceScheduler() {
    runEnforce();
    setInterval(runEnforce, ENFORCE_INTERVAL_MS);
    logger.info(`enforce scheduler started (${ENFORCE_INTERVAL_MS}ms)`);
}

function isAdminRoute(pathname) {
    return pathname === ADMIN_PATH || pathname.startsWith(`${ADMIN_PATH}/`);
}

async function startHttpServer() {
    logger.info('http server start ...');

    site_server.on('error', (err) => {
        logger.error('http server error ', err.stack);
    });

    site_server.on('request', async (req, res) => {
        setSecurityHeaders(res);

        try {
            const parsed = eURL.parse(req.url, true);
            const pathname = normalizePath(parsed.pathname || '/');

            if (pathname === ADMIN_PATH) {
                return serveAdminPanel(req, res);
            }

            if (pathname.startsWith(`${ADMIN_PATH}/api/`)) {
                setSecurityHeaders(res, { admin: true });
                return handleAdminApi(req, res, pathname, parsed.query);
            }

            if (isAdminRoute(pathname) || pathname === 'admin' || pathname.startsWith('admin/')) {
                return sendNotFound(res);
            }

            if (req.method === 'GET') {
                return handlePublicApi(req, res, pathname, parsed.query);
            }

            return sendNotFound(res);
        } catch (e) {
            logger.error('request error', e.message);
            if (!res.headersSent) {
                sendNotFound(res);
            }
        }
    });

    site_server.listen(httpPort, () => {
        logger.info('http server listen on ' + httpPort);
        logger.info('admin path configured (secret)');
        startEnforceScheduler();
    });
}

startHttpServer();
