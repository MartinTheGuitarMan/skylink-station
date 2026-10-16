// The Skylink gate. One message = one sensor batch {run, stream, fields, t[us], v[[...]]}.
// Outputs: 0 edge tap (original msg, carries the HTTP response), 1 influx live, 2 base live,
//          3 influx backfill (rate limited), 4 base backfill (rate limited).
const p = msg.payload;
const st = flow.get('st');
const base = (b) => ({ payload: b, method: 'POST', url: env.get('EDGE_URL') + '/base/ingest' });
msg.method = 'POST'; msg.url = env.get('EDGE_URL') + '/edge/ingest';   // http request nodes take url from msg
const O = [[msg], [], [], [], []];
const npts = p.t.length;
if (!st || st.run !== p.run) {            // no link model configured: transparent pass-through
    O[1].push({ payload: p });
    O[2].push(base(p));
    return O;
}
st.n.in += npts;
const cfg = st.cfg;
const link = (up, ts) => ({ payload: 'skylink,run=' + st.run + ' up=' + (up ? 1 : 0) + 'i,buffered=' + st.bufPts +
                            'i,dropped=' + st.n.dropped + 'i ' + ts });
// advance the Markov chain in event time to the end of this batch
const endS = Math.floor((p.t[npts - 1] - st.epoch_us) / 1000000);
let backfill = false;
while (st.clock < endS) {
    st.clock++;
    const u = mulberry32(st);
    const ts = st.epoch_us + st.clock * 1000000;
    if (st.up) {
        if (u < 1 / cfg.mean_up_s) {
            st.up = false; st.n.outages++; O[1].push(link(false, ts));
            O[2].push(base({ run: st.run, ctrl: 'link', up: 0, t_us: ts }));      // labelling channel for the scorer
        }
    } else if (u < 1 / cfg.mean_down_s) {
        st.up = true; backfill = true; O[1].push(link(true, ts));
        O[2].push(base({ run: st.run, ctrl: 'link', up: 1, t_us: ts }));
    }
}
if (!st.up) {
    st.buffer.push(p); st.bufPts += npts; st.n.buffered += npts;
    while (st.bufPts > cfg.max_buffer_points && st.buffer.length > 1) {   // finite local storage: drop oldest
        const d = st.buffer.shift(); st.bufPts -= d.t.length; st.n.dropped += d.t.length;
    }
}
if (backfill && st.up && st.buffer.length) {
    // merge buffered batches per stream into chunks, then shuffle chunk order inside windows
    const acc = {}, chunks = [];
    for (const b of st.buffer) {
        let a = acc[b.stream];
        if (!a) { a = acc[b.stream] = { run: b.run, stream: b.stream, fields: b.fields, t: [], v: b.fields.map(() => []) }; }
        a.t = a.t.concat(b.t);
        b.v.forEach((col, j) => { a.v[j] = a.v[j].concat(col); });
        if (a.t.length >= cfg.backfill_chunk_points) { chunks.push(a); acc[b.stream] = null; }
    }
    for (const k in acc) if (acc[k]) chunks.push(acc[k]);
    const W = Math.max(1, cfg.backfill_shuffle_window);
    const out = [];
    for (let i = 0; i < chunks.length; i += W) {
        const w = chunks.slice(i, i + W);
        for (let j = w.length - 1; j > 0; j--) { const r = Math.floor(mulberry32(st, 'rb') * (j + 1)); const x = w[j]; w[j] = w[r]; w[r] = x; }
        out.push(...w);
    }
    // link-layer notice that a replay of `n` chunks follows; sent before the first live batch after reconnect
    O[2].push(base({ run: st.run, ctrl: 'bf_start', bf_id: st.clock, n: out.length }));
    for (const c of out) {
        c.bf = true; c.bf_id = st.clock; c.bf_n = out.length;
        O[3].push({ payload: c }); O[4].push(base(c)); st.n.backfilled += c.t.length;
    }
    st.buffer = []; st.bufPts = 0;
}
if (st.up) {
    O[1].push({ payload: p }); O[2].push(base(p));
    st.n.live += npts;
}
return O;
