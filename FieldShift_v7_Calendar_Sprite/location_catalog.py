"""Bundled offline country → region → city approximate-center coordinates.

No geocoding web request or API key is necessary to select a preset.
An exact rural farm site should always use manual coordinates.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from fieldshift_core import valid_lat_lon

CATALOG_FILE = Path(__file__).with_name('locations_catalog.json')

@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG_FILE.read_text(encoding='utf-8'))


def resolve_preset(country, region, city):
    if not all(isinstance(v, str) and v for v in (country, region, city)):
        raise ValueError('Choose country, state/region and city from the dropdowns.')
    countries = catalog()
    try:
        record = countries[country]
        coords = record['regions'][region][city]
    except (KeyError, TypeError):
        raise ValueError('That location is not in the offline list. Choose another city or use exact coordinates.') from None
    lat, lon = valid_lat_lon(*coords)
    return {'mode':'preset', 'country':country, 'region':region, 'city':city,
            'label':f'{city}, {region}, {record["name"]}',
            'latitude':lat, 'longitude':lon,
            'resolution':'approximate city center (not a precise farm location)'}
