const STATUSES = new Set(['ok','dns_error','timeout','connection_refused','network_error','capture_incomplete','skipped']);
function validateEvent(e) {
  if (!e || e.schema_version !== 1 || !e.attempt_id || !e.probe_id || !e.hostname || !Number.isInteger(e.port) || !STATUSES.has(e.status)) throw new Error('invalid website probe event');
  if (e.status === 'ok' && (typeof e.syn_ack_ms !== 'number' || e.syn_ack_ms < 0)) throw new Error('successful event requires non-negative syn_ack_ms');
  if (e.status !== 'ok' && e.syn_ack_ms !== null) throw new Error('failed event must have null syn_ack_ms');
  return e;
}
module.exports = { validateEvent };
