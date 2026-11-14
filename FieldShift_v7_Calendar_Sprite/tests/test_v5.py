"""Offline checks; no NASA, Gemini or cloud accounts needed."""
import unittest
from unittest.mock import patch
from intelligence import demo_nasa_daily
from web_server import validate_plan
from gemini_client import generate_gemini_reply

class DemoTests(unittest.TestCase):
    def setUp(self):
        self.location={'latitude':40.0,'longitude':-74.0}

    def test_nasa_daily_contains_core_parameters_and_is_labeled_demo(self):
        series=demo_nasa_daily(self.location,days=10)
        self.assertFalse(series['is_real_nasa'])
        self.assertTrue(series['demo'])
        self.assertEqual(len(series['rows']),10)
        for key in ('temperature_c','temperature_max_c','temperature_min_c','humidity_pct','pressure_hpa','precipitation_mm','solar_mj_m2_day','wind_2m_ms','wind_10m_ms','dew_point_c','soil_wetness_fraction'):
            self.assertIn(key,series['rows'][0])

    def test_allocation_cannot_exceed_land(self):
        with self.assertRaises(ValueError):
            validate_plan({'total_area':2,'area_unit':'acres','crops':[{'name':'Corn','area':3}]})

    def test_plans_accept_multiple_crops(self):
        data=validate_plan({'total_area':10,'area_unit':'hectares','crops':[{'name':'Corn','area':4},{'name':'Beans','area':2}]})
        self.assertEqual(data['unallocated_area'],4)

    def test_gemini_rejects_multiline_secret_before_request(self):
        with self.assertRaisesRegex(ValueError,'one line'):
            generate_gemini_reply('not-a-real-key\nextra','prompt')

if __name__=='__main__':unittest.main()
