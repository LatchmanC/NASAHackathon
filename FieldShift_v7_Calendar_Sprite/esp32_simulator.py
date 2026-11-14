"""Standalone synthetic ESP32 sender. Runs on any computer; no physical ESP32 needed."""
import argparse
import os
import time
from fieldshift_core import SensorSimulator, http_json


def main():
    p = argparse.ArgumentParser(description='Synthetic ESP32 -> local HTTP test receiver')
    p.add_argument('--receiver', default='http://127.0.0.1:8765', help='Local ESP32 simulation receiver origin')
    p.add_argument('--interval', type=float, default=3, help='Seconds between samples')
    p.add_argument('--count', type=int, default=0, help='0 means continuous')
    args = p.parse_args()
    sim = SensorSimulator(device_id='external-esp32-simulator',seed=24)
    headers = {'X-Device-Token':os.getenv('FIELDSHIFT_DEVICE_TOKEN','local-demo-secret')}
    sent = 0
    print(f'Sending SIMULATED ESP32 readings to {args.receiver.rstrip("/")}/api/ingest (Ctrl+C to stop)')
    try:
        while not args.count or sent < args.count:
            packet = sim.sample()
            try:
                response = http_json('POST',args.receiver.rstrip('/') + '/api/ingest',packet,headers,timeout=5)
                print(packet['recorded_at'], 'T=',packet['temperature_c'],
                      'soil=',packet['soil_moisture_pct'],'stored=',response.get('stored'))
                sent += 1
            except Exception as e:
                print('Receiver connection failed; retry on next interval:',e)
            time.sleep(max(0.2,args.interval))
    except KeyboardInterrupt:
        print('\nStopped')

if __name__=='__main__':
    main()
