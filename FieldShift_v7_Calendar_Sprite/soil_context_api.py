"""Read-only agricultural context sources for Cropaganda Soil & Rotation.

Each measurement preserves its source and vintage. Never substitute the example
hub values from Gemini's dataset script for farmer observations.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging
import time
from functools import lru_cache
import math
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import httpx
from fastapi import Request

from device_api import _owner
from soil_rotation_api import _cache_get, _cache_put, _coords

log = logging.getLogger(__name__)
CACHE_FOR = timedelta(hours=12)

# Only genuine, extracted point samples from the 2016/2022 PRISM rasters
# supplied with this project are used. See prism_reference.py for limitations.
from prism_reference import closest_prism_reference


def _num(value):
    try:
        value = float(value)
        return round(value, 3) if math.isfinite(value) and value not in (-999, -9999, -999.0, -9999.0) and value > -9000 else None
    except (TypeError, ValueError):
        return None


def _get(url, params, timeout=9.0):
    response = httpx.get(url, params=params, timeout=timeout,
                         follow_redirects=False, headers={
                             "Accept": "application/json",
                             "User-Agent": "Cropaganda soil reference/2.0"
                         })
    response.raise_for_status()
    return response.json()


def _power_climatology(lat, lon):
    """NASA POWER climatology; historical regional averages, not current weather."""
    params = {
        "parameters": "T2M,T2M_MAX,PRECTOTCORR,ALLSKY_SFC_SW_DWN,RH2M,PS",
        "community": "AG", "longitude": lon, "latitude": lat, "format": "JSON"
    }
    raw = _get("https://power.larc.nasa.gov/api/temporal/climatology/point", params)
    p = raw.get("properties", {}).get("parameter", {})
    def val(k, period="ANN"):
        return _num((p.get(k) or {}).get(period))
    mm_day = val("PRECTOTCORR")
    return {
        "status": "ok" if val("T2M") is not None or mm_day is not None else "no_data",
        "source": "NASA POWER agroclimatology",
        "type": "historical_climatology",
        "annual_mean_air_temp_c": val("T2M"),
        "july_max_temp_c": val("T2M_MAX", "JUL"),
        "annual_average_precip_mm_day": mm_day,
        "annual_equivalent_precip_mm": round(mm_day * 365.25, 1) if mm_day is not None else None,
        "mean_solar_radiation_mj_m2_day": val("ALLSKY_SFC_SW_DWN"),
        "relative_humidity_pct": val("RH2M"),
        "surface_pressure_kpa": val("PS"),
        "note": "Long-term regional climate averages; annualized rainfall is derived, not a forecast or GPM gauge."
    }


def _usgs_terrain(lat, lon):
    """Two USGS 3DEP point elevations; northward rise/run is a transect estimate."""
    url = "https://epqs.nationalmap.gov/v1/json"
    first = _get(url, {"x": lon, "y": lat, "wkid": 4326, "units": "Meters"})
    north_lat = min(lat + 0.00027, 90)
    second = _get(url, {"x": lon, "y": north_lat, "wkid": 4326, "units": "Meters"})
    a, b = _num(first.get("value")), _num(second.get("value"))
    if a is None or b is None:
        return {"status": "no_data", "source": "USGS 3DEP Elevation Point Query Service",
                "message": "One or both terrain elevations were unavailable."}
    distance_m = 111195 * (north_lat - lat)
    slope = abs(b-a) / distance_m * 100 if distance_m else None
    return {"status": "ok", "source": "USGS 3DEP Elevation Point Query Service",
            "elevation_m": a, "northward_transect_slope_pct": round(slope, 2),
            "resolution_note": "Approximate 30 m northward elevation transect; NOT a full terrain slope and NOT a USDA drainage class."}


def _usgs_water(lat, lon):
    """Return gauge context only; streamflow is not on-farm soil wetness."""
    # USGS NWIS requires min/max lon/lat; a broad 0.5 degree box is permitted.
    params = {"format": "json",
              "bBox": f"{lon-.25:.4f},{lat-.25:.4f},{lon+.25:.4f},{lat+.25:.4f}",
              "parameterCd": "00060,72019", "siteStatus": "active"}
    raw = _get("https://waterservices.usgs.gov/nwis/iv/", params)
    series = raw.get("value", {}).get("timeSeries") or []
    readings = []
    for item in series[:8]:
        source = item.get("sourceInfo") or {}
        variable = item.get("variable") or {}
        vals = (item.get("values") or [{}])[0].get("value") or []
        last = vals[-1] if vals else {}
        value = _num(last.get("value"))
        if value is None:
            continue
        readings.append({"station": source.get("siteName"), "parameter": variable.get("variableCode", [{}])[0].get("value"),
                         "value": value, "unit": (variable.get("unit") or {}).get("unitCode"),
                         "observed_at": last.get("dateTime")})
    return {"status": "ok" if readings else "no_data",
            "source": "USGS NWIS nearby water gauges",
            "station_count": len(series), "readings": readings,
            "note": "Regional streamflow/groundwater gauge context; not soil moisture at the farm."}




def _albers5070(lat, lon):
    """Precise GRS80 NAD83 CONUS Albers equal-area point projection (EPSG:5070).
    Unlike Gemini's linear lat/lon approximation, this matches the projection
    used by the USDA CropScape 30 m point-value service.
    """
    a = 6378137.0
    flattening = 1 / 298.257222101
    e = math.sqrt(2 * flattening - flattening * flattening)
    def m(phi):
        return math.cos(phi) / math.sqrt(1 - e * e * math.sin(phi)**2)
    def q(phi):
        sin_phi = math.sin(phi)
        return (1-e*e)*(sin_phi / (1-e*e*sin_phi*sin_phi)
                - math.log((1-e*sin_phi)/(1+e*sin_phi))/(2*e))
    phi1, phi2, origin_phi = map(math.radians, (29.5, 45.5, 23.0))
    n = (m(phi1)**2-m(phi2)**2)/(q(phi2)-q(phi1))
    C = m(phi1)**2 + n*q(phi1)
    rho0 = a*math.sqrt(C-n*q(origin_phi))/n
    theta = n*math.radians(lon+96)
    rho = a*math.sqrt(C-n*q(math.radians(lat)))/n
    return (round(rho*math.sin(theta), 2),
            round(rho0-rho*math.cos(theta), 2))


# A bounded subset of USDA's official Cropland Data Layer class dictionary.
_CDL_CLASSES = {
    0:"Background",1:"Corn",4:"Sorghum",5:"Soybeans",21:"Barley",
    23:"Spring Wheat",24:"Winter Wheat",26:"Double Crop Winter Wheat/Soybeans",
    27:"Rye",28:"Oats",36:"Alfalfa",37:"Other Hay",43:"Potatoes",
    47:"Miscellaneous Vegetables and Fruits",51:"Chickpeas",54:"Tomatoes",
    58:"Clover/Wildflowers",61:"Fallow/Idle Cropland",
    62:"Pasture/Grass",111:"Open Water",121:"Developed/Open Space",
    122:"Developed/Low Intensity",123:"Developed/Medium Intensity",
    124:"Developed/High Intensity",141:"Deciduous Forest",
    142:"Evergreen Forest",143:"Mixed Forest",176:"Grassland/Pasture",
    190:"Woody Wetlands",195:"Herbaceous Wetlands"
}


def _usda_cdl(lat, lon):
    """Two released CDL classification years; never assume one pixel = crop rotation."""
    x, y = _albers5070(lat, lon)
    samples = []
    for year in (2025, 2024):
        try:
            response = httpx.get(
                "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue",
                params={"year":year,"x":x,"y":y},
                timeout=8.0, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > 16000:
                raise ValueError("Unexpectedly large CDL response")
            root = ET.fromstring(response.content)
            tokens = []
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1].lower()
                if tag in ("result", "return", "getcdlvaluereturn", "value"):
                    value = (element.text or "").strip()
                    if re.fullmatch(r"\d{1,3}", value):
                        tokens.append(int(value))
            if not tokens:
                samples.append({"year":year,"status":"no_data"})
                continue
            code = tokens[0]
            samples.append({"year":year,"status":"ok","code":code,
                            "land_cover":_CDL_CLASSES.get(code, "Other mapped land-cover class")})
        except Exception:
            log.info("USDA NASS CDL %s unavailable at %.4f, %.4f",year,lat,lon)
            samples.append({"year":year,"status":"unavailable"})
    return {"status":"ok" if any(row["status"]=="ok" for row in samples) else "unavailable",
            "source":"USDA NASS Cropland Data Layer (CropScape)",
            "resolution_m":30,
            "samples":samples,
            "note":"30 m classified land cover at selected coordinate, not a verified field boundary or crop planting record. Crop classes may be misclassified."}

def _safe_fetch(name, fn, lat, lon):
    try:
        return fn(lat, lon)
    except Exception:
        log.exception("Soil context provider failed: %s", name)
        return {"status": "unavailable", "source": name,
                "message": "Provider unavailable. No default or synthetic numbers substituted."}


from demo_data import sample_session

def _build_public_context(lat, lon):
    """Query independent PUBLIC providers and convert results to source-labelled JSON."""
    # These independent public providers should never hold one another up.
    providers = {
        "climate": _power_climatology,
        "terrain": _usgs_terrain,
        "water": _usgs_water,
        "land_cover": _usda_cdl,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(_safe_fetch, name, fn, lat, lon)
                   for name, fn in providers.items()}
        results = {name: future.result() for name, future in futures.items()}
    prism = closest_prism_reference(lat, lon)
    response = {
        "status": "ok", "location": {"latitude": lat, "longitude": lon},
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "climate": results["climate"],
        "terrain": results["terrain"],
        "water": results["water"],
        "land_cover": results["land_cover"],
        "prism_reference": prism,
        "other_sources": [
            {"name": "USDA Cropland Data Layer", "status": "connected",
             "url": "https://nassgeodata.gmu.edu/CropScape/",
             "note": "Exact EPSG:5070 point-classification requests for 2024 and 2025; land cover is not verified crop history."},
            {"name": "USDA NASS QuickStats", "status": "reference_only",
             "url": "https://quickstats.nass.usda.gov/",
             "note": "County-specific yield queries need a NASS API key and verified county/commodity identifiers."},
            {"name": "USDA AMS Market News", "status": "reference_only",
             "url": "https://mymarketnews.ams.usda.gov/",
             "note": "Hardcoded commodity prices in the example are not live market quotes."},
            {"name": "OpenET", "status": "reference_only",
             "url": "https://openetdata.org/",
             "note": "Farm-point ET requires the applicable access/API authorization."}
        ]
    }

    return response

@lru_cache(maxsize=48)
def _demo_public_context(lat:float,lon:float,cache_bucket:int):
    # A process-local TTL cache reduces public upstream calls. Never access
    # another farmer's TigerData soil documents or store this sample in SQL.
    return {**_build_public_context(lat,lon),"demo":True,
            "public_provider_data":True,"cache":"public_demo_memory_only",
            "note":"Real public regional estimates for example/demo coordinates. "
                   "ESP32 readings and calendar tasks remain simulated."}

def install_soil_context_routes(app):
    @app.get("/api/soil/context")
    def soil_context(request: Request, latitude: float, longitude: float, refresh: bool = False):
        if sample_session(request):
            lat, lon = _coords(latitude, longitude)
            if not (24 <= lat <= 50 and -125 <= lon <= -66):
                return {"status":"outside_coverage","demo":True,
                        "message":"US soil context sources cover the contiguous USA.",
                        "location":{"latitude":lat,"longitude":lon}}
            return _demo_public_context(round(lat,3),round(lon,3),int(time.time()//3600))
        owner = _owner(request)
        lat, lon = _coords(latitude, longitude)
        if not (24 <= lat <= 50 and -125 <= lon <= -66):
            return {"status": "outside_coverage", "message": "The sources below cover the contiguous USA.",
                    "location": {"latitude": lat, "longitude": lon}}
        if not refresh:
            cached = _cache_get(owner, lat, lon, "soil_context_v2", CACHE_FOR)
            if cached:
                return cached

        response=_build_public_context(lat,lon)
        # Cache only actual public provider results for this authenticated account.
        if all((response.get(key) or {}).get("status")!="unavailable"
               for key in ("climate","terrain","water","land_cover")):
            _cache_put(owner,lat,lon,"soil_context_v2",response)
        return response
