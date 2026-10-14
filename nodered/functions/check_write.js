if (msg.statusCode !== 204) node.warn('influx write failed: ' + msg.statusCode + ' ' + msg.payload);
return null;
