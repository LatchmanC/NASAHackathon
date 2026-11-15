"""Google export of account-owned Farm Calendar tasks (offline, no network)."""
import copy
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import farm_profile_api as farm
import google_calendar_api as google
from tigerdata_store import _key

TASK={"id":"farm-task-1","date":"2026-11-20","kind":"watering",
      "crop":"Tomato","note":"Check soil first","google_event_id":None}

class FakeDb:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def execute(self,*args):pass

class FarmGoogleSyncTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        @self.app.get("/_login/{account}")
        def login(account:str,request:Request):
            request.session["user"]={"mode":"auth0","sub":"auth0|"+account,
                                     "email":account+"@example.invalid"}
            return {"ok":True}
        @self.app.get("/_demo")
        def demo(request:Request):
            request.session["user"]={"mode":"sample","sub":"sample:test"}
            return {"ok":True}
        farm.install_farm_profile_routes(self.app)
        self.app.add_middleware(SessionMiddleware,secret_key="testing-"+"x"*40)
        self.client=TestClient(self.app)
        self.db=FakeDb()
        self.rows={_key("auth0|alice"):{"events":[copy.deepcopy(TASK)],"revision":2},
                   _key("auth0|bob"):{"events":[{**TASK,"id":"bob-private"}],"revision":4}}
        self.calls=[]

    def read_all(self,conn,key):
        state=self.rows.get(key,{"events":[],"revision":0})
        return {"calendar":{"value":copy.deepcopy(state["events"]),
                            "revision":state["revision"],"present":True}}
    def write(self,conn,key,section,value,expected):
        self.assertEqual(section,"calendar")
        self.assertEqual(expected,self.rows[key]["revision"])
        self.rows[key]["events"]=copy.deepcopy(value)
        self.rows[key]["revision"]+=1
        return self.rows[key]["revision"]
    def google_event(self,owner,event):
        self.calls.append((owner,event.request_id,event.confirmed,event.date))
        return {"created":True,"event_id":"g"+event.request_id,
                "google_url":"https://calendar.google.com/calendar/u/0/r"}

    def contexts(self):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(farm,"_connection",return_value=self.db))
        stack.enter_context(patch.object(farm,"_setup"))
        stack.enter_context(patch.object(farm,"_read_all",side_effect=self.read_all))
        stack.enter_context(patch.object(farm,"_write",side_effect=self.write))
        stack.enter_context(patch.object(google,"create_google_event",side_effect=self.google_event))
        return stack

    def login(self,account="alice"):
        self.assertEqual(self.client.get("/_login/"+account).status_code,200)

    def sync(self,id="farm-task-1",confirmed=True):
        return self.client.post("/api/farm/calendar/"+id+"/google-sync",
                                json={"confirmed":confirmed})

    def test_real_auth0_account_required(self):
        with self.contexts():
            self.assertEqual(self.sync().status_code,403)
            self.client.get("/_demo")
            self.assertEqual(self.sync().status_code,403)
        self.assertEqual(self.calls,[])

    def test_explicit_opt_in_required(self):
        self.login()
        with self.contexts():
            r=self.sync(confirmed=False)
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.calls,[])

    def test_unowned_task_cannot_be_exported(self):
        self.login("alice")
        with self.contexts():
            r=self.sync("bob-private")
        self.assertEqual(r.status_code,404)
        self.assertEqual(self.calls,[])

    def test_exports_saved_task_then_records_google_id_and_revision(self):
        self.login()
        with self.contexts():
            r=self.sync()
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["google_event_id"],"gfarm-task-1")
        self.assertEqual(r.json()["events"][0]["google_event_id"],"gfarm-task-1")
        self.assertEqual(self.rows[_key("auth0|alice")]["revision"],3)
        self.assertEqual(self.rows[_key("auth0|alice")]["events"][0]["google_event_id"],"gfarm-task-1")
        self.assertEqual(self.calls,[("auth0|alice","farm-task-1",True,"2026-11-20")])
        self.assertIsNone(self.rows[_key("auth0|bob")]["events"][0]["google_event_id"])

    def test_repeat_click_does_not_create_duplicate_google_event(self):
        self.login()
        with self.contexts():
            a=self.sync()
            b=self.sync()
        self.assertEqual(a.status_code,200)
        self.assertEqual(b.status_code,200)
        self.assertTrue(b.json()["already_synced"])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.rows[_key("auth0|alice")]["revision"],3)

    def test_google_failure_retains_unsynced_tigerdata_task_then_retry_works(self):
        self.login()
        with self.contexts():
            with patch.object(google,"create_google_event",
                              side_effect=HTTPException(502,"Google temporarily down")):
                r=self.sync()
            self.assertEqual(r.status_code,502)
            self.assertIsNone(self.rows[_key("auth0|alice")]["events"][0]["google_event_id"])
            second=self.sync()
        self.assertEqual(second.status_code,200)
        self.assertEqual(len(self.calls),1)

    def test_tigerdata_failure_after_google_send_is_safely_retryable(self):
        self.login()
        with self.contexts():
            with patch.object(farm,"_write",side_effect=RuntimeError("temporary DB outage")):
                failed=self.sync()
            self.assertEqual(failed.status_code,503)
            self.assertIsNone(self.rows[_key("auth0|alice")]["events"][0]["google_event_id"])
            retried=self.sync()
        self.assertEqual(retried.status_code,200)
        self.assertEqual([x[1] for x in self.calls],["farm-task-1","farm-task-1"])
        self.assertEqual(self.rows[_key("auth0|alice")]["events"][0]["google_event_id"],"gfarm-task-1")

    def test_delete_during_google_request_is_detected_not_silent(self):
        self.login()
        def removed(owner,event):
            self.rows[_key(owner)]["events"]=[]
            return {"created":True,"event_id":"g"+event.request_id}
        with self.contexts():
            with patch.object(google,"create_google_event",side_effect=removed):
                r=self.sync()
        self.assertEqual(r.status_code,409)
        self.assertIn("Google event was created",r.json()["detail"])

if __name__=="__main__":
    unittest.main()
