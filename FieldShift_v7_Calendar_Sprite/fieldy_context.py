"""Small, attributed context for Fieldy's conversational Gemini requests.

The browser provides current Soil & Rotation *view* selections. Authoritative
USDA/POWER/CDL/etc results are preferably obtained from account-specific
TigerData caches; client snapshots are only a clearly labelled fallback.
"""
from __future__ import annotations

import math
from datetime import timedelta
from soil_rotation_api import _cache_get, SOIL_TTL
from soil_context_api import CACHE_FOR
from prism_reference import closest_prism_reference

USDA_FIELDS = ("mapunit_name", "component", "dominant_component",
               "selection_reason", "component_pct", "texture",
               "drainage_class", "slope_pct", "organic_matter_pct",
               "ph_water", "hydrologic_group", "available_water_cm_per_cm",
               "sand_pct", "silt_pct", "clay_pct")
CLIMATE_FIELDS = ("annual_mean_air_temp_c", "july_max_temp_c",
                  "annual_average_precip_mm_day","annual_equivalent_precip_mm",
                  "mean_solar_radiation_mj_m2_day", "relative_humidity_pct")
TERRAIN_FIELDS = ("elevation_m", "northward_transect_slope_pct")
CDL_FIELDS = ("year", "code", "land_cover")


def compact_history(items):
    """Only limited ordinary user/assistant turns; never any system role."""
    if not isinstance(items,list):return []
    output=[]
    for item in items[-16:]:
        if not isinstance(item,dict) or item.get("role") not in ("user","assistant"):
            continue
        text=item.get("content")
        if not isinstance(text,str) or not text.strip():continue
        output.append({"role":item["role"],"content":text.strip()[:1400]})
    return output[-12:]


def _clean(value, limit=150):
    if value is None or isinstance(value,bool):return None
    if isinstance(value,(int,float)):
        return round(float(value),3) if math.isfinite(float(value)) else None
    if isinstance(value,str):
        return value[:limit]
    return None


def _fields(data,names):
    if not isinstance(data,dict):return {}
    return {name:clean for name in names if (clean:=_clean(data.get(name))) is not None}


def _browser_soil(view,lat,lon):
    if not isinstance(view,dict):return {}
    try:
        if abs(float(view.get("latitude"))-lat)>.00011 or abs(float(view.get("longitude"))-lon)>.00011:
            return {}
    except (ValueError,TypeError):
        return {}
    result={}
    if view.get("profile_status")=="ok":
        result["usda_visible_profile"]=_fields(view.get("profile"),USDA_FIELDS)
    context=view.get("context")
    if isinstance(context,dict):
        c=context.get("climate")
        if isinstance(c,dict) and c.get("status")=="ok":
            result["nasa_power_visible"]=_fields(c,CLIMATE_FIELDS)
        terrain=context.get("terrain")
        if isinstance(terrain,dict) and terrain.get("status")=="ok":
            result["usgs_terrain_visible"]=_fields(terrain,TERRAIN_FIELDS)
        cover=context.get("land_cover")
        if isinstance(cover,dict) and cover.get("status")=="ok":
            results=[_fields(x,CDL_FIELDS) for x in (cover.get("samples") or [])[:3] if isinstance(x,dict) and x.get("status")=="ok"]
            if results:result["usda_cdl_visible"]=results
    guide=view.get("crop_guide")
    if isinstance(guide,dict):
        # User's current crop guide selection is reference advice, not a
        # measured farm property or proof a crop was planted.
        result["selected_crop_guide"]=_fields(guide,("name","type","family","water","watch","soil","soilTip","season","before","after"))
    goal=_clean(view.get("rotation_goal"),70)
    if goal:result["rotation_goal"]=goal
    current=_clean(view.get("current_crop"),80)
    if current:result["current_crop"]=current
    return result


def fieldy_soil_context(owner,lat,lon,view):
    pointlat,pointlon=round(float(lat),5),round(float(lon),5)
    client=_browser_soil(view,float(lat),float(lon))
    info={
        "interpretation":"Soil surveys are map-unit estimates, not lab tests. "
          "Regional climate, land-cover, and PRISM archive are not ESP32 readings.",
        "crop_and_rotation_view":{"current_crop":client.get("current_crop"),
                 "rotation_goal":client.get("rotation_goal"),
                 "selected_crop_guide":client.get("selected_crop_guide")},
        "prism_historical_reference":closest_prism_reference(lat,lon)
    }
    usda=None
    climate=None
    try:
        usda=_cache_get(owner,pointlat,pointlon,"usda",SOIL_TTL)
    except Exception:pass
    try:
        climate=_cache_get(owner,pointlat,pointlon,"soil_context_v2",CACHE_FOR)
    except Exception:pass
    if isinstance(usda,dict) and usda.get("status")=="ok":
        info["usda_soil_survey"]={"status":"server_cached","source":"USDA NRCS SSURGO",
              "profile":_fields(usda.get("profile"),USDA_FIELDS)}
    elif client.get("usda_visible_profile"):
        info["usda_soil_survey"]={"status":"browser_view_not_server_verified",
              "source":"Previously displayed USDA survey panel (browser relay)",
              "profile":client["usda_visible_profile"]}
    else:
        info["usda_soil_survey"]={"status":"unavailable"}
    if isinstance(climate,dict):
        for key,fields in (("climate",CLIMATE_FIELDS),("terrain",TERRAIN_FIELDS)):
            item=climate.get(key)
            if isinstance(item,dict) and item.get("status")=="ok":
                info[key]={"status":"server_cached","source":item.get("source",key),
                            "values":_fields(item,fields)}
        cover=climate.get("land_cover")
        if isinstance(cover,dict) and cover.get("status")=="ok":
            info["land_cover"]={"status":"server_cached","source":"USDA CDL",
              "samples":[_fields(x,CDL_FIELDS) for x in (cover.get("samples") or [])[:3] if isinstance(x,dict) and x.get("status")=="ok"]}
    for key,browser_key,source in (
        ("climate","nasa_power_visible","NASA POWER historical climate (browser panel)"),
        ("terrain","usgs_terrain_visible","USGS terrain (browser panel)"),
        ("land_cover","usda_cdl_visible","USDA CDL classified cover (browser panel)")):
        if key not in info and client.get(browser_key):
            info[key]={"status":"browser_view_not_server_verified",
                       "source":source,"values":client[browser_key]}
    return info
