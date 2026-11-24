const fs = require('fs');
const {execFileSync, spawn} = require('child_process');
const tokenFile = 'data/dev-token.json';
if (!fs.existsSync(tokenFile)) {
  const result = execFileSync('influxdb3', ['create','token','--admin','--host','http://127.0.0.1:18181','--format','json']);
  fs.writeFileSync(tokenFile, result, {mode: 0o600});
}
const token = JSON.parse(fs.readFileSync(tokenFile)).token;
if (!token) throw Error('No development token returned');
const env = {...process.env, INFLUX_URL:'http://127.0.0.1:18181', INFLUX_DATABASE:'adwiser_probe_dev', INFLUX_TOKEN:token};
if (process.argv[2] === 'setup') {
  execFileSync('influxdb3',['create','database','--host',env.INFLUX_URL,'adwiser_probe_dev'], {env:{...env,INFLUXDB3_AUTH_TOKEN:token},stdio:'inherit'});
} else {
  const child = spawn(process.execPath,[process.argv[2] === 'api' ? 'api/server.js' : 'ingestion/server.js'],{env,stdio:'inherit'});
  for (const signal of ['SIGINT','SIGTERM']) process.on(signal,()=>child.kill(signal));
}
