"""Capture-independent TCP SYN/SYN-ACK matching and timing."""
from dataclasses import dataclass

@dataclass
class Syn:
    ts_ns: int; src_ip: str; src_port: int; dst_ip: str; dst_port: int; seq: int; retransmit: bool = False

def match_syn_ack(syn, packet):
    """Return True only for the reverse tuple and ACK of the first SYN."""
    return (packet.get('src_ip') == syn.dst_ip and packet.get('src_port') == syn.dst_port and
            packet.get('dst_ip') == syn.src_ip and packet.get('dst_port') == syn.src_port and
            packet.get('syn') and packet.get('ack') and packet.get('ack_num') == syn.seq + 1)

def syn_ack_ms(syn_ts_ns, ack_ts_ns):
    return (ack_ts_ns - syn_ts_ns) / 1_000_000
