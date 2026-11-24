const test = require('node:test');
const assert = require('node:assert/strict');
const {InfluxStore} = require('../../ingestion/store');
test('Influx SQL request supplies database and JSON format in body', async () => {
  const original = global.fetch;
  global.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    assert.equal(body.db, 'adwiser_probe_dev');
    assert.equal(body.format, 'json');
    return {ok:true,json:async()=>[{payload:JSON.stringify({hostname:'example.com',port:443,status:'timeout',syn_ack_ms:null})}]};
  };
  try {
    const rows = await new InfluxStore({url:'http://localhost:18181',database:'adwiser_probe_dev',token:'test'}).all();
    assert.equal(rows[0].port,443);
    assert.equal(rows[0].syn_ack_ms,null);
  } finally { global.fetch = original; }
});
