const fs=require('fs'), path=require('path');
const key=e=>JSON.stringify([e.probe_id,e.hostname,e.port]);
class FileStore {
  constructor(file){this.file=file;fs.mkdirSync(path.dirname(file),{recursive:true});}
  async all(){const rows=new Map();if(fs.existsSync(this.file)) for(const line of fs.readFileSync(this.file,'utf8').split('\n').filter(Boolean)){const e=JSON.parse(line);rows.set(key(e),e);}return [...rows.values()];}
  async write(events){const rows=new Map((await this.all()).map(e=>[key(e),e]));let count=0;for(const e of events){const old=rows.get(key(e));if(old&&(old.attempt_id===e.attempt_id||old.observed_at>e.observed_at))continue;rows.set(key(e),e);count++;}if(count){fs.writeFileSync(this.file+'.tmp',[...rows.values()].map(JSON.stringify).join('\n')+'\n');fs.renameSync(this.file+'.tmp',this.file);}return count;}
}
const tag=v=>String(v).replace(/\\/g,'\\\\').replace(/[ ,=]/g,'\\$&');
const field=v=>'"'+String(v).replace(/\\/g,'\\\\').replace(/"/g,'\\"')+'"';
class InfluxStore {
  constructor({url,database,token}){this.url=url.replace(/\/$/,'');this.database=database;this.token=token;}
  async write(events){if(!events.length)return 0;const lines=events.map(e=>`website_probe_latest,hostname=${tag(e.hostname)},port=${e.port},probe_id=${tag(e.probe_id)} payload=${field(JSON.stringify(e))} 0`);const r=await fetch(`${this.url}/api/v3/write_lp?db=${encodeURIComponent(this.database)}&precision=nanosecond`,{method:'POST',headers:{Authorization:`Bearer ${this.token}`,'Content-Type':'text/plain'},body:lines.join('\n')});if(!r.ok)throw Error(`Influx write ${r.status}: ${await r.text()}`);return events.length;}
  async all(){const r=await fetch(`${this.url}/api/v3/query_sql`,{method:'POST',headers:{Authorization:`Bearer ${this.token}`,'Content-Type':'application/json'},body:JSON.stringify({db:this.database,format:'json',q:'SELECT * FROM website_probe_latest'})});if(!r.ok)throw Error(`Influx query ${r.status}: ${await r.text()}`);return (await r.json()).map(row=>JSON.parse(row.payload));}
}
module.exports={FileStore,InfluxStore};
