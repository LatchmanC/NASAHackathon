"""Real USDA Soil Data Access and opt-in NASA SMAP/Google Earth Engine sampling.
No synthetic soil, satellite, hardware, price or yield values are generated.
Both routes require an authenticated Auth0 account; cache stays account-isolated.
"""
from __future__ import annotations
import json
import math
import os
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from device_api import _owner
from fieldshift_core import valid_lat_lon

USDA_URL="https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
USDA_SOURCE="USDA NRCS Soil Data Access (SSURGO/Soil Data Mart)"
SMAP_SOURCE="NASA SMAP SPL3SMP_E v006 AM, via Google Earth Engine"
SMAP_COLLECTION="NASA/SMAP/SPL3SMP_E/006"
SOIL_TTL=timedelta(hours=24)
SMAP_TTL=timedelta(hours=6)


def _now():
    return datetime.now(timezone.utc)


def _coords(latitude,longitude):
    try:
        lat,lon=valid_lat_lon(latitude,longitude)
    except (TypeError,ValueError) as exc:
        raise HTTPException(400,"Enter valid farm coordinates") from exc
    return round(float(lat),5),round(float(lon),5)


def _cache_connection():
    import tigerdata_store as tiger
    if not tiger.enabled():
        return None
    return tiger._connection()


def _cache_get(owner,lat,lon,kind,ttl):
    try:
        import tigerdata_store as tiger
        conn=_cache_connection()
        if conn is None:return None
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT payload, saved_at FROM cropaganda_soil_cache
                               WHERE account_key=%s AND latitude=%s
                               AND longitude=%s AND data_kind=%s""",
                            (tiger._key(owner),lat,lon,kind))
                row=cur.fetchone()
        if row and _now()-row[1]<ttl:
            data=row[0] if isinstance(row[0],dict) else json.loads(row[0])
            data["cache"]="TigerData"
            data["checked_at"]=row[1].isoformat()
            return data
    except Exception:
        # An optional cache must never invent values or prevent a real upstream request.
        return None
    return None


def _cache_put(owner,lat,lon,kind,data):
    try:
        import tigerdata_store as tiger
        from psycopg.types.json import Jsonb
        conn=_cache_connection()
        if conn is None:return
        with conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS cropaganda_soil_cache (
                    account_key TEXT NOT NULL,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    data_kind TEXT NOT NULL,
                    saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    payload JSONB NOT NULL,
                    PRIMARY KEY(account_key,latitude,longitude,data_kind)
                )""")
                cur.execute("""INSERT INTO cropaganda_soil_cache
                    (account_key,latitude,longitude,data_kind,saved_at,payload)
                    VALUES (%s,%s,%s,%s,now(),%s)
                    ON CONFLICT(account_key,latitude,longitude,data_kind)
                    DO UPDATE SET saved_at=now(),payload=excluded.payload""",
                    (tiger._key(owner),lat,lon,kind,Jsonb(data)))
    except Exception:
        # Optional persistence: the live authoritative result is still returned.
        pass


def _number(v):
    if v in (None,"","NULL","-9999","-9999.0"):return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):
        return None


def _query_usda(lat,lon):
    # Controlled parameterization: coordinates have already been reduced to floats.
    # Query only the mapunit that intersects the point; no user-provided SQL.
    wkt=f"point({lon:.5f} {lat:.5f})"
    query=f"""SELECT TOP 24
     mu.mukey AS mukey,mu.musym AS map_symbol,mu.muname AS map_name,
     le.areasymbol AS survey_area,
     c.compname AS component_name,c.comppct_r AS component_pct,
     c.drainagecl AS drainage_class,c.slope_r AS slope_pct,
     c.hydgrp AS hydrologic_group,
     ch.hzdept_r AS depth_top_cm,ch.hzdepb_r AS depth_bottom_cm,
     ch.om_r AS organic_matter_pct,ch.ph1to1h2o_r AS ph_water,
     ch.awc_r AS available_water_cm_per_cm,
     ch.sandtotal_r AS sand_pct,ch.silttotal_r AS silt_pct,
     ch.claytotal_r AS clay_pct,
     ctg.texture AS texture
     FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}') AS hit
     INNER JOIN mapunit mu ON mu.mukey=hit.mukey
     INNER JOIN legend le ON le.lkey=mu.lkey
     LEFT JOIN component c ON c.mukey=mu.mukey AND c.majcompflag='Yes'
     LEFT JOIN chorizon ch ON ch.cokey=c.cokey AND ch.hzdept_r=0
     LEFT JOIN chtexturegrp ctg ON ctg.chkey=ch.chkey AND ctg.rvindicator='Yes'
     ORDER BY c.comppct_r DESC,ch.hzdept_r ASC"""
    import httpx
    response=httpx.post(USDA_URL,data={"query":query,"format":"JSON+COLUMNNAME"},
                       timeout=22.0,follow_redirects=False,
                       headers={"Accept":"application/json","User-Agent":"Cropaganda Soil Guide/1.0"})
    response.raise_for_status()
    data=response.json()
    raw=data.get("Table") or []
    if not raw:
        return {"status":"no_coverage","message":"No published USDA soil map unit was returned for this point."}
    columns=[str(x).lower() for x in raw[0]]
    rows=[dict(zip(columns,row)) for row in raw[1:] if isinstance(row,list)]
    if not rows:
        return {"status":"no_coverage","message":"No USDA soil components were returned for this point."}
    selected=rows[0]
    profile={
        "mapunit_key":str(selected.get("mukey") or ""),
        "mapunit_symbol":selected.get("map_symbol"),
        "mapunit_name":selected.get("map_name"),
        "survey_area":selected.get("survey_area"),
        "component":selected.get("component_name"),
        "component_pct":_number(selected.get("component_pct")),
        "drainage_class":selected.get("drainage_class"),
        "slope_pct":_number(selected.get("slope_pct")),
        "hydrologic_group":selected.get("hydrologic_group"),
        "depth_top_cm":_number(selected.get("depth_top_cm")),
        "depth_bottom_cm":_number(selected.get("depth_bottom_cm")),
        "organic_matter_pct":_number(selected.get("organic_matter_pct")),
        "ph_water":_number(selected.get("ph_water")),
        "available_water_cm_per_cm":_number(selected.get("available_water_cm_per_cm")),
        "sand_pct":_number(selected.get("sand_pct")),
        "silt_pct":_number(selected.get("silt_pct")),
        "clay_pct":_number(selected.get("clay_pct")),
        "texture":selected.get("texture")
    }
    return {"status":"ok","profile":profile,"components_found":len(rows),
            "message":"Dominant published map-unit component; not a site-specific laboratory sample."}


def _smap_is_configured():
    return bool(os.getenv("EARTH_ENGINE_PROJECT") and os.getenv("EARTH_ENGINE_SERVICE_ACCOUNT_JSON"))


def _query_smap(lat,lon):
    import ee
    key=json.loads(os.environ["EARTH_ENGINE_SERVICE_ACCOUNT_JSON"])
    credentials=ee.ServiceAccountCredentials(key["client_email"],key_data=json.dumps(key))
    ee.Initialize(credentials,project=os.environ["EARTH_ENGINE_PROJECT"])
    pt=ee.Geometry.Point([lon,lat])
    stop=_now()+timedelta(days=1)
    start=stop-timedelta(days=31)
    images=(ee.ImageCollection(SMAP_COLLECTION)
        .filterBounds(pt).filterDate(start.strftime("%Y-%m-%d"),stop.strftime("%Y-%m-%d"))
        .sort("system:time_start",False).limit(24))
    # Apply the source's actual retrieval quality flag, not a modeled threshold.
    def record(item):
        image=ee.Image(item)
        sample=image.select(["soil_moisture_am","retrieval_qual_flag_am"]).reduceRegion(
            reducer=ee.Reducer.first(),geometry=pt,scale=9000,maxPixels=10000)
        return ee.Feature(None,{
            "date":ee.Date(image.get("system:time_start")).format("YYYY-MM-dd"),
            "moisture":sample.get("soil_moisture_am"),
            "quality":sample.get("retrieval_qual_flag_am")
        })
    items=ee.FeatureCollection(images.toList(24).map(record)).getInfo().get("features",[])
    readings=[]
    for item in items:
        p=item.get("properties") or {}
        moisture=_number(p.get("moisture"))
        quality=_number(p.get("quality"))
        if moisture is None or quality is None or quality!=0 or not 0<=moisture<=1:
            continue
        readings.append({"date":p["date"],"soil_moisture_m3_m3":round(moisture,4),
                         "quality":"passed"})
    readings.sort(key=lambda item:item["date"])
    return {"status":"ok" if readings else "no_data",
            "readings":readings,
            "latest":readings[-1] if readings else None,
            "message":("Latest valid 9 km-grid AM soil moisture observations."
                       if readings else "No quality-passing satellite retrievals for the last 30 days."),
            "resolution_km":9,"units":"m³/m³","dataset":SMAP_COLLECTION}


def install_soil_rotation_routes(app):
    @app.get("/api/soil/profile")
    def soil_profile(request:Request,latitude:float,longitude:float,refresh:bool=False):
        owner=_owner(request)
        lat,lon=_coords(latitude,longitude)
        if not (24<=lat<=72 and -180<=lon<=-60):
            return {"status":"outside_us_coverage","source":USDA_SOURCE,
                    "message":"USDA detailed soil mapping is for supported US areas. No inferred soil profile is displayed.",
                    "location":{"latitude":lat,"longitude":lon}}
        if not refresh:
            cache=_cache_get(owner,lat,lon,"usda",SOIL_TTL)
            if cache:return cache
        try:
            result=_query_usda(lat,lon)
        except Exception:
            return {"status":"unavailable","source":USDA_SOURCE,
                    "location":{"latitude":lat,"longitude":lon},
                    "message":"USDA Soil Data Access is unavailable. No guessed soil values are shown."}
        result.update({"source":USDA_SOURCE,"location":{"latitude":lat,"longitude":lon},
                       "checked_at":_now().isoformat(),"cache":"live"})
        if result["status"]=="ok":_cache_put(owner,lat,lon,"usda",result)
        return result

    @app.get("/api/soil/smap")
    def soil_smap(request:Request,latitude:float,longitude:float,refresh:bool=False):
        owner=_owner(request)
        lat,lon=_coords(latitude,longitude)
        extra={"source":SMAP_SOURCE,"location":{"latitude":lat,"longitude":lon},
               "dataset":SMAP_COLLECTION,"resolution_km":9,
               "documentation":"https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL3SMP_E_006"}
        if not _smap_is_configured():
            return {**extra,"status":"setup_required","readings":[],"latest":None,
                    "message":"SMAP sampling requires a registered Earth Engine project and server-side service-account credentials. This is separate from Google Calendar OAuth."}
        if not refresh:
            cache=_cache_get(owner,lat,lon,"smap",SMAP_TTL)
            if cache:return cache
        try:
            result=_query_smap(lat,lon)
        except Exception:
            return {**extra,"status":"unavailable","readings":[],"latest":None,
                    "message":"SMAP point sampling could not be completed; verify Earth Engine access and try again."}
        result.update(extra)
        result.update({"checked_at":_now().isoformat(),"cache":"live"})
        if result["status"]=="ok":_cache_put(owner,lat,lon,"smap",result)
        return result
