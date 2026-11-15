"""Archived PRISM GeoTIFF point samples extracted from user-supplied genuine rasters.

These are climate context at the NAMED sample points only, not gridded coverage
for arbitrary farm coordinates. 2022 data: 2.5 arc-minute (~4 km) annual
rasters. 2016 data: 30 arc-second (~800 m) annual rasters. Never use an
unverified nearby point as a location-specific farm measurement.
"""
from math import asin, cos, radians, sin, sqrt

# name, latitude, longitude, 2022 annual precipitation mm,
# 2022 mean / max / min air temperature deg C,
# 2022 mean dewpoint deg C, 2022 total / sloped solar MJ/m2/day,
# 2016 minimum / maximum air temperature deg C.
POINTS = [
 ("Queens, NY",40.7282,-73.7949,1132.76,13.14,17.18,9.11,6.04,14.27,14.30,9.69,17.81),
 ("Long Island, NY",40.806,-73.042,1065.73,12.15,16.69,7.61,6.26,14.22,14.24,7.85,16.92),
 ("Ithaca, NY",42.4439,-76.5019,850.35,9.48,15.42,3.54,3.69,13.02,13.04,3.68,16.15),
 ("Rochester, NY",43.1566,-77.6088,862.04,9.46,14.32,4.61,3.78,12.90,12.87,5.59,15.48),
 ("Buffalo, NY",42.8864,-78.8784,1185.51,9.55,13.88,5.22,4.31,13.15,13.16,6.61,14.20),
 ("Albany, NY",42.6526,-73.7562,1073.56,10.57,16.07,5.07,3.86,13.43,13.48,5.74,16.13),
 ("Syracuse, NY",43.0481,-76.1474,951.56,10.14,15.11,5.17,3.90,12.94,12.90,4.76,15.18),
 ("Binghamton, NY",42.0987,-75.918,1040.08,8.46,14.32,2.61,3.31,13.16,12.91,2.85,15.67),
 ("Poughkeepsie, NY",41.7004,-73.921,1075.43,10.80,16.83,4.77,4.27,13.73,13.74,5.0,17.27),
 ("Watertown, NY",43.9748,-75.9108,1226.15,7.91,13.23,2.59,2.97,12.77,12.72,3.37,14.01),
 ("Plattsburgh, NY",44.6995,-73.4529,913.91,8.17,13.26,3.08,2.18,13.01,13.00,3.41,13.80),
 ("Hudson, NY",42.2529,-73.7909,1125.89,10.79,16.55,5.03,4.28,13.49,13.43,5.39,17.02),
 ("Saratoga Springs, NY",43.0831,-73.7846,1224.36,9.86,15.94,3.78,3.44,13.46,13.49,4.38,16.07),
 ("Cortland, NY",42.6012,-76.1805,1109.17,7.64,13.18,2.11,3.16,12.98,12.74,3.31,14.52),
 ("Auburn, NY",42.9317,-76.5661,1127.19,9.10,14.34,3.86,4.39,12.92,12.89,3.96,15.10),
 ("Elmira, NY",42.0898,-76.8077,889.99,9.01,15.51,2.52,3.42,13.43,13.49,3.27,16.31),
 ("Canandaigua, NY",42.8875,-77.2817,815.24,9.39,14.71,4.08,4.01,13.24,13.20,5.19,15.5),
 ("Geneseo, NY",42.7959,-77.8169,748.78,9.29,14.95,3.63,3.68,13.19,13.16,4.41,15.56),
 ("Cooperstown, NY",42.7006,-74.9243,1324.06,7.26,13.06,1.46,2.63,13.15,13.13,3.13,13.66),
 ("New York City, NY",40.7128,-74.006,1127.00,13.35,17.40,9.30,5.98,13.94,13.94,9.98,17.99),
 ("Ames, IA",42.03,-93.62,888.25,8.69,14.77,2.61,3.44,14.36,14.38,4.97,16.15),
 ("Fresno, CA",36.74,-119.78,170.21,18.74,25.96,11.53,6.71,18.81,18.82,11.09,25.84),
 ("Lubbock, TX",33.58,-101.85,331.89,16.55,23.88,9.22,3.16,19.27,19.27,9.83,24.46),
 ("Pullman, WA",46.73,-117.18,642.11,8.62,14.59,2.65,1.80,14.01,14.02,3.95,15.85),
 ("Kearney, NE",40.70,-99.08,473.13,10.15,17.65,2.66,1.92,16.10,16.15,4.74,18.41),
 ("Tifton, GA",31.45,-83.51,1042.54,19.38,25.46,13.30,13.60,16.91,16.92,13.67,25.71)
]


# Additional 2016 PRISM annual 30-arcsecond raster samples (extracted directly
# from the uploaded tdmean and solslope GeoTIFFs, separate from 2022 grids).
PRISM_2016_SUPPLEMENT = {"Queens, NY":[6.03,13.89],"Long Island, NY":[6.28,14.1],"Ithaca, NY":[4.16,12.97],"Rochester, NY":[4.43,13.29],"Buffalo, NY":[5.17,13.48],"Albany, NY":[3.9,13.3],"Syracuse, NY":[4.33,13.1],"Binghamton, NY":[3.54,13.2],"Poughkeepsie, NY":[4.42,13.79],"Watertown, NY":[3.22,13.1],"Plattsburgh, NY":[2.66,12.73],"Hudson, NY":[4.36,13.57],"Saratoga Springs, NY":[3.33,13.56],"Cortland, NY":[4.46,12.81],"Auburn, NY":[4.44,13.1],"Elmira, NY":[3.82,13.27],"Canandaigua, NY":[4.28,13.49],"Geneseo, NY":[4.02,13.14],"Cooperstown, NY":[3.37,13.09],"New York City, NY":[6.34,13.95],"Ames, IA":[6.14,14.28],"Fresno, CA":[7.97,18.55],"Lubbock, TX":[6.22,18.7],"Pullman, WA":[3.13,14.2],"Kearney, NE":[4.55,15.33],"Tifton, GA":[14.05,17.37]}

def _kilometers(a, b, c, d):
    p1, p2 = radians(a), radians(c)
    dp, dl = radians(c-a), radians(d-b)
    h = sin(dp/2)**2 + cos(p1)*cos(p2)*sin(dl/2)**2
    return 12742 * asin(min(1, sqrt(h)))


def closest_prism_reference(lat, lon):
    nearest = min(POINTS, key=lambda p: _kilometers(lat, lon, p[1], p[2]))
    distance_km = round(_kilometers(lat, lon, nearest[1], nearest[2]), 1)
    if distance_km > 30:
        return {
            "status": "not_near_reference_point",
            "source": "PRISM archive 2016 and 2022 (uploaded GeoTIFF files)",
            "message": "No local archival sample was pre-extracted near this farm. Open PRISM Explorer for an exact grid cell; no values were substituted.",
            "reference_url": "https://prism.oregonstate.edu/explorer/"
        }
    return {
        "status": "reference_only",
        "source": "PRISM archival GeoTIFF samples; Oregon State University",
        "location_name": nearest[0],
        "sample_latitude": nearest[1],
        "sample_longitude": nearest[2],
        "distance_from_farm_km": distance_km,
        "sample_resolution_km": 4,
        "year_2022": {
            "precip_mm": nearest[3],
            "mean_temp_c": nearest[4],
            "max_temp_c": nearest[5],
            "min_temp_c": nearest[6],
            "dewpoint_c": nearest[7],
            "solar_total_mj_m2_day": nearest[8],
            "solar_slope_mj_m2_day": nearest[9]
        },
        "year_2016": {"min_temp_c": nearest[10], "max_temp_c": nearest[11],
                     "dewpoint_c": PRISM_2016_SUPPLEMENT.get(nearest[0], [None, None])[0],
                     "solar_slope_mj_m2_day": PRISM_2016_SUPPLEMENT.get(nearest[0], [None, None])[1]},
        "message": "Archived modeled climate at the named reference coordinate, not at your farm. The 2016 data are a separate finer-resolution grid. Not a forecast or 30-year climate normal.",
        "reference_url": "https://prism.oregonstate.edu/explorer/"
    }
