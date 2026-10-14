// Build the InfluxDB write request (bucket raw, microsecond precision) from a batch or a ready line string.
const lines = (typeof msg.payload === 'string') ? msg.payload : toLines(msg.payload).join('\n');
return {
    method: 'POST',
    url: env.get('INFLUX_URL') + '/api/v2/write?org=' + env.get('INFLUX_ORG') + '&bucket=raw&precision=us',
    headers: { Authorization: 'Token ' + env.get('INFLUX_TOKEN') },
    payload: lines
};
