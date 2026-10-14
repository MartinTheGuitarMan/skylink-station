// POST /config  (from the simulator, at run start or resume). Resets the link model.
const c = msg.payload;
const D = { mean_up_s: 14400, mean_down_s: 2400, max_buffer_points: 3000000,
            backfill_chunk_points: 5000, backfill_shuffle_window: 8 };
const cfg = {};
for (const k in D) cfg[k] = (c[k] !== undefined) ? c[k] : D[k];
const st = {
    run: c.run, epoch_us: c.epoch_us, cfg: cfg,
    rs: ((c.seed * 2654435761) ^ 0x9E3779B9) | 0,
    rb: ((c.seed * 40503) ^ 0x85EBCA6B) | 0,
    clock: 0, up: true, buffer: [], bufPts: 0,
    n: { in: 0, live: 0, buffered: 0, backfilled: 0, dropped: 0, outages: 0 }
};
// Replay the Markov chain up to the resume point, so the outage schedule is identical after a restart.
const resume = c.resume_s || 0;
while (st.clock < resume) {
    st.clock++;
    const u = mulberry32(st);
    if (st.up) { if (u < 1 / cfg.mean_up_s) st.up = false; }
    else if (u < 1 / cfg.mean_down_s) st.up = true;
}
flow.set('st', st);
const ts = st.epoch_us + st.clock * 1000000;
msg.payload = { ok: true, up: st.up, clock: st.clock };
msg.statusCode = 200;
msg.influx = 'skylink,run=' + st.run + ' up=' + (st.up ? 1 : 0) + 'i,buffered=0i,dropped=0i ' + ts;
return [msg, { payload: msg.influx }];
