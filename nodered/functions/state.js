// GET /state: link model counters, used to check point accounting (C8).
const st = flow.get('st');
msg.payload = st ? { run: st.run, up: st.up, clock: st.clock, buffered_now: st.bufPts, n: st.n } : { configured: false };
msg.statusCode = 200;
return msg;
