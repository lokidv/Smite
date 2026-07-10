const GB_BYTES = 1024 ** 3;

function pickFirst(source, keys) {
    if (!source) {
        return undefined;
    }
    for (const key of keys) {
        const value = source[key];
        if (value !== undefined && value !== null && value !== '') {
            return value;
        }
    }
    return undefined;
}

function toGbFromBytes(bytesValue) {
    const bytes = Number(bytesValue);
    if (!Number.isFinite(bytes) || bytes <= 0) {
        return null;
    }
    return bytes / GB_BYTES;
}

function normalizeGbValue(value) {
    if (value === undefined || value === null || value === '') {
        return null;
    }
    const gb = Number(value);
    if (!Number.isFinite(gb) || gb < 0) {
        return null;
    }
    return gb;
}

function resolveCreateVolume(source = {}) {
    const bytesValue = pickFirst(source, [
        'dataLimitBytes',
        'data_limit_bytes',
        'volumeBytes',
        'volume_bytes',
    ]);
    const bytesGb = toGbFromBytes(bytesValue);
    if (bytesGb !== null) {
        return { dataLimitGB: bytesGb, explicitLimit: true };
    }

    const gbValue = pickFirst(source, [
        'dataLimitGB',
        'data_limit_gb',
        'volumeGB',
        'volume_gb',
        'volume',
        'dataLimit',
        'data_limit',
    ]);
    const gb = normalizeGbValue(gbValue);
    if (gb !== null) {
        return { dataLimitGB: gb, explicitLimit: true };
    }

    if (pickFirst(source, ['unlimited', 'noLimit', 'no_limit']) === '1'
        || source.unlimited === true
        || source.unlimited === 1) {
        return { dataLimitGB: 0, explicitLimit: true };
    }

    return { dataLimitGB: undefined, explicitLimit: false };
}

function resolvePurchaseVolume(source = {}) {
    const bytesValue = pickFirst(source, [
        'addDataBytes',
        'purchaseDataBytes',
        'dataLimitBytes',
        'data_limit_bytes',
        'volumeBytes',
        'volume_bytes',
    ]);
    const bytesGb = toGbFromBytes(bytesValue);
    if (bytesGb !== null) {
        return bytesGb;
    }

    const gbValue = pickFirst(source, [
        'addDataGB',
        'add_data_gb',
        'purchaseDataGB',
        'purchase_data_gb',
        'dataLimitGB',
        'data_limit_gb',
        'volumeGB',
        'volume_gb',
        'volume',
    ]);
    const gb = normalizeGbValue(gbValue);
    return gb === null ? undefined : gb;
}

function resolveSetVolume(source = {}) {
    const bytesValue = pickFirst(source, [
        'setDataLimitBytes',
        'set_data_limit_bytes',
    ]);
    const bytesGb = toGbFromBytes(bytesValue);
    if (bytesGb !== null) {
        return bytesGb;
    }

    const gbValue = pickFirst(source, [
        'setDataLimitGB',
        'set_data_limit_gb',
        'setLimitGB',
        'set_limit_gb',
    ]);
    const gb = normalizeGbValue(gbValue);
    return gb === null ? undefined : gb;
}

function resolveUpdateVolume(source = {}) {
    const setDataLimitGB = resolveSetVolume(source);
    const purchaseGb = resolvePurchaseVolume(source);
    return {
        setDataLimitGB,
        addDataGB: setDataLimitGB !== undefined ? undefined : purchaseGb,
    };
}

module.exports = {
    resolveCreateVolume,
    resolveUpdateVolume,
    resolvePurchaseVolume,
    resolveSetVolume,
};
