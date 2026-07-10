function sendJson(res, payload, statusCode) {
    const code = statusCode || (payload.success === false ? 400 : 200);
    res.statusCode = code;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.end(JSON.stringify(payload));
}

function sendText(res, text, statusCode) {
    res.statusCode = statusCode || 200;
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.end(text);
}

function sendHtml(res, html, statusCode) {
    res.statusCode = statusCode || 200;
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(html);
}

function sendBinary(res, buffer, contentType, options = {}) {
    res.statusCode = options.statusCode || 200;
    res.setHeader('Content-Type', contentType);
    if (options.disposition) {
        res.setHeader('Content-Disposition', options.disposition);
    }
    res.end(buffer);
}

function readBody(req, maxBytes = 1_048_576) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        let size = 0;
        req.on('data', (chunk) => {
            size += chunk.length;
            if (size > maxBytes) {
                reject(new Error('Request body too large'));
                req.destroy();
                return;
            }
            chunks.push(chunk);
        });
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
        req.on('error', reject);
    });
}

async function readJsonBody(req) {
    const raw = await readBody(req);
    if (!raw) {
        return {};
    }
    return JSON.parse(raw);
}

module.exports = {
    sendJson,
    sendText,
    sendHtml,
    sendBinary,
    readBody,
    readJsonBody,
};
