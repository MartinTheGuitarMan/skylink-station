// After the edge call returns: deliver the ordered live messages (link labels, replay notice, live batch)
// to the base arms in ONE request, so they cannot overtake each other, then answer the simulator.
const list = msg.baseMsgs || [];
if (!list.length) return [null, msg];
msg.method = 'POST';
msg.url = env.get('EDGE_URL') + '/base/ingest';
msg.payload = { msgs: list };
return [msg, null];
