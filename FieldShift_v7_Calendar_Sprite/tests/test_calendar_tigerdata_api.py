"""Authenticated TigerData farm calendar regression tests, entirely offline."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
import farm_profile_api as farm
from tigerdata_store import _key

TASK_A={"id":"alice-water","date":"2026-12-01","kind":"watering",
        "crop":"Tomato","note":"Water if dry"}
TASK_B={"id":"bob-plant","date":"2026-12-02","kind":"planting",
        "crop":"Corn","note":"Start planting"}

class MemoryDb:
    def __init__(self,rows):
        self.rows=rows
        self.last_key=None
        self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def execute(self,query,params):
        self.calls.append((query,params))
        if "SELECT value,revision,updated_at" in query:
            self.last_key=params[0]
    def fetchone(self):
        value=self.rows.get(self.last_key)
        return (value,3,datetime(2026,11,15,tzinfo=timezone.utc)) if value is not None else None

class CalendarCloudTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        @self.app.get("/_test/login/{who}")
        def login(who:str,request:Request):
            request.session["user"]={"mode":"auth0","sub":"auth0|"+who,
                "email":who+"@example.invalid"}
            return {"ok":True}
        farm.install_farm_profile_routes(self.app)
        self.app.add_middleware(SessionMiddleware,secret_key="test"*32)
        self.client=TestClient(self.app)

    def login(self,name):
        self.assertEqual(self.client.get("/_test/login/"+name).status_code,200)

    def test_requires_auth0_for_calendar_reads(self):
        result=self.client.get("/api/farm/calendar")
        self.assertEqual(result.status_code,403)

    def test_per_account_reads_are_separate(self):
        db=MemoryDb({_key("auth0|alice"):[TASK_A],_key("auth0|bob"):[TASK_B]})
        with patch.object(farm,"_connection",return_value=db),\
             patch.object(farm,"_setup"):
            self.login("alice")
            result=self.client.get("/api/farm/calendar")
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()["events"],[TASK_A])
            self.assertEqual(result.json()["storage"],"TigerData")
            self.assertEqual(result.json()["revision"],3)
            self.login("bob")
            other=self.client.get("/api/farm/calendar")
            self.assertEqual(other.status_code,200,other.text)
            self.assertEqual(other.json()["events"],[TASK_B])
        self.assertNotEqual(db.calls[0][1][0],db.calls[1][1][0])
        self.assertNotIn("auth0|",str(db.calls))

    def test_missing_calendar_is_real_empty_remote_record(self):
        self.login("alice")
        db=MemoryDb({})
        with patch.object(farm,"_connection",return_value=db),\
             patch.object(farm,"_setup"):
            result=self.client.get("/api/farm/calendar")
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json(),{"events":[],"revision":0,"updated_at":None,
                                        "storage":"TigerData"})

    def test_database_failure_is_not_silently_replaced_with_browser_data(self):
        self.login("alice")
        with patch.object(farm,"_connection",side_effect=HTTPException(503,"TigerData offline")):
            result=self.client.get("/api/farm/calendar")
        self.assertEqual(result.status_code,503)
        self.assertNotIn("events",result.json())

    def test_write_and_delete_do_not_touch_other_account(self):
        db=MemoryDb({})
        store={}
        def read_all(conn,key):
            value=store.get(key,[])
            return {"calendar":{"value":value,"revision":1 if value else 0,
                                "present":bool(value)}}
        def write(conn,key,section,value,revision):
            self.assertEqual(section,"calendar")
            store[key]=value
            return revision+1
        with patch.object(farm,"_connection",return_value=db),\
             patch.object(farm,"_setup"),\
             patch.object(farm,"_read_all",side_effect=read_all),\
             patch.object(farm,"_write",side_effect=write):
            self.login("alice")
            a=self.client.post("/api/farm/calendar",json=TASK_A)
            self.assertEqual(a.status_code,200,a.text)
            self.login("bob")
            b=self.client.post("/api/farm/calendar",json=TASK_B)
            self.assertEqual(b.status_code,200,b.text)
            self.assertEqual(store[_key("auth0|alice")],[TASK_A|{"google_event_id":None}])
            self.assertEqual(store[_key("auth0|bob")],[TASK_B|{"google_event_id":None}])
            self.login("alice")
            deleted=self.client.delete("/api/farm/calendar/alice-water")
            self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertEqual(store[_key("auth0|alice")],[])
        self.assertEqual(len(store[_key("auth0|bob")]),1)

if __name__=="__main__":
    unittest.main()
