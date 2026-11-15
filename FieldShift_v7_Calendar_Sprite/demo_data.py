"""Fictional, isolated Cropaganda demo fixtures.

Every value in this module is GENERATED, not an ESP32, NASA, USDA, USGS,
PRISM, TigerData, NWS, or Google Calendar observation. No database access.
The source and demo flag travel with responses to prevent misattribution.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

DEMO_SOURCE="SIMULATED DEMO — NOT REAL FARM DATA"


def sample_session(request):
    try:
        return request.session.get("user", {}).get("mode") == "sample"
    except (AssertionError, AttributeError):
        return False


def soil_profile(lat, lon):
    return {
        "status": "ok", "demo": True, "simulated": True,
        "source": DEMO_SOURCE,
        "message": "SIMULATED soil characteristics — not a USDA survey or a laboratory test.",
        "location": {"latitude": lat, "longitude": lon},
        "profile": {
            "mapunit_key": "DEMO-001",
            "mapunit_name": "Fictional sandy loam demonstration soil",
            "survey_area": "DEMO ONLY — no survey area",
            "component": "Simulated sandy loam",
            "dominant_component": "Simulated sandy loam",
            "component_pct": 75,
            "selection_reason": "dominant",
            "texture": "Sandy loam (SIMULATED)",
            "drainage_class": "Well drained (SIMULATED)",
            "slope_pct": 2.5,
            "organic_matter_pct": 2.7,
            "ph_water": 6.4,
            "depth_top_cm": 0,
            "depth_bottom_cm": 25,
            "hydrologic_group": "B",
            "available_water_cm_per_cm": 0.14,
            "sand_pct": 62,
            "silt_pct": 26,
            "clay_pct": 12
        }
    }


def soil_context(lat, lon):
    src=DEMO_SOURCE
    return {
        "status": "ok", "demo": True, "simulated": True,
        "location": {"latitude": lat, "longitude": lon},
        "source": src,
        "climate": {
            "status": "ok", "simulated": True, "source": src,
            "annual_mean_air_temp_c": 17.8,
            "july_max_temp_c": 30.5,
            "annual_average_precip_mm_day": 1.35,
            "annual_equivalent_precip_mm": 492,
            "mean_solar_radiation_mj_m2_day": 17.6,
            "relative_humidity_pct": 58,
            "surface_pressure_kpa": 101.1,
        },
        "terrain": {
            "status": "ok", "simulated": True, "source": src,
            "elevation_m": 142.0,
            "northward_transect_slope_pct": 2.5
        },
        "water": {
            "status": "ok", "simulated": True, "source": src,
            "station_count": 2,
            "readings": [
                {"station": "Demo gauge A", "parameter": "streamflow",
                 "value": 0.83, "unit": "m³/s"}
            ]
        },
        "land_cover": {
            "status": "ok", "simulated": True, "source": src,
            "samples": [
                {"year": date.today().year-1, "status": "ok",
                 "land_cover": "Corn (simulated classification)", "code": 1},
                {"year": date.today().year-2, "status": "ok",
                 "land_cover": "Tomatoes (simulated classification)", "code": 12}
            ]
        },
        "prism_reference": {
            "status": "demo", "source": src,
            "message": "SIMULATED climate example; no historical PRISM raster sampled."
        },
        "other_sources": [
            {"name": "Fictional Soil & Rotation demo", "status": "simulated",
             "note": "All soil, terrain, water and crop classifications shown here are fabricated for exploring the interface."}
        ]
    }


def sample_weather(lat, lon):
    today=date.today()
    descriptions=("Sunny", "Partly cloudy", "Cloudy", "Light showers",
                  "Clear", "Partly cloudy", "Sunny")
    forecast=[]
    for i in range(7):
        forecast.append({
            "date": (today+timedelta(days=i)).isoformat(),
            "summary": "SIMULATED: "+descriptions[i],
            "high_c": round(24.4 + ((i*3)%7-3),1),
            "low_c": round(14.2 + ((i*2)%5-2),1),
            "rain_chance_pct": (i*13)%45
        })
    return {
        "mode": "demo", "demo": True,
        "forecast": forecast,
        "forecast_source": "SIMULATED weather example — not Open-Meteo or a real forecast",
        "current": None,
        "alert_status": {"status":"demo","alerts":[],
                         "message":"Demonstration only; no actual weather alerts queried."},
        "location": {"latitude":lat,"longitude":lon,
                     "label":"Fictional example farm"},
        "errors": []
    }


def archive_dates():
    today=date.today()
    return [(today-timedelta(days=i)).isoformat() for i in range(7)]


def archive_snapshots(day):
    parsed=date.fromisoformat(day)
    if parsed>date.today() or parsed<date.today()-timedelta(days=6):
        return []
    return [
        {"bucket_at": datetime(parsed.year,parsed.month,parsed.day,hour,0,
                                tzinfo=timezone.utc).isoformat(),
         "recorded_at": datetime(parsed.year,parsed.month,parsed.day,hour,0,
                                 tzinfo=timezone.utc).isoformat(),
         "device_id": "DEMO-ESP32-SIMULATED"}
        for hour in (14,20)
    ]


def archive_reading(day,bucket):
    options=archive_snapshots(day)
    if not any(r["bucket_at"]==bucket for r in options):
        return None
    return {"recorded_at":bucket,"device_id":"DEMO-ESP32-SIMULATED",
            "temperature_c":24.5,"humidity_pct":52.1,"pressure_hpa":1013.2,
            "altitude_m":140,"soil_moisture_pct":45.8,"rain_wetness_pct":12.5,
            "light_pct":65.2}
