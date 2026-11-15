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

    def test_public_demo_usda_uses_real_provider_but_never_private_soil_cache(self):
        soil_rotation_api._demo_public_usda.cache_clear()
        mock_result={"status":"ok","profile":{"ph_water":6.3,"texture":"Silt loam",
                  "drainage_class":"Moderately well drained"}}
        with patch.object(soil_rotation_api,"_query_usda",return_value=mock_result) as provider,\
             patch.object(soil_rotation_api,"_cache_get",side_effect=AssertionError("Private cache read")),\
             patch.object(soil_rotation_api,"_cache_put",side_effect=AssertionError("Private cache write")):
            r=self.client.get("/api/soil/profile",
                params={"latitude":32.7157,"longitude":-117.1611})
            repeated=self.client.get("/api/soil/profile",
                params={"latitude":32.7157,"longitude":-117.1611})
        self.assertEqual(r.status_code,200,r.text)
        result=r.json()
        self.assertTrue(result["demo"])
        self.assertTrue(result["public_provider_data"])
        self.assertIn("USDA",result["source"])
        self.assertEqual(result["profile"]["ph_water"],6.3)
        self.assertEqual(repeated.status_code,200)
        self.assertEqual(provider.call_count,1)

    def test_demo_context_uses_real_public_sources_never_tigerdata(self):
        soil_context_api._demo_public_context.cache_clear()
        with patch.object(soil_context_api,"_power_climatology",
                          return_value={"status":"ok","source":"NASA POWER","annual_mean_air_temp_c":17.8}) as climate,\
             patch.object(soil_context_api,"_usgs_terrain",
                          return_value={"status":"ok","source":"USGS 3DEP","elevation_m":20.5}) as terrain,\
             patch.object(soil_context_api,"_usgs_water",
                          return_value={"status":"no_data","source":"USGS NWIS"}) as water,\
             patch.object(soil_context_api,"_usda_cdl",
                          return_value={"status":"ok","source":"USDA CDL","samples":[]}) as cdl,\
             patch.object(soil_context_api,"_cache_get",side_effect=AssertionError("Private cache read")),\
             patch.object(soil_context_api,"_cache_put",side_effect=AssertionError("Private cache write")):
            r=self.client.get("/api/soil/context",
                params={"latitude":32.7157,"longitude":-117.1611})
        self.assertEqual(r.status_code,200,r.text)
        data=r.json()
        self.assertTrue(data["demo"])
        self.assertTrue(data["public_provider_data"])
        self.assertEqual(data["climate"]["annual_mean_air_temp_c"],17.8)
        self.assertEqual(data["terrain"]["elevation_m"],20.5)
        self.assertIn("prism_reference",data)
        for provider in (climate,terrain,water,cdl):
            self.assertEqual(provider.call_count,1)

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

    def test_demo_weather_calls_live_open_meteo_and_nws(self):
        req=SimpleNamespace(scope={"session":{}},session={"user":{"mode":"sample","sub":"sample:test"}})
        server._demo_public_weather.cache_clear()
        weather=([{"date":"2026-11-15","high_c":26}],{"temperature_c":22,"summary":"Clear"})
        alerts={"status":"live","source":"NWS","alerts":[{"event":"Wind Advisory"}]}
        with patch.object(server,"forecast_bundle",return_value=weather) as meteo,\
             patch.object(server,"official_alerts",return_value=alerts) as nws,\
             patch.object(server,"sample_weather",side_effect=AssertionError("Synthetic weather called")):
            out=server.weather(req,latitude=32.7157,longitude=-117.1611)
            again=server.weather(req,latitude=32.7157,longitude=-117.1611)
        self.assertTrue(out["demo"])
        self.assertEqual(out["current"]["temperature_c"],22)
        self.assertEqual(out["alert_status"]["alerts"][0]["event"],"Wind Advisory")
        self.assertIn("REAL Open-Meteo",out["forecast_source"])
        self.assertEqual(meteo.call_count,1)
        self.assertEqual(nws.call_count,1)

    def test_demo_nasa_is_real_public_read_only(self):
        req=SimpleNamespace(scope={"session":{}},session={"user":{"mode":"sample","sub":"sample:test"}})
        server._demo_public_nasa.cache_clear()
        fake={"is_real_nasa":True,"source":"NASA POWER","rows":[{"date":"2026-11-10","temperature_c":22}]}
        with patch.object(server,"fetch_nasa_daily",return_value=fake) as nasa,\
             patch.object(server,"tiger_save_nasa",side_effect=AssertionError("TigerData write")),\
             patch.object(server,"tiger_enabled",side_effect=AssertionError("TigerData probe")):
            out=server.nasa(req,mode="real",days=30,latitude=32.7157,longitude=-117.1611)
            again=server.nasa(req,mode="auto",days=30,latitude=32.7157,longitude=-117.1611)
        self.assertTrue(out["nasa_daily"]["is_real_nasa"])
        self.assertEqual(out["tigerdata_stored_days"],0)
        self.assertIn("REAL NASA POWER",out["note"])
        self.assertEqual(nasa.call_count,1)
        self.assertTrue(again["demo"])

    def test_demo_public_api_failures_do_not_fabricate_data(self):
        req=SimpleNamespace(scope={"session":{}},session={"user":{"mode":"sample","sub":"sample:test"}})
        server._demo_public_weather.cache_clear()
        server._demo_public_nasa.cache_clear()
        with patch.object(server,"forecast_bundle",side_effect=RuntimeError("network down")),\
             patch.object(server,"official_alerts",side_effect=RuntimeError("unavailable")):
            out=server.weather(req,latitude=32.7157,longitude=-117.1611)
        self.assertEqual(out["forecast"],[])
        self.assertIsNone(out["current"])
        self.assertEqual(out["alert_status"]["status"],"unavailable")
        with patch.object(server,"fetch_nasa_daily",side_effect=RuntimeError("NASA failed")):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as exc:
                server.nasa(req,mode="real",days=30,latitude=32.7157,longitude=-117.1611)
        self.assertEqual(exc.exception.status_code,502)

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
