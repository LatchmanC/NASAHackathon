"""Real USDA Soil Data Access and opt-in NASA SMAP/Google Earth Engine sampling.
No synthetic soil, satellite, hardware, price or yield values are generated.
Both routes require an authenticated Auth0 account; cache stays account-isolated.
"""
from __future__ import annotations
import json
import math
import os
import logging
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from device_api import _owner
from fieldshift_core import valid_lat_lon

USDA_URL="https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
USDA_SOURCE="USDA NRCS Soil Data Access (SSURGO/Soil Data Mart)"
SMAP_SOURCE="NASA SMAP SPL3SMP_E v006 AM, via Google Earth Engine"
SMAP_COLLECTION="NASA/SMAP/SPL3SMP_E/006"
logger=logging.getLogger(__name__)
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



def _interpret_usda_table(data):
    """Preserve map-unit coverage even when the dominant component is unrated."""
    raw = data.get("Table") or []
    if len(raw) < 2:
        return {"status": "no_coverage",
                "message": "No published USDA soil map unit was returned for this point. Use precise farm coordinates rather than a city center."}
    columns = [str(x).lower() for x in raw[0]]
    rows = [dict(zip(columns, row)) for row in raw[1:] if isinstance(row, list)]
    if not rows:
        return {"status": "no_coverage",
                "message": "USDA returned no mapped soil components at this point. Check the exact farm coordinates."}

    # Rows are ordered by surveyed component percentage, not site-specific certainty.
    dominant = rows[0]
    unrated = {"", "not rated", "not assigned", "none", "null", "n/a"}
    def has_rating(row):
        return str(row.get("drainage_class") or "").strip().lower() not in unrated

    # If the largest component has no drainage class (common for urban or
    # disturbed land), show the largest *rated* alternative and disclose that
    # it is not the dominant component. Never fabricate a drainage class.
    rated = next((row for row in rows if has_rating(row)), None)
    selected = rated or dominant
    alternative = rated is not None and (
        selected.get("component_name") != dominant.get("component_name")
        or selected.get("mukey") != dominant.get("mukey")
    )
    selected_drainage = str(selected.get("drainage_class") or "").strip() if rated else None
    component_keys = {
        (str(row.get("mukey") or ""), str(row.get("component_name") or ""))
        for row in rows
    }
    profile = {
        "mapunit_key": str(selected.get("mukey") or ""),
        "mapunit_symbol": selected.get("map_symbol"),
        "mapunit_name": selected.get("map_name"),
        "survey_area": selected.get("survey_area"),
        "component": selected.get("component_name"),
        "component_pct": _number(selected.get("component_pct")),
        "dominant_component": dominant.get("component_name"),
        "selection_reason": "rated_alternative" if alternative else "dominant",
        "drainage_class": selected_drainage,
        "slope_pct": _number(selected.get("slope_pct")),
        "hydrologic_group": selected.get("hydrologic_group"),
        "depth_top_cm": _number(selected.get("depth_top_cm")),
        "depth_bottom_cm": _number(selected.get("depth_bottom_cm")),
        "organic_matter_pct": _number(selected.get("organic_matter_pct")),
        "ph_water": _number(selected.get("ph_water")),
        "available_water_cm_per_cm": _number(selected.get("available_water_cm_per_cm")),
        "sand_pct": _number(selected.get("sand_pct")),
        "silt_pct": _number(selected.get("silt_pct")),
        "clay_pct": _number(selected.get("clay_pct")),
        "texture": selected.get("texture")
    }
    if alternative:
        message = ("The dominant map-unit component has no drainage rating. "
                   "Showing a rated secondary component instead; this is not "
                   "verified drainage at the precise farm location.")
    elif rated:
        message = ("Published USDA drainage for the dominant mapped soil component; "
                   "not a site-specific soil test.")
    else:
        message = ("USDA mapped this location, but no surveyed component has a "
                   "rated drainage class. This is possible on urban, disturbed, "
                   "or miscellaneous land. Try the exact farm coordinates.")
    return {
        "status": "ok", "profile": profile,
        "drainage_status": "rated_secondary" if alternative else "rated" if rated else "unrated",
        "components_found": len(component_keys),
        "message": message
    }


def _sda_rows(sql):
    """USDA SDA tabular POST: column names are row zero in JSON+COLUMNNAME."""
    import httpx
    response = httpx.post(
        USDA_URL, json={"query": sql, "format": "JSON+COLUMNNAME"},
        timeout=19.0, follow_redirects=False,
        headers={"Accept": "application/json", "User-Agent": "Cropaganda Soil Guide/2.0"})
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise ValueError("USDA SDA returned an error response")
    table = payload.get("Table") or []
    if not table:
        return []
    if not isinstance(table[0], list):
        raise ValueError("USDA SDA returned unexpected column metadata")
    columns = [str(value).lower() for value in table[0]]
    return [dict(zip(columns, row)) for row in table[1:]
            if isinstance(row, list) and len(row) == len(columns)]


def _query_usda(lat, lon):
    """Resolve the actual map unit first; then query its individual components.

    Two small SQL requests avoid a costly spatial join with multiple horizon
    and texture rows, which has been unreliable for some NY locations.
    """
    wkt = f"POINT({lon:.5f} {lat:.5f})"
    spatial_sql = ("SELECT TOP 1 mukey FROM "
                   f"SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')")
    matched = _sda_rows(spatial_sql)
    if not matched:
        return {"status": "no_coverage",
                "message": "USDA has no intersecting soil map unit at these coordinates. "
                           "Try actual field coordinates instead of a city-center preset."}
    mukey = str(matched[0].get("mukey") or "")
    if not mukey.isdigit():
        raise ValueError("USDA returned a nonnumeric map unit key")

    # Do NOT filter out minor components; urban map units sometimes contain a
    # rated secondary component even if the dominant one is not rated.
    component_sql = f"""
    SELECT TOP 40
       mu.mukey AS mukey, mu.musym AS map_symbol,
       mu.muname AS map_name, le.areasymbol AS survey_area,
       c.compname AS component_name, c.comppct_r AS component_pct,
       c.drainagecl AS drainage_class, c.slope_r AS slope_pct,
       c.hydgrp AS hydrologic_group,
       ch.hzdept_r AS depth_top_cm, ch.hzdepb_r AS depth_bottom_cm,
       ch.om_r AS organic_matter_pct, ch.ph1to1h2o_r AS ph_water,
       ch.awc_r AS available_water_cm_per_cm,
       ch.sandtotal_r AS sand_pct, ch.silttotal_r AS silt_pct,
       ch.claytotal_r AS clay_pct
    FROM mapunit mu
    JOIN legend le ON le.lkey = mu.lkey
    LEFT JOIN component c ON c.mukey = mu.mukey
    LEFT JOIN chorizon ch ON ch.cokey = c.cokey AND ch.hzdept_r = 0
    WHERE mu.mukey = '{mukey}'
    ORDER BY c.comppct_r DESC
    """
    rows = _sda_rows(component_sql)
    if not rows:
        return {"status": "no_components",
                "message": "USDA identified a map unit but published no component properties."}

    # Texture is a useful optional lookup, not a reason to lose drainage if
    # the texture join or value is unavailable. Separate it from the main SQL.
    try:
        first = rows[0]
        # The top-horizon texture may be absent; do not label the soil series
        # as a measured texture.
        texture_sql = f"""
        SELECT TOP 30 c.compname AS component_name, ctg.texture AS texture
        FROM component c
        JOIN chorizon ch ON ch.cokey = c.cokey AND ch.hzdept_r = 0
        JOIN chtexturegrp ctg ON ctg.chkey = ch.chkey AND ctg.rvindicator = 'Yes'
        WHERE c.mukey = '{mukey}'
        ORDER BY c.comppct_r DESC
        """
        textures = _sda_rows(texture_sql)
        for row in rows:
            value = next((item.get("texture") for item in textures
                          if item.get("component_name") == row.get("component_name")
                          and item.get("texture")), None)
            row["texture"] = value
    except Exception:
        logger.info("Optional USDA texture lookup unavailable for map unit %s", mukey)
        for row in rows:
            row["texture"] = None

    columns = ["mukey", "map_symbol", "map_name", "survey_area",
               "component_name", "component_pct", "drainage_class", "slope_pct",
               "hydrologic_group", "depth_top_cm", "depth_bottom_cm",
               "organic_matter_pct", "ph_water", "available_water_cm_per_cm",
               "sand_pct", "silt_pct", "clay_pct", "texture"]
    values = [[row.get(col) for col in columns] for row in rows]
    result = _interpret_usda_table({"Table": [columns, *values]})
    result["lookup_method"] = "point -> map unit -> component (separate SDA requests)"
    return result



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
            logger.exception("USDA Soil Data Access request failed")
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
                    "message":"SMAP Level-3 sampling needs EARTH_ENGINE_PROJECT and EARTH_ENGINE_SERVICE_ACCOUNT_JSON in the server environment. Google Calendar OAuth cannot authenticate Earth Engine.",
                    "missing_configuration":[name for name in ("EARTH_ENGINE_PROJECT","EARTH_ENGINE_SERVICE_ACCOUNT_JSON") if not os.getenv(name,"").strip()]}
        if not refresh:
            cache=_cache_get(owner,lat,lon,"smap",SMAP_TTL)
            if cache:return cache
        try:
            result=_query_smap(lat,lon)
        except Exception:
            logger.exception("Earth Engine SMAP sampling failed")
            return {**extra,"status":"unavailable","readings":[],"latest":None,
                    "message":"SMAP point sampling could not be completed; verify Earth Engine access and try again."}
        result.update(extra)
        result.update({"checked_at":_now().isoformat(),"cache":"live"})
        if result["status"]=="ok":_cache_put(owner,lat,lon,"smap",result)
        return result
