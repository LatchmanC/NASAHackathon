"""Offline unit and route regressions for authenticated farm state storage."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from fastapi import HTTPException

import farm_profile_api as farm

VALID_PLAN={"total_area":12,"area_unit":"acres","notes":"Test",
            "crops":[{"name":"Corn","area":3,"stage":"Planning","planted_on":"",
                      "variety":"Sweet"}]}
VALID_LOCATION={"mode":"coords","label":"My field","latitude":42.44,"longitude":-76.50}
TASK={"id":"test-1","date":"2026-11-20","kind":"inspection","crop":"Corn","note":"Check fields"}

class FarmValidationTests(unittest.TestCase):
    def test_account_hash_is_private_and_separate(self):
        from tigerdata_store import _key
        self.assertNotEqual(_key("auth0|one"),_key("auth0|two"))
        self.assertNotIn("auth0",_key("auth0|one"))

    def test_plan_validation(self):
        plan=farm._validate("plan",VALID_PLAN)
        self.assertEqual(plan["total_area"],12)
        self.assertEqual(plan["crops"][0]["name"],"Corn")

    def test_calendar_validation_and_limit(self):
        rows=farm._validate("calendar",[TASK])
        self.assertEqual(rows[0]["id"],"test-1")
        with self.assertRaises(HTTPException):
            farm._validate("calendar",[TASK]*501)
        with self.assertRaises(HTTPException):
            farm._validate("calendar",[TASK,TASK])

    def test_calendar_invalid_kind_and_date(self):
        with self.assertRaises(HTTPException):
            farm._validate("calendar",[{**TASK,"date":"not-a-date"}])
        with self.assertRaises(HTTPException):
            farm._validate("calendar",[{**TASK,"kind":"dangerous"}])

    def test_rotation_validation(self):
        val=farm._validate("rotation_scenarios",[{
            "id":"rot-1","goal":"diversify","location":"My field",
            "generated_at":"2026-11-15T01:00:00Z",
            "steps":[{"name":"Corn","emoji":"🌽","phase":"Current crop",
                      "description":"Plan"}]}])
        self.assertEqual(val[0]["steps"][0]["name"],"Corn")
        with self.assertRaises(HTTPException):
            farm._validate("rotation_scenarios",[{"id":"bad","steps":[]}])

    def test_location_validation(self):
        loc=farm._validate("location",VALID_LOCATION)
        self.assertEqual(loc["latitude"],42.44)
        with self.assertRaises(HTTPException):
            farm._validate("location",{**VALID_LOCATION,"latitude":120})

    def test_merge_only_adds_missing_ids(self):
        existing=[TASK]
        incoming=[TASK,{**TASK,"id":"test-2"}]
        merged,n=farm._merge_unique(existing,incoming,500)
        self.assertEqual(n,1)
        self.assertEqual(len(merged),2)
        self.assertEqual(existing,[TASK])
        self.assertEqual(merged[0],TASK)

    def test_merge_respects_limit_and_does_not_overwrite(self):
        existing=[{**TASK,"id":"x","note":"Saved to cloud"}]
        incoming=[{**TASK,"id":"x","note":"Old browser version"},
                  {**TASK,"id":"y"}]
        merged,n=farm._merge_unique(existing,incoming,1)
        self.assertEqual(n,0)
        self.assertEqual(merged[0]["note"],"Saved to cloud")

class FarmAuthTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        self.app.add_middleware(SessionMiddleware,secret_key="test"*32)
        farm.install_farm_profile_routes(self.app)
        self.client=TestClient(self.app)
    def test_all_cloud_routes_require_auth0(self):
        self.assertEqual(self.client.get("/api/farm/state").status_code,403)
        self.assertEqual(self.client.put("/api/farm/state/plan",json={"value":VALID_PLAN,"expected_revision":0}).status_code,403)
        self.assertEqual(self.client.post("/api/farm/import",json={"sections":{"plan":VALID_PLAN}}).status_code,403)
        self.assertEqual(self.client.post("/api/farm/calendar",json=TASK).status_code,403)
        self.assertEqual(self.client.delete("/api/farm/calendar/test-1").status_code,403)

    def test_bad_section_rejected(self):
        @self.app.get("/_login")
        def login(request:Request):
            request.session["user"]={"mode":"auth0","sub":"auth0|test"}
            return {"ok":True}
        self.client.get("/_login")
        r=self.client.put("/api/farm/state/not-real",json={
            "value":{},"expected_revision":0})
        self.assertEqual(r.status_code,404)

if __name__=="__main__":
    unittest.main()
