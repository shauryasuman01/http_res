const fs = require('fs');
const path = require('path');

function loadConfig(file = path.join(__dirname, '..', 'config', 'websites.json')) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const targets = (raw.targets || []).map(t => typeof t === 'string' ? { hostname: t, port: 443 } : t)
    .map(t => ({ hostname: String(t.hostname).trim().toLowerCase(), port: Number(t.port || 443) }));
  const seen = new Set();
  for (const t of targets) {
    if (!/^[a-z0-9.-]+$/.test(t.hostname) || t.hostname.length > 253) throw new Error(`invalid hostname: ${t.hostname}`);
    if (!Number.isInteger(t.port) || t.port < 1 || t.port > 65535) throw new Error(`invalid port for ${t.hostname}`);
    const key = `${t.hostname}:${t.port}`; if (seen.has(key)) throw new Error(`duplicate target: ${key}`); seen.add(key);
  }
  return { interval_seconds: Number(raw.interval_seconds || 30), timeout_seconds: Number(raw.timeout_seconds || 5), concurrency: Number(raw.concurrency || 5), targets };
}
module.exports = { loadConfig };
