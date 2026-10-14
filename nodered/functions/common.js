// Shared helpers, prepended to every function body by scripts/build_flows.py.
function mulberry32(st, key) {
    key = key || 'rs';   // 'rs' drives the link chain, 'rb' the backfill shuffle: never mix them
    st[key] = (st[key] + 0x6D2B79F5) | 0;
    let t = Math.imul(st[key] ^ (st[key] >>> 15), 1 | st[key]);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
function toLines(b) {
    const pre = 'sensor,run=' + b.run + ',stream=' + b.stream + ' ';
    const n = b.t.length, nf = b.fields.length, L = new Array(n);
    for (let i = 0; i < n; i++) {
        let f = '';
        for (let j = 0; j < nf; j++) f += (j ? ',' : '') + b.fields[j] + '=' + b.v[j][i];
        L[i] = pre + f + ' ' + b.t[i];
    }
    return L;
}
