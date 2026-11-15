"""Offline public-demo integration tests: never call live providers or TigerData."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import app as server
import advisor_core
import demo_data
import soil_rotation_api
import soil_context_api
import history_api

EXAMPLE_PLAN={"total_area":5,"area_unit":"acres","crops":[
    {"name":"Corn","area":2,"stage":"Planning"},
    {"name":"Tomato","area":1,"stage":"Flowering"}]}

class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        @self.app.get("/_sample")
        def login(request:__import__('fastapi').Request):
            request.session["user"]={"sub":"sample:test","mode":"sample","name":"Demo Farmer"}
            return {"ok":True}
        soil_rotation_api.install_soil_rotation_routes(self.app)
        soil_context_api.install_soil_context_routes(self.app)
        history_api.install_history_routes(self.app)
        self.app.add_middleware(SessionMiddleware,secret_key="long-testing-key-"+"x"*32)
        self.client=TestClient(self.app)
        self.client.get("/_sample")

    def test_demo_soil_profiles_are_simulated_and_never_query_usda(self):
        with patch.object(soil_rotation_api,"_query_usda",side_effect=AssertionError("live USDA called")):
            r=self.client.get("/api/soil/profile",params={"latitude":32.7157,"longitude":-117.1611})
        self.assertEqual(r.status_code,200,r.text)
        result=r.json()
        self.assertTrue(result["demo"])
        self.assertIn("SIMULATED",result["source"])
        self.assertEqual(result["profile"]["ph_water"],6.4)

    def test_demo_context_never_calls_usgs_or_tigerdata(self):
        with patch.object(soil_context_api,"_power_climatology",side_effect=AssertionError("live climate called")):
            r=self.client.get("/api/soil/context",params={"latitude":32.7157,"longitude":-117.1611})
        self.assertEqual(r.status_code,200,r.text)
        data=r.json()
        self.assertTrue(data["demo"])
        self.assertTrue(data["climate"]["simulated"])
        self.assertEqual(data["climate"]["annual_mean_air_temp_c"],17.8)

    def test_demo_history_has_fake_dates_and_readings_only(self):
        with patch.object(history_api.tiger,"_connection",side_effect=AssertionError("TigerData used")):
            status=self.client.get("/api/history/status").json()
            self.assertTrue(status["demo"])
            dates=self.client.get("/api/history/dates").json()
            self.assertTrue(dates["demo"])
            day=dates["dates"][0]
            snaps=self.client.get("/api/history/snapshots",params={"day":day}).json()["snapshots"]
            self.assertEqual(len(snaps),2)
            sample=self.client.get("/api/history/entry",params={
                "day":day,"bucket":snaps[0]["bucket_at"],
                "latitude":32.7157,"longitude":-117.1611})
        self.assertEqual(sample.status_code,200,sample.text)
        self.assertTrue(sample.json()["demo"])
        self.assertIn("SIMULATED",sample.json()["sensor"]["device_id"])
        self.assertEqual(self.client.post("/api/history/sync-nasa",json={}).status_code,403)

    def test_simulated_weather_does_not_fetch_external_forecast(self):
        req=SimpleNamespace(scope={"session":{}},session={"user":{"mode":"sample","sub":"sample:test"}})
        with patch.object(server,"forecast_bundle",side_effect=AssertionError("live weather called")):
            out=server.weather(req,latitude=32.7157,longitude=-117.1611)
        self.assertTrue(out["demo"])
        self.assertEqual(len(out["forecast"]),7)
        self.assertIn("SIMULATED",out["forecast_source"])

    def test_simulated_nasa_data_never_calls_live_nasa(self):
        req=SimpleNamespace(scope={"session":{}},session={"user":{"mode":"sample","sub":"sample:test"}})
        with patch.object(server,"fetch_nasa_daily",side_effect=AssertionError("live NASA called")):
            out=server.nasa(req,mode="real",days=30,latitude=32.7157,longitude=-117.1611)
        self.assertFalse(out["nasa_daily"]["is_real_nasa"])
        self.assertIn("SIMULATED",out["note"])
        self.assertEqual(len(out["nasa_daily"]["rows"]),30)

    def test_public_demo_never_uses_paid_gemini(self):
        req=SimpleNamespace(scope={"session":{}},session={"user":{"mode":"sample","sub":"sample:test"}})
        with patch.dict(os.environ,{"GEMINI_API_KEY":"fake-demo-secret"}):
            status=server.gemini_status(req)
        self.assertEqual(status["mode"],"sample")
        self.assertFalse(status["configured"])
        self.assertIn("key not available",status["note"])
        body=server.AdviceRequest(plan=EXAMPLE_PLAN,question="How is soil drainage?",
            location={"latitude":32.7157,"longitude":-117.1611})
        with patch.object(server,"generate_gemini_reply",side_effect=AssertionError("Paid Gemini called")):
            advice=server.farming_advice(body,req)
        self.assertEqual(advice["provider"],"demo")
        self.assertIn("simulated",advice["advice_structured"]["source_notes"][0].lower())
        self.assertTrue(advice["advice_structured"]["highlights"])

    def test_demo_data_is_not_a_real_tigerdata_account(self):
        from device_api import _owner
        from fastapi import HTTPException
        req=SimpleNamespace(session={"user":{"mode":"sample","sub":"sample:test"}})
        with self.assertRaises(HTTPException) as e:
            _owner(req)
        self.assertEqual(e.exception.status_code,403)

if __name__=="__main__": unittest.main()
