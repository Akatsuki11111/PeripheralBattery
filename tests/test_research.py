import unittest
from unittest.mock import patch
from research import compare,sample


def pkt(data,vid=1,pid=2,interface=3):
 return {'hex':bytes(data).hex(' '),'vid':vid,'pid':pid,'interface':interface,'usage_page':0xffc0,'usage':1,'backend':'nova5'}

class ResearchTests(unittest.TestCase):
 def test_stable_flip_and_noise_separated(self):
  b=[pkt([176,0,55,3]),pkt([176,0,54,4]),pkt([176,0,54,5])]
  a=[pkt([176,1,55,6]),pkt([176,1,56,7]),pkt([176,1,57,8])]
  result=compare(b,a)
  self.assertEqual(result['stable_changed'],[{'offset':1,'mask':1,'before':0,'after':1}])
  self.assertEqual(result['unstable_offsets'],[2,3]);self.assertEqual([x['offset'] for x in result['battery_candidates']],[2])
  self.assertEqual(result['confidence'],'低')
 def test_ambiguous_values_are_not_automatic_evidence(self):
  b=[pkt([176,1,255]),pkt([176,1,255])];a=[pkt([176,1,0]),pkt([176,1,0])]
  result=compare(b,a);self.assertFalse(result['battery_candidates']);self.assertEqual(result['stable_changed'][0]['offset'],2)
 def test_length_and_identity_must_match(self):
  b=[pkt([1,2]),pkt([1,2])]
  for a in ([pkt([1]),pkt([1])],[pkt([1,2],pid=9),pkt([1,2],pid=9)]):
   with self.assertRaises(ValueError):compare(b,a)
 def test_missing_samples_rejected(self):
  with self.assertRaises(ValueError):compare([pkt([1])],[pkt([1]),pkt([1])])
 def test_unknown_device_does_not_open_hid(self):
  group={'device':{'identity':'a'*24,'vid':0x19f5,'pid':0x3247},'backend':'','infos':[]}
  with patch('research.enumerate_groups',return_value=[group]),patch('research.query') as query:
   with self.assertRaises(ValueError):sample('a'*24)
   query.assert_not_called()
 def test_changed_identity_rejected(self):
  with patch('research.enumerate_groups',return_value=[]),patch('research.query') as query:
   with self.assertRaises(ValueError):sample('a'*24)
   query.assert_not_called()
 def test_known_query_checks_interface_and_response(self):
  group={'device':{'identity':'a'*24,'vid':0x1038,'pid':0x2230,'name':'Nova 5'},'backend':'nova5_usb',
         'infos':[{'path':b'ab'.hex(),'interface_number':0,'usage_page':0xffc0,'usage':1}]}
  with patch('research.enumerate_groups',return_value=[group]),patch('research.query',return_value=[0xb0,2,2,57,1]+[0]*11):
   result=sample('a'*24);self.assertEqual(result['percent'],57);self.assertTrue(result['charging']);self.assertNotIn('path',result)

if __name__=='__main__':unittest.main()
