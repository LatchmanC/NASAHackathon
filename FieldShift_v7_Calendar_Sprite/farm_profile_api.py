"""Authenticated TigerData farm documents and safe browser-data migration.

Never overwrite another device's changes silently: each document has a revision.
The import operation inserts missing sections and *merges* calendars/drafts by
stable IDs, without overwriting any existing server item.
"""
from __future__ import annotations

from datetime import date
import logging
import hashlib
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb
from device_api import _owner
from fieldshift_core import valid_lat_lon
from farm_sync import _setup as setup_farm_locations
from tigerdata_store import _connection, _key, _json, enabled

log = logging.getLogger(__name__)
SECTIONS = ("plan", "location", "calendar", "rotation_scenarios")
TASK_KINDS = {"planting", "watering", "harvest", "fertilizing", "inspection", "other"}


class SectionWrite(BaseModel):
    value: Any
    expected_revision: int = Field(ge=0)


class ImportWrite(BaseModel):
    sections: dict[str, Any] = Field(default_factory=dict)


class TaskWrite(BaseModel):
    date: str
    kind: str
    crop: str = ""
    note: str = ""
    google_event_id: str | None = None
    id: str | None = None


class GoogleTaskSync(BaseModel):
    # A farmer explicitly opts into a connected Google Calendar when saving
    # the task or clicking the Send to Google button.
    confirmed: bool = False


def _setup(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS cropoganda_farm_documents (
            account_key TEXT NOT NULL,
            section TEXT NOT NULL,
            value JSONB NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (account_key, section),
            CHECK (section IN ('plan','location','calendar','rotation_scenarios'))
        )""")
    setup_farm_locations(conn)


def _present(value):
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return bool(value)
    return True


def _validate_date(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError("Date must be YYYY-MM-DD")
    date.fromisoformat(s)
    return s


def _validate_task(row):
    if not isinstance(row, dict):
        raise ValueError("Invalid calendar task")
    if row.get("kind") not in TASK_KINDS:
        raise ValueError("Invalid calendar task type")
    ident = str(row.get("id") or uuid4()).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", ident):
        raise ValueError("Invalid calendar task ID")
    crop = str(row.get("crop") or "")[:70]
    note = str(row.get("note") or "")[:240]
    google_id = row.get("google_event_id")
    if google_id is not None and (not isinstance(google_id,str) or len(google_id)>255):
        raise ValueError("Invalid Google Calendar event reference")
    return {"id": ident, "date": _validate_date(row.get("date")), "kind": row["kind"],
            "crop": crop, "note": note, "google_event_id": google_id}


def _validate(section, value):
    if section not in SECTIONS:
        raise HTTPException(404, "Unknown farm data section")
    if section == "plan":
        from app import validate_plan
        try:
            return validate_plan(value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if section == "location":
        if not isinstance(value, dict):
            raise HTTPException(400, "Invalid farm location")
        try:
            lat, lon = valid_lat_lon(value.get("latitude"),value.get("longitude"))
            mode = value.get("mode", "coords")
            if mode not in ("coords", "preset"):
                raise ValueError("Invalid farm location mode")
            label = str(value.get("label") or "").strip()[:130]
            if not label:
                label = f"{lat:.4f}, {lon:.4f}"
            return {"mode":mode,"latitude":lat,"longitude":lon,
                    "label":label,"resolution":str(value.get("resolution") or "")[:130]}
        except (TypeError,ValueError) as exc:
            raise HTTPException(400, "Invalid farm coordinates") from exc
    if section == "calendar":
        if not isinstance(value,list) or len(value)>500:
            raise HTTPException(400, "Calendar must contain at most 500 tasks")
        try:
            tasks=[_validate_task(item) for item in value]
        except (ValueError,TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if len(set(item["id"] for item in tasks)) != len(tasks):
            raise HTTPException(400, "Duplicate calendar task ID")
        return sorted(tasks,key=lambda t:(t["date"],t["id"]))
    if not isinstance(value,list) or len(value)>30:
        raise HTTPException(400, "Rotation drafts must be a list (maximum 30)")
    clean=[]
    seen=set()
    for item in value:
        if not isinstance(item,dict):
            raise HTTPException(400, "Invalid rotation draft")
        ident=str(item.get("id") or uuid4())
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}",ident) or ident in seen:
            raise HTTPException(400, "Duplicate or invalid rotation draft ID")
        seen.add(ident)
        steps=item.get("steps")
        if not isinstance(steps,list) or not 1<=len(steps)<=12:
            raise HTTPException(400, "Rotation draft needs 1–12 steps")
        clean_steps=[]
        for step in steps:
            if not isinstance(step,dict):
                raise HTTPException(400, "Invalid rotation step")
            clean_steps.append({k:str(step.get(k) or "")[:300] for k in
                                ("name","emoji","phase","description")})
        goal=str(item.get("goal") or "")[:80]
        loc=item.get("location")
        if loc is not None: loc=str(loc)[:130]
        clean.append({"id":ident, "steps":clean_steps, "goal":goal,
                      "location":loc,
                      "generated_at":str(item.get("generated_at") or "")[:50]})
    return clean


def _read_all(conn, account_key):
    with conn.cursor() as cur:
        cur.execute("""SELECT section,value,revision,updated_at FROM cropoganda_farm_documents
                       WHERE account_key=%s""",(account_key,))
        fetched=cur.fetchall()
        cur.execute("""SELECT latitude,longitude,label FROM cropoganda_farm_locations
                       WHERE account_key=%s""",(account_key,))
        registered=cur.fetchone()
    sections={key:{"value":None,"revision":0,"present":False,"updated_at":None}
              for key in SECTIONS}
    for section,value,revision,updated in fetched:
        sections[section]={"value":_json(value),"revision":revision,
                           "present":True,"updated_at":updated.isoformat()}
    if registered and not sections["location"]["present"]:
        lat,lon,label=registered
        sections["location"]={"value":{"mode":"coords","latitude":lat,
                            "longitude":lon,"label":label,"resolution":"saved farm location"},
                            "revision":0,"present":True,"updated_at":None,
                            "source":"existing TigerData farm location registration"}
    return sections


def _write(conn, account_key, section, value, expected):
    with conn.cursor() as cur:
        cur.execute("""SELECT revision FROM cropoganda_farm_documents
                       WHERE account_key=%s AND section=%s FOR UPDATE""",
                    (account_key,section))
        existing=cur.fetchone()
        if existing is not None:
            if int(existing[0])!=expected:
                raise HTTPException(409,"Farm data changed on another device. Reload before saving.")
            cur.execute("""UPDATE cropoganda_farm_documents
                           SET value=%s, revision=revision+1,updated_at=now()
                           WHERE account_key=%s AND section=%s
                           RETURNING revision""",
                        (Jsonb(value),account_key,section))
        else:
            if expected!=0:
                raise HTTPException(409,"Farm data changed on another device. Reload before saving.")
            # A concurrent first write wins; never overwrite it without a
            # fresh read and explicit revision match.
            cur.execute("""INSERT INTO cropoganda_farm_documents
                           (account_key,section,value,revision,updated_at)
                           VALUES (%s,%s,%s,1,now())
                           ON CONFLICT DO NOTHING
                           RETURNING revision""",
                        (account_key,section,Jsonb(value)))
        updated=cur.fetchone()
    if not updated:
        raise HTTPException(409,"Farm data changed on another device. Reload before saving.")
    if section=="location":
        lat,lon=value["latitude"],value["longitude"]
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO cropoganda_farm_locations
                           (account_key,latitude,longitude,label,last_nasa_sync_at)
                           VALUES (%s,%s,%s,%s,NULL)
                           ON CONFLICT(account_key) DO UPDATE
                           SET latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,
                               label=EXCLUDED.label,updated_at=now(),
                               last_nasa_sync_at=CASE
                                 WHEN cropoganda_farm_locations.latitude=EXCLUDED.latitude
                                   AND cropoganda_farm_locations.longitude=EXCLUDED.longitude
                                 THEN cropoganda_farm_locations.last_nasa_sync_at
                                 ELSE NULL END""",(account_key,lat,lon,value["label"]))
    return int(updated[0])


def _merge_unique(existing, incoming, limit):
    output=list(existing)
    found={item["id"] for item in existing}
    added=0
    for item in incoming:
        if item["id"] not in found and len(output)<limit:
            output.append(item)
            found.add(item["id"])
            added+=1
    return output,added


def install_farm_profile_routes(app):
    @app.get("/api/farm/state")
    def farm_state(request:Request):
        account=_owner(request)
        with _connection() as conn:
            _setup(conn)
            sections=_read_all(conn,_key(account))
        return {"storage":"TigerData","sections":sections}

    @app.put("/api/farm/state/{section}")
    def set_farm_section(section:str,req:SectionWrite,request:Request):
        account=_owner(request)
        value=_validate(section,req.value)
        try:
            with _connection() as conn:
                _setup(conn)
                revision=_write(conn,_key(account),section,value,req.expected_revision)
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("Farm section update failed")
            raise HTTPException(503,"Farm database could not save this change") from exc
        return {"saved":True,"storage":"TigerData","section":section,
                "value":value,"revision":revision}

    @app.post("/api/farm/import")
    def import_browser_data(req:ImportWrite,request:Request):
        account=_owner(request)
        if not req.sections or any(k not in SECTIONS for k in req.sections):
            raise HTTPException(400,"Invalid browser import sections")
        # Validate everything before starting any database modification.
        validated={k:_validate(k,v) for k,v in req.sections.items()}
        result={}
        with _connection() as conn:
            _setup(conn)
            account_key=_key(account)
            with conn.cursor() as cur:
                # Serialize migrations across tabs/devices per account. The
                # account row is locked even before the first document exists.
                cur.execute("""SELECT pg_advisory_xact_lock(hashtext(%s))""",(account_key,))
            server=_read_all(conn,account_key)
            for section,value in validated.items():
                current=server[section]
                if not current["present"]:
                    revision=_write(conn,account_key,section,value,0)
                    result[section]={"action":"imported","count":len(value) if isinstance(value,list) else 1,
                                     "revision":revision}
                elif section in ("calendar","rotation_scenarios"):
                    merged,added=_merge_unique(current["value"] or [],value,
                                               500 if section=="calendar" else 30)
                    if added:
                        # A registration-only location has revision zero, but
                        # list sections are always stored as actual documents.
                        revision=_write(conn,account_key,section,
                                        _validate(section,merged),current["revision"])
                    else:
                        revision=current["revision"]
                    result[section]={"action":"merged" if added else "unchanged",
                                     "count":added,"revision":revision}
                else:
                    result[section]={"action":"kept_existing","count":0,
                                     "revision":current["revision"]}
            sections=_read_all(conn,account_key)
        return {"storage":"TigerData","results":result,"sections":sections}

    @app.post("/api/farm/calendar")
    def add_calendar(req:TaskWrite,request:Request):
        account_key=_key(_owner(request))
        try: task=_validate_task(req.model_dump())
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        with _connection() as conn:
            _setup(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(account_key,))
            row=_read_all(conn,account_key)["calendar"]
            events=list(row["value"] or [])
            if not any(x["id"]==task["id"] for x in events):
                if len(events)>=500:raise HTTPException(400,"Maximum 500 calendar tasks")
                events.append(task)
                revision=_write(conn,account_key,"calendar",_validate("calendar",events),row["revision"])
            else:revision=row["revision"]
        return {"saved":True,"storage":"TigerData","events":sorted(events,key=lambda t:t["date"]),
                "revision":revision}

    @app.post("/api/farm/calendar/{event_id}/google-sync")
    def sync_calendar_to_google(event_id:str,req:GoogleTaskSync,request:Request):
        """Publish a previously saved task to THIS Auth0 owner's Google Calendar.

        Database save and Google insertion are intentionally separate: a Google
        outage must never lose a TigerData task. Google IDs are derived from
        the stable farm task ID, so retrying after a timeout cannot duplicate
        events even if Google succeeded but the DB association failed.
        """
        owner=_owner(request)
        if not req.confirmed:
            raise HTTPException(403,"Google Calendar sync needs the farmer's confirmation")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}",event_id):
            raise HTTPException(400,"Invalid farm calendar task ID")
        key=_key(owner)
        try:
            with _connection() as conn:
                _setup(conn)
                stored=_read_all(conn,key)["calendar"]
                task=next((item for item in (stored["value"] or [])
                           if item["id"]==event_id),None)
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("Could not look up task for Google sync")
            raise HTTPException(503,"Farm calendar unavailable; Google sync not attempted") from exc
        if task is None:
            raise HTTPException(404,"Save this task to your Farm Calendar before syncing")
        if task.get("google_event_id"):
            return {"synced":True,"already_synced":True,
                    "google_event_id":task["google_event_id"],
                    "events":stored["value"],"revision":stored["revision"],
                    "storage":"TigerData"}
        # Import lazily: never invoke Google from a public/demo account.
        from google_calendar_api import AddEvent, create_google_event
        response=create_google_event(owner,AddEvent(
            confirmed=True,request_id=hashlib.sha256(event_id.encode('utf-8')).hexdigest(),
            date=task["date"],
            kind=task["kind"],crop=task.get("crop",""),note=task.get("note","")))
        google_id=response["event_id"]
        try:
            with _connection() as conn:
                _setup(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(key,))
                section=_read_all(conn,key)["calendar"]
                tasks=[dict(item) for item in (section["value"] or [])]
                match=next((item for item in tasks if item["id"]==event_id),None)
                if match is None:
                    raise HTTPException(409,"Google event was created, but the Farm Calendar task was removed during sync. Check Google Calendar.")
                if match.get("google_event_id"):
                    google_id=match["google_event_id"]
                    revision=section["revision"]
                else:
                    match["google_event_id"]=google_id
                    tasks=_validate("calendar",tasks)
                    revision=_write(conn,key,"calendar",tasks,section["revision"])
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("Google event created, but farm association could not be stored")
            raise HTTPException(503,"Google event may have been created, but Farm Calendar could not record the link. Use Retry Google sync; it cannot duplicate the event.") from exc
        return {"synced":True,"already_synced":bool(response.get("already_exists")),
                "google_event_id":google_id,"google_url":response.get("google_url"),
                "events":tasks,"revision":revision,"storage":"TigerData"}

    @app.delete("/api/farm/calendar/{event_id}")
    def delete_calendar(event_id:str,request:Request):
        account_key=_key(_owner(request))
        with _connection() as conn:
            _setup(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(account_key,))
            row=_read_all(conn,account_key)["calendar"]
            events=list(row["value"] or [])
            filtered=[x for x in events if x["id"]!=event_id]
            if len(filtered)==len(events):
                raise HTTPException(404,"Calendar task not found")
            revision=_write(conn,account_key,"calendar",filtered,row["revision"])
        return {"deleted":True,"storage":"TigerData","events":filtered,"revision":revision}
