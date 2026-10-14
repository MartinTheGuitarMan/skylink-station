// Runs nodered/functions/{config,gate}.js outside Node-RED. Input: JSON on stdin {seed, resume_s, cfg, seconds, hz}.
import fs from 'node:fs';
const fdir = new URL('../nodered/functions/', import.meta.url);
const read = (n) => fs.readFileSync(new URL(n + '.js', fdir), 'utf8');
const common = read('common');
const mk = (n) => new Function('msg', 'flow', 'env', 'node', common + '\n' + read(n));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = {};
const flow = { get: (k) => store[k], set: (k, v) => { store[k] = v; } };
const cfgFn = mk('config'), gate = mk('gate');
const ENV = { get: (k) => 'http://stub/' + k };
const epoch = 1767225600000000;
cfgFn({ payload: { run: 'r', seed: input.seed, epoch_us: epoch, resume_s: input.resume_s || 0, ...input.cfg } }, flow, ENV, {});
const start = input.resume_s || 0;
const trace = [];            // link transitions (event seconds)
const backfillOrder = [];    // first timestamp of each backfill chunk, in emission order
let liveOut = 0, bfOut = 0, emitted = 0;
for (let s = start; s < start + input.seconds; s++) {
    const t = [], v = [[]];
    for (let i = 0; i < input.hz; i++) { t.push(epoch + s * 1000000 + i * Math.floor(1000000 / input.hz)); v[0].push(s + i / 100); }
    emitted += t.length;
    const O = gate({ payload: { run: 'r', stream: 'temp', fields: ['value'], t, v } }, flow, ENV, {});
    for (const m of O[1]) {
        if (typeof m.payload === 'string') trace.push(m.payload.split(' ')[1].split(',')[0] + '@' + (Number(m.payload.split(' ').pop()) - epoch) / 1e6);
        else liveOut += m.payload.t.length;
    }
    for (const m of O[3]) { bfOut += m.payload.t.length; backfillOrder.push(m.payload.t[0]); }
}
const st = flow.get('st');
console.log(JSON.stringify({ trace, liveOut, bfOut, emitted, n: st.n, bufPts: st.bufPts, up: st.up, backfillOrder }));
