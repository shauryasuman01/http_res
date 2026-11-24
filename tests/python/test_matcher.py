import sys, unittest
sys.path.insert(0,'probe')
from matcher import Syn, match_syn_ack, syn_ack_ms
class MatcherTest(unittest.TestCase):
 def test_exact_42ms(self): self.assertEqual(syn_ack_ms(100_000_000,142_000_000),42)
 def test_tuple_ack_and_unrelated(self):
  s=Syn(100,'10.0.0.1',5000,'1.2.3.4',443,99)
  good={'src_ip':'1.2.3.4','src_port':443,'dst_ip':'10.0.0.1','dst_port':5000,'syn':True,'ack':True,'ack_num':100}
  self.assertTrue(match_syn_ack(s,good)); self.assertFalse(match_syn_ack(s,{**good,'ack_num':101})); self.assertFalse(match_syn_ack(s,{**good,'src_port':80}))
 def test_retransmit_does_not_change_first_syn(self):
  first=Syn(100_000_000,'a',1,'b',443,7); retransmit=Syn(110_000_000,'a',1,'b',443,7,True)
  self.assertEqual(syn_ack_ms(first.ts_ns,142_000_000),42); self.assertNotEqual(retransmit.ts_ns,first.ts_ns)
if __name__=='__main__': unittest.main()
