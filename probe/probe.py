"""Long-lived probe. Packet capture is intentionally isolated behind CaptureAdapter."""
import asyncio, json, os, socket, time, uuid
from decimal import Decimal
from matcher import syn_ack_ms
from scheduler import Scheduler

class CaptureAdapter:
    async def start(self, interface): raise RuntimeError(f"packet capture unavailable on {interface}; grant CAP_NET_RAW/CAP_NET_ADMIN or run as root")
    async def first_syn(self, key): return None
    async def syn_ack(self, key, timeout): return None

class ScapyCaptureAdapter(CaptureAdapter):
    """One libpcap listener shared by all attempts. Requires scapy."""
    def __init__(self):
        try:
            from scapy.all import AsyncSniffer
        except ImportError as e:
            raise RuntimeError('Install scapy and libpcap for live capture: python3 -m pip install scapy') from e
        self.AsyncSniffer=AsyncSniffer; self.syns={}; self.acks={}; self.waiters={}
    async def start(self, interface):
        check=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); check.close()
        def on_packet(p):
            try:
                ip=p.getlayer('IP') or p.getlayer('IPv6'); tcp=p.getlayer('TCP')
                if not ip or not tcp: return
                src=(ip.src,tcp.sport,ip.dst,tcp.dport); reverse=(ip.dst,tcp.dport,ip.src,tcp.sport); ts=int(Decimal(str(p.time))*1_000_000_000)
                flags=int(tcp.flags)
                if flags & 0x02 and not flags & 0x10: self.syns.setdefault(src,(ts,int(tcp.seq)))
                if flags & 0x12 == 0x12 and reverse in self.syns and int(tcp.ack)==(self.syns[reverse][1]+1) % (2**32):
                    self.acks[reverse]=ts; waiter=self.waiters.pop(reverse,None)
                    if waiter and not waiter.done(): waiter.set_result(ts)
            except (AttributeError, ValueError): return
        try: self.sniffer=self.AsyncSniffer(iface=interface,filter='tcp',prn=on_packet,store=False); self.sniffer.start()
        except Exception as e: raise RuntimeError(f'Cannot start packet capture on {interface}: {e}') from e
    async def first_syn(self, key):
        for _ in range(50):
            if key in self.syns: return self.syns[key][0]
            await asyncio.sleep(.01)
        return None
    async def syn_ack(self, key, timeout):
        if key in self.acks: return self.acks[key]
        loop=asyncio.get_running_loop(); fut=loop.create_future(); self.waiters[key]=fut
        try: return await asyncio.wait_for(fut,timeout)
        except asyncio.TimeoutError: self.waiters.pop(key,None); return None

async def attempt(target, capture, probe_id, timeout=5, skipped=None):
    now=time.strftime('%Y-%m-%dT%H:%M:%S.000Z',time.gmtime()); base={'schema_version':1,'attempt_id':str(uuid.uuid4()),'probe_id':probe_id,'hostname':target['hostname'],'port':target['port'],'resolved_ip':None,'observed_at':now,'first_syn_capture_ns':None,'syn_ack_capture_ns':None,'syn_ack_ms':None,'syn_retransmits':0,'status':skipped or 'network_error','error_reason':None}
    if skipped: base['error_reason']=skipped; return base
    try: infos=await asyncio.get_running_loop().run_in_executor(None,lambda:socket.getaddrinfo(target['hostname'],target['port'],type=socket.SOCK_STREAM))
    except socket.gaierror as e: base.update(status='dns_error',error_reason=e.errno or str(e)); return base
    family,_,_,_,addr=infos[0]; base['resolved_ip']=addr[0]; sock=socket.socket(family,socket.SOCK_STREAM); sock.settimeout(timeout)
    try:
        await asyncio.get_running_loop().run_in_executor(None,sock.connect,addr)
        key=(sock.getsockname()[0],sock.getsockname()[1],addr[0],addr[1]); syn=await capture.first_syn(key); ack=await capture.syn_ack(key,timeout)
        if not syn or not ack: base.update(status='capture_incomplete',error_reason='capture did not deliver both handshake packets'); return base
        base.update(status='ok',first_syn_capture_ns=str(syn),syn_ack_capture_ns=str(ack),syn_ack_ms=syn_ack_ms(syn,ack)); return base
    except socket.timeout: base.update(status='timeout',error_reason='connect timeout'); return base
    except ConnectionRefusedError: base.update(status='connection_refused',error_reason='ECONNREFUSED'); return base
    except OSError as e: base.update(status='network_error',error_reason=e.errno or str(e)); return base
    finally: sock.close()

async def main():
    cfg=json.load(open(os.getenv('WEBSITES_CONFIG','config/websites.json'))); capture=ScapyCaptureAdapter(); await capture.start(os.environ.get('PROBE_INTERFACE','eth0'))
    try:
        import zmq
        publisher=zmq.Context.instance().socket(zmq.PUB); publisher.bind(os.environ.get('ZMQ_BIND_ENDPOINT','tcp://*:5557'))
    except ImportError as e: raise RuntimeError('Install pyzmq for ZeroMQ publishing: python3 -m pip install pyzmq') from e
    async def do(t,skipped=None):
        event=await attempt(t,capture,os.environ.get('PROBE_ID','adwiser-probe-dev'),float(os.environ.get('PROBE_TIMEOUT_SECONDS',cfg['timeout_seconds'])),skipped)
        # PUB boundary is optional to keep core measurement testable; pyzmq is deployment dependency.
        publisher.send_json(event)
    scheduler=Scheduler([{'hostname':x,'port':443} if isinstance(x,str) else x for x in cfg['targets']],cfg['interval_seconds'],cfg['concurrency'],do)
    while True: await scheduler.run_round()
if __name__=='__main__': asyncio.run(main())
