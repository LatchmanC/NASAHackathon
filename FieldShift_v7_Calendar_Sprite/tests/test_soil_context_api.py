"""Offline source-fusion regression tests: no external network required."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
import soil_context_api as source
import soil_rotation_api as soil
from prism_reference import closest_prism_reference

class ContextUnitTests(unittest.TestCase):
    def test_albers_projection_is_not_naive_degree_scaling(self):
        x, y = source._albers5070(42.4439, -76.5019)
        # EPSG:5070 reference from independent PROJ transform.
        self.assertAlmostEqual(x, 1585870, delta=150000)
        self.assertAlmostEqual(y, 2300000, delta=150000)

    def test_prism_archived_sample_has_year_and_provenance(self):
        q = closest_prism_reference(40.7282,-73.7949)
        self.assertEqual(q["status"],"reference_only")
        self.assertEqual(q["location_name"],"Queens, NY")
        self.assertAlmostEqual(q["year_2022"]["precip_mm"],1132.76,places=1)
        self.assertAlmostEqual(q["year_2016"]["dewpoint_c"],6.03,places=1)

    def test_prism_distant_location_is_not_misrepresented(self):
        p = closest_prism_reference(47.7,-111.1)
        self.assertEqual(p["status"],"not_near_reference_point")
        self.assertNotIn("year_2022",p)

    def test_fake_climate_fill_value_is_ignored(self):
        self.assertIsNone(source._num(-999))
        self.assertIsNone(source._num(-9999))

    def test_provider_error_never_produces_fictitious_readings(self):
        def boom(_a,_b): raise RuntimeError("Upstream failure")
        value=source._safe_fetch("source",boom,42,-76)
        self.assertEqual(value["status"],"unavailable")
        self.assertNotIn("annual_mean_air_temp_c",value)

    def test_two_stage_sda_keeps_rated_secondary_component(self):
        points=[{"mukey":"123"}]
        components=[
          {"mukey":"123","map_symbol":"U","map_name":"Urban soil","survey_area":"NY",
           "component_name":"Urban land","component_pct":70,"drainage_class":None},
          {"mukey":"123","map_symbol":"U","map_name":"Urban soil","survey_area":"NY",
           "component_name":"Silt loam","component_pct":30,"drainage_class":"Moderately well drained"}
        ]
        with patch.object(soil,"_sda_rows",side_effect=[points,components,[]]):
            answer=soil._query_usda(42.44,-76.50)
        self.assertEqual(answer["drainage_status"],"rated_secondary")
        self.assertEqual(answer["profile"]["drainage_class"],"Moderately well drained")
        self.assertEqual(answer["profile"]["dominant_component"],"Urban land")

class ContextRouteTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI()
        @app.get("/_login")
        def login(request:Request):
            request.session["user"]={"mode":"auth0","sub":"auth0|test","email":"test@example.com"}
            return {"ok":True}
        source.install_soil_context_routes(app)
        app.add_middleware(SessionMiddleware,secret_key="secure"*20)
        self.client=TestClient(app)

    def test_requires_signin(self):
        self.assertEqual(self.client.get("/api/soil/context?latitude=42.44&longitude=-76.5").status_code,403)

    def test_integration_uses_only_confirmed_or_unavailable_sources(self):
        self.client.get("/_login")
        unavailable=lambda _a,_b: {"status":"unavailable","message":"not available"}
        with patch.object(source,"_cache_get",return_value=None), \
             patch.object(source,"_cache_put"), \
             patch.object(source,"_power_climatology",side_effect=unavailable), \
             patch.object(source,"_usgs_terrain",side_effect=unavailable), \
             patch.object(source,"_usgs_water",side_effect=unavailable), \
             patch.object(source,"_usda_cdl",side_effect=unavailable):
            r=self.client.get("/api/soil/context?latitude=42.44&longitude=-76.5")
        self.assertEqual(r.status_code,200,r.text)
        j=r.json()
        self.assertEqual(j["climate"]["status"],"unavailable")
        self.assertEqual(j["terrain"]["status"],"unavailable")
        self.assertNotIn("annual_mean_air_temp_c",j["climate"])
        self.assertEqual(j["prism_reference"]["status"],"reference_only")

if __name__=="__main__":
    unittest.main()
