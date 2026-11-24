# ADWISER website TCP latency backend

This standalone prototype measures TCP SYN-to-SYN-ACK latency from the machine running the probe. It serves JSON for a separately developed dashboard; no frontend is included.

The current storage mode **updates one logical current record per probe ID, hostname and port**. It does not retain new historical samples. Existing data in the older `website_probe` measurement is untouched but no longer read.

## Architecture

```text
config/websites.json
        ↓
Python scheduler → DNS lookup → TCP socket connection
        ↕
One Scapy packet listener on the selected Linux interface
        ↓ JSON event, ZeroMQ PUB (bind)
Node.js ingestion, ZeroMQ SUB (connect)
        ↓ validation and write
InfluxDB 3 Core / adwiser_probe_dev / website_probe_latest
        ↓ SQL query
Node.js HTTP read API → future dashboard polls for updates
```

| Directory/file | Responsibility |
| --- | --- |
| `probe/probe.py` | DNS, TCP attempts, packet capture and publishing |
| `probe/matcher.py` | Capture-independent matching/timing helpers |
| `probe/scheduler.py` | Spread attempts within each round, limit concurrency |
| `config/websites.json` | Editable targets and sampling settings |
| `contracts/` | Event schema and success/failure examples |
| `ingestion/server.js` | Receive, validate and write events |
| `ingestion/store.js` | InfluxDB and local-file storage adapters |
| `api/server.js`, `api/queries.js` | HTTP server, filtering and statistics |
| `api/openapi.yaml` | Initial API specification; not exhaustive validation documentation |
| `deploy/live.js` | Development token/database setup and service launcher |
| `tests/` | Unit tests and synthetic file-store smoke test |

## Measurement and update logic

The probe resolves the hostname before connecting and selects the first address returned by the operating system. Its listener matches the reversed IP/port tuple and TCP acknowledgment of the SYN sequence number. Packet capture timestamps are converted to integer nanoseconds:

```text
syn_ack_ms = (syn_ack_capture_ns - first_syn_capture_ns) / 1,000,000
```

DNS resolution, TLS negotiation, HTTP responses and page loading are outside this interval. In WSL, the measurement originates in the WSL network environment; it is not a measurement captured on a physical ADWISER gateway interface.

Events include a UUID attempt ID, probe ID, hostname, port, resolved IP, UTC observation time, status and latency. Capture nanoseconds are JSON strings. Failure latency is null. Supported contract statuses are `ok`, `dns_error`, `timeout`, `connection_refused`, `network_error`, `capture_incomplete` and `skipped`.

Influx writes use stable tags (`hostname`, `port`, `probe_id`) and a fixed storage timestamp of zero. The entire event is stored in a string field named `payload`. Rewriting the same point replaces that payload, including clearing previous latency after a failure. The real observation time is `payload.observed_at`, not Influx's `time` column. Do not apply time retention based on this fixed timestamp.

With one probe and 50 targets, repeated rounds keep 50 logical current records. A new probe ID or hostname/port pair creates another record. Old removed targets are not automatically deleted. Internal Influx write logs and storage can grow despite the logical row count remaining stable. The Influx adapter does not reject out-of-order older events.

Example of one measurement at each boundary (illustrative timestamps):

```json
{"schema_version":1,"attempt_id":"demo-1","probe_id":"adwiser-probe-dev","hostname":"example.com","port":443,"resolved_ip":"192.0.2.10","observed_at":"2026-11-24T00:00:00.000Z","first_syn_capture_ns":"100000000","syn_ack_capture_ns":"142000000","syn_ack_ms":42,"syn_retransmits":0,"status":"ok","error_reason":null}
```

The database record has measurement `website_probe_latest`, tags `example.com/443/adwiser-probe-dev`, storage timestamp `0`, and the above JSON in `payload`. `/latest` returns that decoded object in its `results` array. A later failure replaces it with a new event containing null latency.

## Ubuntu: installation

Use Ubuntu 24.04 or a comparable Linux installation with Python 3, a Node.js version supporting global `fetch` and `node:test` (18+), npm, and InfluxDB **3 Core**. The observed development versions were Node 26.13.1, Python 3.12.3 and InfluxDB 3 Core 3.12.3; other versions have not been comprehensively tested.

### 1. Open the project directory

Copy or clone this project to your machine, then open its root. For example:

```bash
cd ~/http_res
```

All commands below assume this working directory, including commands in additional terminals. On the original machine it is `/home/shaurya/http_res`.

### 2. Install dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip libpcap-dev tcpdump iproute2 curl ca-certificates nodejs npm
node --version
npm --version
python3 --version
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install scapy pyzmq
```

If your Ubuntu repository provides Node older than 18, install a supported Node release before `npm ci`. Check that ZeroMQ loads:

```bash
node -e "require('zeromq'); console.log('ZeroMQ ready')"
```

### 3. Install InfluxDB 3 Core

If `influxdb3 --version` already works, skip installation. Otherwise use the official installer, downloaded to a temporary directory:

```bash
probe_install_dir=$(mktemp -d)
curl -fsSL https://www.influxdata.com/d/install_influxdb3.sh -o "$probe_install_dir/install_influxdb3.sh"
less "$probe_install_dir/install_influxdb3.sh"
sh "$probe_install_dir/install_influxdb3.sh"
```

Choose Core if prompted. Follow the installer's PATH instructions, open a new terminal if necessary, return to the project root, and verify:

```bash
command -v influxdb3
influxdb3 --version
```

See the [official InfluxDB installation instructions](https://docs.influxdata.com/influxdb3/core/install/) for distribution packages and alternate installation methods. This walkthrough uses the native binary, not the bundled Docker Compose file. That Compose file is an older placeholder and does not implement this token/setup workflow.

## Ubuntu: start the services

Keep four terminal tabs open. These are foreground processes; closing their terminals can stop the backend. Start them in this order.

### Terminal 1: database

```bash
cd ~/http_res
mkdir -p data
influxdb3 serve \
  --node-id adwiser-probe-dev \
  --object-store file \
  --data-dir "$PWD/data/influx" \
  --http-bind 127.0.0.1:18181
```

Wait for the server startup message. Port `18181` isolates this instance from an existing database on `8181`. Do not start another instance using the same directory or port.

### Terminal 2: first-time database setup, then ingestion

```bash
cd ~/http_res
node deploy/live.js setup
node deploy/live.js ingestion
```

Run `setup` once for a fresh database, not on every restart. It creates a development admin token, saves it to `data/dev-token.json` with mode `0600`, and creates only `adwiser_probe_dev`. Keep this credential private. If the database already exists, skip setup and start ingestion directly. Preserve the token file together with the database data across restarts.

The launcher uses `127.0.0.1:18181` and `adwiser_probe_dev` explicitly; it overrides any `INFLUX_*` values inherited from the shell.

### Terminal 3: API

```bash
cd ~/http_res
node deploy/live.js api
```

The API listens on `127.0.0.1:8090`. Check that it responds:

```bash
curl -fsS http://127.0.0.1:8090/health
```

Expected: `{"ok":true}`. This only checks HTTP availability, not database readiness. Data endpoints can fail before the first successful write creates `website_probe_latest`.

### Terminal 4: live probe

Find the interface carrying traffic to the targets:

```bash
ip -br address
ip route show default
```

Use the device following `dev` in the default route, such as `enp3s0`, `wlp46s0` or `eth0`. Replace `YOUR_INTERFACE` below:

```bash
cd ~/http_res
sudo env \
  PROBE_INTERFACE=YOUR_INTERFACE \
  PROBE_ID=adwiser-probe-dev \
  ZMQ_BIND_ENDPOINT=tcp://127.0.0.1:5557 \
  "$PWD/.venv/bin/python" probe/probe.py
```

Enter your Ubuntu password locally when sudo prompts. Capture requires Linux raw-packet privileges; the other three services run without sudo. The command runs only this probe process as root. Do not grant capabilities to the shared system Python interpreter. A more restricted service deployment would use a dedicated account and scoped capture capabilities; no such service unit is shipped yet.

The probe normally publishes silently. A shell that stays open without new text does not imply failure. Allow approximately one full sampling round, then inspect the API.

### Verify real measurements

```bash
curl -fsS http://127.0.0.1:8090/api/website-probes/latest | python3 -m json.tool
curl -fsS 'http://127.0.0.1:8090/api/website-probes/history?hostname=example.com&port=443&limit=10' | python3 -m json.tool
```

Look for `status: "ok"`, numeric `syn_ack_ms`, and an advancing `observed_at`. Repeat after a round: the observation/attempt ID should change while the number of current records remains stable. Public sites may legitimately fail depending on DNS, firewall or network conditions.

### Stop and restart

Press Ctrl+C in each service terminal, stopping the probe first, then ingestion, API and database. On the next run, repeat the four startup commands but skip `node deploy/live.js setup`. Keep `data/` and its token. Processes do not currently auto-start after boot; unattended hosting needs systemd or another supervisor.

## Windows: run the complete backend through WSL2 Ubuntu

The current Python probe uses Linux `AF_PACKET` sockets. Native Windows Python is **not supported by this implementation**, even if Scapy/Npcap is installed. Run all four components inside WSL2 Ubuntu using the Linux steps above. This Windows procedure is documented but has not been executed in this project's verification environment.

### 1. Install WSL2

Open PowerShell **as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart Windows if requested, launch Ubuntu, and create its Linux username/password. In PowerShell, verify and update:

```powershell
wsl --update
wsl --list --verbose
```

The distribution should show version `2`. If needed:

```powershell
wsl --set-version Ubuntu-24.04 2
```

If the name differs, use the exact name shown by `wsl --list --verbose`. See [Microsoft's WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install) for supported Windows builds and installation troubleshooting.

### 2. Put the source in the Linux filesystem

In Ubuntu, copy your project from Windows, replacing `YOUR_WINDOWS_USER` and the source directory:

```bash
cp -r /mnt/c/Users/YOUR_WINDOWS_USER/projects/http_res ~/http_res
cd ~/http_res
```

Prefer copying source files only. Do not transfer a Windows `node_modules`, virtual environment, or another machine's development credentials/database. Install Linux dependencies afresh. A source checkout directly into `~/http_res` is also suitable.

### 3. Install and start inside Ubuntu

Follow all Ubuntu installation and startup sections above. Open four Ubuntu tabs in Windows Terminal, all in `~/http_res`. Install Node, Python and InfluxDB **inside Ubuntu**; Windows installations do not replace these dependencies.

Use `ip route show default` inside WSL to select the probe interface, commonly `eth0`. Use the Linux sudo command from Terminal 4. All service-to-service addresses remain localhost because the components share the same Ubuntu instance.

### 4. Access from Windows

Open this URL in your Windows browser:

```text
http://localhost:8090/api/website-probes/latest
```

Or use PowerShell:

```powershell
Invoke-RestMethod http://localhost:8090/health
Invoke-RestMethod http://localhost:8090/api/website-probes/latest
```

WSL shutdown or Windows sleep interrupts probing. VPNs and WSL networking can affect route selection and timing. For measurements representing an actual ADWISER gateway, run the probe on that Linux gateway.

## Access from other devices on the local network

### Ubuntu host

Stop only the existing API process with Ctrl+C, then restart it with:

```bash
API_HOST=0.0.0.0 API_PORT=8090 node deploy/live.js api
hostname -I
```

On another device, open `http://LAN_IP:8090/api/website-probes/latest`. Use the IP of the host's LAN adapter, not localhost or a container bridge. If UFW is active, allow only your actual LAN subnet; this is an example to adapt:

```bash
sudo ufw status
sudo ufw allow from 192.168.1.0/24 to any port 8090 proto tcp
```

Keep InfluxDB and ZeroMQ on loopback. The API currently has no authentication, HTTPS or CORS configuration. Use it only on a trusted network; for authenticated hosting add a reverse proxy/session integration. A separate-origin dashboard requires CORS or a same-origin proxy. No router internet port forwarding is required.

### Windows host with WSL2 NAT networking

First restart the API inside Ubuntu with `API_HOST=0.0.0.0` as above. Then in Administrator PowerShell:

```powershell
wsl -d Ubuntu-24.04 hostname -I
ipconfig
```

Identify the WSL IPv4 address and Windows LAN IPv4 address. Set the following values to those addresses, then create a port proxy and firewall rule:

```powershell
$probeWslIp = "172.20.10.2"       # replace with current WSL IPv4
$probeLanIp = "192.168.1.50"      # replace with Windows LAN IPv4
netsh interface portproxy add v4tov4 listenaddress=$probeLanIp listenport=8090 connectaddress=$probeWslIp connectport=8090
New-NetFirewallRule -DisplayName "ADWISER API LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8090 -Profile Private -RemoteAddress LocalSubnet
```

Other LAN devices use the Windows LAN address. WSL IP changes can require updating the proxy. Remove this exposure when no longer needed:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=$probeLanIp listenport=8090
Remove-NetFirewallRule -DisplayName "ADWISER API LAN"
```

These commands assume NAT networking and a trusted Private Windows network. Mirrored networking has different firewall requirements; consult [Microsoft's WSL networking documentation](https://learn.microsoft.com/en-us/windows/wsl/networking) for that alternative.

## Configuration reference

Edit `config/websites.json`, then restart the probe and API:

```json
{
  "interval_seconds": 30,
  "timeout_seconds": 5,
  "concurrency": 5,
  "targets": ["example.com", {"hostname": "localhost", "port": 8443}]
}
```

For a localhost target, run a TCP listener on the chosen port and use capture interface `lo`. Do not mix localhost and internet targets when testing a single-interface capture setup.

The shipped configuration has 50 hosts and port 443 by default. Node's loader normalizes names and rejects duplicate hostname/port pairs, but Python currently reads configuration separately. Use lowercase valid hostnames, explicit valid object ports, and positive interval/timeout/concurrency values.

| Variable | Current behavior |
| --- | --- |
| `API_HOST`, `API_PORT` | Defaults `127.0.0.1`, `8090` |
| `INFLUX_URL`, `INFLUX_DATABASE`, `INFLUX_TOKEN` | Used by direct Node entrypoints; launcher supplies its own values |
| `ZMQ_ENDPOINT` | Subscriber address; default `tcp://127.0.0.1:5557` |
| `ZMQ_BIND_ENDPOINT` | Publisher bind address; set localhost explicitly as above |
| `PROBE_INTERFACE` | Capture interface; code default `eth0` |
| `PROBE_ID` | Stable identity; default `adwiser-probe-dev` |
| `PROBE_TIMEOUT_SECONDS` | Overrides probe connection timeout |
| `WEBSITES_CONFIG` | Probe-only alternate config path; API still uses default config |
| `QUEUE_PATH`, `STORE_PATH` | Failed-write file and fallback local store |

`PROBE_INTERVAL_SECONDS` and `PROBE_CONCURRENCY` in `.env.example` are not wired into the probe; edit JSON instead. `.env` is not loaded automatically. Direct entrypoints (`node api/server.js`, `node ingestion/server.js`) require exported environment variables and fall back to a local file if Influx URL/token are missing or the token is a placeholder. Use `deploy/live.js` for the documented database workflow.

## API contract

| GET route | Response/behavior |
| --- | --- |
| `/health` | HTTP liveness only |
| `/api/website-probes/targets` | Targets, interval, timeout, concurrency |
| `/api/website-probes/latest` | `results`: newest record per configured target, including failures or `never_probed` |
| `/api/website-probes/history` | `items`, `total`, `limit`, `offset`; current records only |
| `/api/website-probes/summary` | Per-target current success/failure/skip counts and successful latency statistics |

History accepts `hostname`, `port`, `probe_id`, `from`, `to`, `limit` (default 100, capped at 500) and `offset`. Use UTC ISO timestamps for inclusive time filters. Ordering is descending observation time, then attempt ID. Summary currently applies only `from`/`to` filters. Latest chooses the newest target record across probe IDs.

Statistics exclude failures and return null for no successful samples. Percentiles use linear interpolation. With one current record per target/probe, these are **not historical reliability or latency statistics**; a single successful sample makes all latency statistics equal. The frontend must poll; no push updates are implemented.

## Tests and verification evidence

The included launcher runs the full automated test suite:

```bash
./run-all.sh test
```

It can also start the complete local backend in one terminal. Pass the Linux
interface used by the default route; the probe still runs with `sudo` because
packet capture requires raw-packet privileges:

```bash
./run-all.sh backend eth0
```

Set `PROBE_INTERFACE` instead of passing the interface if preferred. Press
Ctrl+C to stop the probe, API, ingestion process and database together. The
launcher runs `node deploy/live.js setup` only on a fresh database; it skips
setup automatically after the token file has been created.

Run from the project root in Ubuntu or WSL:

```bash
npm test
.venv/bin/python -m unittest discover -s tests/python
env -u INFLUX_URL -u INFLUX_TOKEN npm run smoke
```

The smoke test uses a synthetic 42 ms event and a temporary file store. Although it starts a local TCP listener, it does not connect to it or capture a real handshake. It does not verify ZeroMQ or InfluxDB. Public websites are not required for the automated tests.

Previously verified on the development Linux host: unit tests, synthetic smoke, real public-target events through ZeroMQ into InfluxDB, HTTP 200 on all four read routes, and 50 logical current records after writing the same 50 targets twice. Windows/WSL instructions have not been executed here. A controlled-target real-capture automated smoke test is still missing.

## Troubleshooting

| Symptom | Check/action |
| --- | --- |
| `Operation not permitted` | Start the probe with the documented sudo command |
| Missing `scapy` or `zmq` | Install using `.venv/bin/python -m pip`; run that exact interpreter under sudo |
| Filter/libpcap error | Install `libpcap-dev`, confirm interface with `ip -br address` |
| `Address already in use` | Inspect `ss -ltnp`; stop the matching existing service before restarting |
| API health works but data fails | Check database, token and ingestion terminal; no table exists before the first successful write |
| `Influx query 400` | Inspect server error; SQL POST requires `db` in JSON (fixed in current code) |
| Token error/HTTP 401 | Confirm `data/dev-token.json` belongs to the running development database; do not delete credentials as a blind reset |
| No new observations | Check probe process, selected interface, DNS, subscriber endpoint and ingestion errors |
| `capture_incomplete` | Socket connected but capture lacked the pair; check route/interface and known capture limitations |
| Browser shows JSON | Expected: there is no dashboard frontend |
| LAN cannot connect | Check API bind address, host IP, firewall and wireless client isolation; on WSL also check port proxy |

## Known limitations and integration work

- Scheduling spreads attempts within a round but waits for completion before the next round, so it is not globally drift-free.
- Capture has no explicit readiness barrier, does not pre-register bound connection tuples, does not clean up capture state, and does not count retransmissions accurately. Async futures are touched from the capture thread without thread-safe coordination.
- Capacity exhaustion currently produces an invalid status (`capacity_exhausted` instead of `skipped`) and is rejected by ingestion.
- PUB/SUB can lose messages before receipt. Failed writes are appended to disk, but automatic retry/replay and batching are not implemented. Counters are in memory and have no HTTP metrics endpoint.
- API validation/range caps are incomplete, queries load all current rows, and database failures are reported as HTTP 400. No session protection or mountable authenticated router is implemented.
- No service supervisor, boot startup, or comprehensive graceful-shutdown handling is included.

For ADWISER integration, adapt `ingestion.ingest` to its actual framing and receiver, reuse its writer/retry infrastructure, and refactor the HTTP routes to mount behind its existing session middleware/database client. The initial standalone implementation did not inspect the separate ADWISER repository, so compatibility has not been verified. Switch database settings explicitly after development verification. Historical migration is a separate optional task; current update-only storage intentionally does not preserve new history.
