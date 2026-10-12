import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from Main import configuration, new_output, derive

class IntegrationTests(unittest.TestCase):
    def test_smoke_config(self):
        self.assertEqual(configuration(Path(__file__).parents[1]/"configs"/"smoke.json")["profile"],"smoke")
    def test_aggregation(self):
        row={"experiment":"E3","method":"P1","workload":"W1","threads":1,"pause_us":0,"pause_rate":0,
             "status":"completed","throughput":100.0,"p50_ns":20,"p95_ns":30,"p99_ns":40,
             "loads_per_op":2.0,"depth_per_op":1.0,"cas_per_op":1.0,"retries_per_op":0.0,"completion_ratio":1.0}
        self.assertEqual(derive([row])[0]["throughput_median"],100.0)

if __name__=="__main__": unittest.main()
