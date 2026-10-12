import unittest
from verify.check import linearizable
from verify.tso_litmus import report

class VerificationTests(unittest.TestCase):
    def test_good_history(self):
        h=[{"thread":0,"index":0,"op":"unite","x":0,"y":1,"start_ns":1,"end_ns":2,"result":1},
           {"thread":1,"index":0,"op":"find","x":1,"y":0,"start_ns":3,"end_ns":4,"result":0}]
        self.assertEqual(linearizable(h,3)["status"],"pass")
    def test_bad_history(self):
        h=[{"thread":0,"index":0,"op":"find","x":1,"y":0,"start_ns":1,"end_ns":2,"result":99}]
        self.assertEqual(linearizable(h,3)["status"],"fail")
    def test_tso_differs_from_sc(self):
        r=report()
        self.assertIn((0,0),r["tso_only"])

if __name__=="__main__":unittest.main()
