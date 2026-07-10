const crypto = require('crypto');
const { loadConfig } = require('./config');

const SESSION_COOKIE = 'wvpn_session';
const SESSION_TTL_MS = 4 * 60 * 60 * 1000;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;

const sessions = new Map();
const apiRateBuckets = new Map();
const loginAttempts = new Map();

function cleanupMaps() {
    const now = Date.now();
    for (const [key, session] of sessions.entries()) {
        if (session.expiresAt <= now) {
            sessions.delete(key);
        }
    }
    for (const [key, bucket] of apiRateBuckets.entries()) {
        if (bucket.resetAt <= now) {
            apiRateBuckets.delete(key);
        }
    }
    for (const [key, attempt] of loginAttempts.entries()) {
        if (attempt.lockUntil <= now && attempt.resetAt <= now) {
            loginAttempts.delete(key);
        }
    }
}

setInterval(cleanupMaps, 60_000).unref();

function normalizeIp(ip) {
    if (!ip) {
        return 'unknown';
    }
    return String(ip).replace(/^::ffff:/, '');
}

function getClientIp(req) {
    const config = loadConfig();
    const trustProxy = config.trustProxy === true;
    if (trustProxy) {
        const forwarded = req.headers['x-forwarded-for'];
        if (forwarded) {
            return normalizeIp(String(forwarded).split(',')[0].trim());
        }
    }
    return normalizeIp(req.socket.remoteAddress || 'unknown');
}

function isAdminIpAllowed(ip, config = loadConfig()) {
    const allowList = config.adminAllowIps || [];
    if (!allowList.length) {
        return true;
    }
    const normalized = normalizeIp(ip);
    return allowList.some((entry) => normalizeIp(entry) === normalized);
}

function signSessionId(sessionId) {
    const config = loadConfig();
    return crypto.createHmac('sha256', config.sessionSecret).update(sessionId).digest('hex');
}

function createSession(adminPath) {
    const sessionId = crypto.randomBytes(32).toString('hex');
    const csrfToken = crypto.randomBytes(32).toString('hex');
    const expiresAt = Date.now() + SESSION_TTL_MS;
    sessions.set(sessionId, { csrfToken, expiresAt, createdAt: Date.now(), adminPath });
    return { sessionId, csrfToken, expiresAt };
}

function parseCookies(req) {
    const header = req.headers.cookie || '';
    const cookies = {};
    header.split(';').forEach((part) => {
        const idx = part.indexOf('=');
        if (idx === -1) {
            return;
        }
        const key = part.slice(0, idx).trim();
        const value = part.slice(idx + 1).trim();
        cookies[key] = decodeURIComponent(value);
    });
    return cookies;
}

function getSessionFromRequest(req, adminPath) {
    const cookies = parseCookies(req);
    const raw = cookies[SESSION_COOKIE];
    if (!raw || !raw.includes('.')) {
        return null;
    }
    const [sessionId, signature] = raw.split('.', 2);
    if (!sessionId || !signature) {
        return null;
    }
    const expected = signSessionId(sessionId);
    if (signature.length !== expected.length) {
        return null;
    }
    if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {
        return null;
    }
    const session = sessions.get(sessionId);
    if (!session || session.expiresAt <= Date.now()) {
        sessions.delete(sessionId);
        return null;
    }
    if (session.adminPath && adminPath && session.adminPath !== adminPath) {
        return null;
    }
    return { sessionId, ...session };
}

function buildSessionCookie(sessionId, expiresAt, adminPath) {
    const signature = signSessionId(sessionId);
    const value = `${sessionId}.${signature}`;
    const maxAge = Math.floor((expiresAt - Date.now()) / 1000);
    const cookiePath = `/${adminPath}`;
    return `${SESSION_COOKIE}=${encodeURIComponent(value)}; HttpOnly; SameSite=Strict; Path=${cookiePath}; Max-Age=${maxAge}`;
}

function clearSessionCookie(adminPath) {
    const cookiePath = `/${adminPath}`;
    return `${SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=${cookiePath}; Max-Age=0`;
}

function destroySession(sessionId) {
    sessions.delete(sessionId);
}

function verifyCsrf(session, req) {
    const token = req.headers['x-csrf-token'];
    if (!token || !session.csrfToken) {
        return false;
    }
    if (token.length !== session.csrfToken.length) {
        return false;
    }
    return crypto.timingSafeEqual(Buffer.from(token), Buffer.from(session.csrfToken));
}

function checkApiRateLimit(ip, limit) {
    const now = Date.now();
    const bucket = apiRateBuckets.get(ip) || { count: 0, resetAt: now + 60_000 };
    if (bucket.resetAt <= now) {
        bucket.count = 0;
        bucket.resetAt = now + 60_000;
    }
    bucket.count += 1;
    apiRateBuckets.set(ip, bucket);
    return bucket.count <= limit;
}

function getLoginLockoutMs(config = loadConfig()) {
    const minutes = Number(config.rateLimit?.loginLockoutMinutes || 30);
    return Math.max(5, minutes) * 60_000;
}

function checkLoginAllowed(ip, maxAttempts, config = loadConfig()) {
    const now = Date.now();
    const lockoutMs = getLoginLockoutMs(config);
    const attempt = loginAttempts.get(ip) || { count: 0, resetAt: now + LOGIN_WINDOW_MS, lockUntil: 0 };
    if (attempt.lockUntil > now) {
        return { allowed: false, retryAfterSec: Math.ceil((attempt.lockUntil - now) / 1000) };
    }
    if (attempt.resetAt <= now) {
        attempt.count = 0;
        attempt.resetAt = now + LOGIN_WINDOW_MS;
    }
    if (attempt.count >= maxAttempts) {
        attempt.lockUntil = now + lockoutMs;
        loginAttempts.set(ip, attempt);
        return { allowed: false, retryAfterSec: Math.ceil(lockoutMs / 1000) };
    }
    return { allowed: true, attempt };
}

function recordFailedLogin(ip, attemptState, config = loadConfig()) {
    const lockoutMs = getLoginLockoutMs(config);
    const attempt = attemptState || loginAttempts.get(ip) || { count: 0, resetAt: Date.now() + LOGIN_WINDOW_MS, lockUntil: 0 };
    attempt.count += 1;
    const maxAttempts = Number(config.rateLimit?.loginPer15Min || 3);
    if (attempt.count >= maxAttempts) {
        attempt.lockUntil = Date.now() + lockoutMs;
    }
    loginAttempts.set(ip, attempt);
}

function clearLoginAttempts(ip) {
    loginAttempts.delete(ip);
}

function setSecurityHeaders(res, options = {}) {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Permissions-Policy', 'geolocation=(), microphone=(), camera=()');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Robots-Tag', 'noindex, nofollow');
    if (options.admin) {
        res.setHeader(
            'Content-Security-Policy',
            "default-src 'none'; connect-src 'self'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        );
    }
}

function sendNotFound(res) {
    if (!res.headersSent) {
        setSecurityHeaders(res);
        res.statusCode = 404;
        res.setHeader('Content-Type', 'text/plain; charset=utf-8');
        res.end('Not Found');
    }
}

function extractApiKey(req, query) {
    const header = req.headers['x-api-key'] || req.headers.authorization || '';
    if (header.startsWith('Bearer ')) {
        return header.slice(7).trim();
    }
    if (header) {
        return String(header).trim();
    }
    if (query && query.apiKey) {
        return String(query.apiKey);
    }
    return '';
}

module.exports = {
    SESSION_COOKIE,
    SESSION_TTL_MS,
    getClientIp,
    normalizeIp,
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
};
