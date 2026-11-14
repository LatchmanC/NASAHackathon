"""Local Python test receiver that stands in for the ESP32 + persistent storage.
The real ESP32 will replace this simulation endpoint when flashed with firmware.
"""
from __future__ import annotations
import argparse
import time
from fieldshift_core import StationDB
from station_service import StationEngine

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    engine=StationEngine(db=StationDB(),host='127.0.0.1',port=args.port,simulator=False,cloud_period=6).start()
    print(f'ESP32 simulation receiver running on http://127.0.0.1:{args.port}',flush=True)
    try:
        while True:time.sleep(1)
    except KeyboardInterrupt:pass
    finally:engine.close()

if __name__=='__main__':main()
