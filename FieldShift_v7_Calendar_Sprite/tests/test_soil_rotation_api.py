"""Offline regressions for USDA drainage and SMAP configuration states."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
import soil_rotation_api as soil

HEADERS=[
    "mukey","map_symbol","map_name","survey_area","component_name",
    "component_pct","drainage_class","slope_pct","texture"
]
def record(name, percent, drainage, key="123"):
    return [key,"A","Example NY map unit","NY001",name,percent,drainage,2.1,"Loam"]

class SoilIngestionTests(unittest.TestCase):
    def test_dominant_rated(self):
        data={"Table":[HEADERS,record("Silt loam",85,"Moderately well drained")]}
        result=soil._interpret_usda_table(data)
        self.assertEqual(result["drainage_status"],"rated")
        self.assertEqual(result["profile"]["component"],"Silt loam")

    def test_selects_rated_secondary_and_discloses_it(self):
        data={"Table":[HEADERS,record("Urban land",70,None),
                       record("Sandy loam",30,"Well drained")]}
        result=soil._interpret_usda_table(data)
        self.assertEqual(result["profile"]["drainage_class"],"Well drained")
        self.assertEqual(result["profile"]["dominant_component"],"Urban land")
        self.assertEqual(result["profile"]["selection_reason"],"rated_alternative")
        self.assertEqual(result["drainage_status"],"rated_secondary")
        self.assertIn("secondary",result["message"])

    def test_unrated_map_does_not_invent_drainage(self):
        data={"Table":[HEADERS,record("Urban land",100,"Not rated")]}
        result=soil._interpret_usda_table(data)
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["drainage_status"],"unrated")
        self.assertIsNone(result["profile"]["drainage_class"])

    def test_missing_map_unit(self):
        result=soil._interpret_usda_table({"Table":[]})
        self.assertEqual(result["status"],"no_coverage")

class SoilRouteTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI()
        @app.get("/_login")
        def login(request:Request):
            request.session["user"]={"mode":"auth0","sub":"auth0|test",
                                     "email":"test@example.com"}
            return {"ok":True}
        soil.install_soil_rotation_routes(app)
        app.add_middleware(SessionMiddleware,secret_key="test"*24)
        self.client=TestClient(app)
        self.client.get("/_login")

    def test_missing_credentials_report_setup_required(self):
        with patch.dict(os.environ,{"EARTH_ENGINE_PROJECT":"",
                                     "EARTH_ENGINE_SERVICE_ACCOUNT_JSON":""}):
            r=self.client.get("/api/soil/smap",params={"latitude":42.5,"longitude":-76.5})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()["status"],"setup_required")
        self.assertEqual(len(r.json()["missing_configuration"]),2)
        self.assertIsNone(r.json()["latest"])

    def test_upstream_failure_has_no_fake_profile(self):
        with patch.object(soil,"_cache_get",return_value=None), \
             patch.object(soil,"_query_usda",side_effect=RuntimeError("example")):
            r=self.client.get("/api/soil/profile",params={"latitude":42.5,"longitude":-76.5})
        self.assertEqual(r.json()["status"],"unavailable")
        self.assertNotIn("profile",r.json())

    def test_invalid_location_rejected(self):
        r=self.client.get("/api/soil/profile",params={"latitude":100,"longitude":-76.5})
        self.assertEqual(r.status_code,400)

if __name__=="__main__":
    unittest.main()
