"""Read-only agricultural context sources for Cropaganda Soil & Rotation.

Each measurement preserves its source and vintage. Never substitute the example
hub values from Gemini's dataset script for farmer observations.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging
import math
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
        return round(value, 3) if math.isfinite(value) and value > -9000 else None
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


def _safe_fetch(name, fn, lat, lon):
    try:
        return fn(lat, lon)
    except Exception:
        log.exception("Soil context provider failed: %s", name)
        return {"status": "unavailable", "source": name,
                "message": "Provider unavailable. No default or synthetic numbers substituted."}


def install_soil_context_routes(app):
    @app.get("/api/soil/context")
    def soil_context(request: Request, latitude: float, longitude: float, refresh: bool = False):
        owner = _owner(request)
        lat, lon = _coords(latitude, longitude)
        if not (24 <= lat <= 50 and -125 <= lon <= -66):
            return {"status": "outside_coverage", "message": "The sources below cover the contiguous USA.",
                    "location": {"latitude": lat, "longitude": lon}}
        if not refresh:
            cached = _cache_get(owner, lat, lon, "soil_context_v2", CACHE_FOR)
            if cached:
                return cached

        # These independent public providers should never hold one another up.
        providers = {
            "climate": _power_climatology,
            "terrain": _usgs_terrain,
            "water": _usgs_water,
        }
        with ThreadPoolExecutor(max_workers=3) as pool:
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
            "prism_reference": prism,
            "other_sources": [
                {"name": "NASA SMAP Level-3", "status": "separate_endpoint", "path": "/api/soil/smap",
                 "note": "Numeric satellite readings require authorized Earth Engine server credentials."},
                {"name": "USDA Cropland Data Layer", "status": "reference_only",
                 "url": "https://nassgeodata.gmu.edu/CropScape/",
                 "note": "The example script's Albers coordinate approximation is not accurate enough for 30 m crop history."},
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
        # Cache only actual source results and sample metadata, never estimated weather.
        if all(v.get("status") != "unavailable" for v in results.values()):
            _cache_put(owner, lat, lon, "soil_context_v2", response)
        return response
