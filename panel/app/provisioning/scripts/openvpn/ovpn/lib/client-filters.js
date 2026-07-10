const GB = 1024 ** 3;

function isTruthy(value) {
    return value === true || value === 1 || value === '1' || value === 'true';
}

function parseNumber(value) {
    if (value === undefined || value === null || value === '') {
        return null;
    }
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function parseTimestamp(value) {
    const n = parseNumber(value);
    if (n === null) {
        return null;
    }
    return n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
}

function hasExpiry(client) {
    const exp = client.expiresAt;
    return exp !== null && exp !== undefined && exp !== 'null' && Number(exp) > 0;
}

function parseListFilters(query = {}) {
    const limit = parseInt(query.limit, 10);
    const offset = parseInt(query.offset, 10);
    return {
        search: String(query.q || query.search || '').trim().toLowerCase(),
        status: String(query.status || 'all').toLowerCase(),
        disabledReason: String(query.reason || query.disabledReason || '').trim(),
        expiry: String(query.expiry || 'all').toLowerCase(),
        expiresWithinDays: parseNumber(query.expiresWithinDays) || 7,
        expiresBefore: parseTimestamp(query.expiresBefore),
        expiresAfter: parseTimestamp(query.expiresAfter),
        createdBefore: parseTimestamp(query.createdBefore),
        createdAfter: parseTimestamp(query.createdAfter),
        usedMinGB: parseNumber(query.usedMinGB),
        usedMaxGB: parseNumber(query.usedMaxGB),
        limitMinGB: parseNumber(query.limitMinGB),
        limitMaxGB: parseNumber(query.limitMaxGB),
        overQuota: isTruthy(query.overQuota),
        hasDataLimit: isTruthy(query.hasDataLimit),
        unlimitedData: isTruthy(query.unlimitedData),
        sort: String(query.sort || 'name'),
        order: String(query.order || 'asc').toLowerCase() === 'desc' ? 'desc' : 'asc',
        limit: Number.isInteger(limit) && limit > 0 ? Math.min(limit, 1000) : 0,
        offset: Number.isInteger(offset) && offset >= 0 ? offset : 0,
    };
}

function matchesSearch(client, search) {
    if (!search) {
        return true;
    }
    const haystack = [
        client.name,
        client.ipv4,
        client.publicKey,
        client.disabledReason,
        client.status,
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(search);
}

function matchesExpiry(client, filters, now) {
    const expiryTs = hasExpiry(client) ? Number(client.expiresAt) : null;

    switch (filters.expiry) {
        case 'unlimited':
            if (expiryTs !== null) {
                return false;
            }
            break;
        case 'expired':
            if (expiryTs === null || now < expiryTs) {
                return false;
            }
            break;
        case 'expiring':
            if (expiryTs === null || now >= expiryTs) {
                return false;
            }
            if (expiryTs > now + filters.expiresWithinDays * 86400) {
                return false;
            }
            break;
        case 'active':
            if (expiryTs !== null && now >= expiryTs) {
                return false;
            }
            break;
        default:
            break;
    }

    if (filters.expiresBefore !== null) {
        if (expiryTs === null || expiryTs > filters.expiresBefore) {
            return false;
        }
    }
    if (filters.expiresAfter !== null) {
        if (expiryTs === null || expiryTs < filters.expiresAfter) {
            return false;
        }
    }
    return true;
}

function matchesDataLimit(client, filters) {
    const limitBytes = client.dataLimitBytes;
    const hasLimit = limitBytes !== null && limitBytes !== undefined && limitBytes !== 'null';

    if (filters.hasDataLimit && !hasLimit) {
        return false;
    }
    if (filters.unlimitedData && hasLimit) {
        return false;
    }
    if (filters.overQuota) {
        if (!hasLimit || Number(client.usedBytes || 0) < Number(limitBytes)) {
            return false;
        }
    }

    const usedGb = Number(client.usedBytes || 0) / GB;
    if (filters.usedMinGB !== null && usedGb < filters.usedMinGB) {
        return false;
    }
    if (filters.usedMaxGB !== null && usedGb > filters.usedMaxGB) {
        return false;
    }

    if (hasLimit) {
        const limitGb = Number(limitBytes) / GB;
        if (filters.limitMinGB !== null && limitGb < filters.limitMinGB) {
            return false;
        }
        if (filters.limitMaxGB !== null && limitGb > filters.limitMaxGB) {
            return false;
        }
    } else if (filters.limitMinGB !== null || filters.limitMaxGB !== null) {
        return false;
    }

    return true;
}

function compareClients(a, b, sort, order) {
    const dir = order === 'desc' ? -1 : 1;

    const compareString = (left, right) => {
        const lv = String(left || '').toLowerCase();
        const rv = String(right || '').toLowerCase();
        if (lv < rv) return -1 * dir;
        if (lv > rv) return 1 * dir;
        return 0;
    };

    const compareNumber = (left, right, nullLast = true) => {
        const ln = left === null || left === undefined || left === 'null' ? null : Number(left);
        const rn = right === null || right === undefined || right === 'null' ? null : Number(right);
        if (ln === null && rn === null) return 0;
        if (ln === null) return nullLast ? 1 * dir : -1 * dir;
        if (rn === null) return nullLast ? -1 * dir : 1 * dir;
        if (ln < rn) return -1 * dir;
        if (ln > rn) return 1 * dir;
        return 0;
    };

    switch (sort) {
        case 'createdAt':
            return compareNumber(a.createdAt, b.createdAt, false);
        case 'expiresAt':
            return compareNumber(a.expiresAt, b.expiresAt, true);
        case 'usedBytes':
            return compareNumber(a.usedBytes, b.usedBytes, false);
        case 'dataLimitBytes':
            return compareNumber(a.dataLimitBytes, b.dataLimitBytes, true);
        case 'status':
            return compareString(a.status, b.status) || compareString(a.name, b.name);
        case 'ipv4':
            return compareString(a.ipv4, b.ipv4) || compareString(a.name, b.name);
        case 'name':
        default:
            return compareString(a.name, b.name);
    }
}

function buildSummary(clients) {
    const all = Object.values(clients || {});
    return {
        total: all.length,
        active: all.filter((c) => c.status === 'active').length,
        disabled: all.filter((c) => c.status === 'disabled').length,
        usedBytes: all.reduce((sum, c) => sum + Number(c.usedBytes || 0), 0),
    };
}

function applyClientFilters(rawResult, query = {}) {
    if (!rawResult || rawResult.success === false) {
        return rawResult;
    }

    const filters = parseListFilters(query);
    const now = Math.floor(Date.now() / 1000);
    const allClients = rawResult.clients || {};
    const summary = buildSummary(allClients);

    let entries = Object.values(allClients).filter((client) => {
        if (filters.status !== 'all' && client.status !== filters.status) {
            return false;
        }
        if (filters.disabledReason && client.disabledReason !== filters.disabledReason) {
            return false;
        }
        if (!matchesSearch(client, filters.search)) {
            return false;
        }
        if (!matchesExpiry(client, filters, now)) {
            return false;
        }
        if (filters.createdBefore !== null && Number(client.createdAt || 0) > filters.createdBefore) {
            return false;
        }
        if (filters.createdAfter !== null && Number(client.createdAt || 0) < filters.createdAfter) {
            return false;
        }
        if (!matchesDataLimit(client, filters)) {
            return false;
        }
        return true;
    });

    entries.sort((a, b) => compareClients(a, b, filters.sort, filters.order));

    const filteredCount = entries.length;
    if (filters.offset > 0) {
        entries = entries.slice(filters.offset);
    }
    if (filters.limit > 0) {
        entries = entries.slice(0, filters.limit);
    }

    const clients = {};
    for (const client of entries) {
        clients[client.name] = client;
    }

    return {
        success: true,
        clients,
        meta: {
            ...summary,
            filtered: filteredCount,
            returned: entries.length,
            offset: filters.offset,
            limit: filters.limit,
        },
        filters: {
            q: filters.search || undefined,
            status: filters.status !== 'all' ? filters.status : undefined,
            reason: filters.disabledReason || undefined,
            expiry: filters.expiry !== 'all' ? filters.expiry : undefined,
            expiresWithinDays: filters.expiry === 'expiring' ? filters.expiresWithinDays : undefined,
            sort: filters.sort,
            order: filters.order,
        },
    };
}

module.exports = {
    parseListFilters,
    applyClientFilters,
    buildSummary,
};
