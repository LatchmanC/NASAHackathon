"""One command: simulate ESP32 -> local cloud SQL -> simplified web app.

Use `python run_demo.py --no-browser` for server/testing. No Pi required.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

HERE=Path(__file__).resolve().parent

def wait_http(url,limit=10):
    end=time.monotonic()+limit
    while time.monotonic()<end:
        try:
            with urlopen(url,timeout=1) as resp:
                if resp.status==200:return True
        except Exception:pass
        time.sleep(.2)
    return False

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--no-browser',action='store_true')
    args=p.parse_args()
    env={**os.environ,'FIELDSHIFT_ALERTS_ENABLED':'0','FIELDSHIFT_DEMO':'1','PYTHONUNBUFFERED':'1'}
    # Populate demonstrative history and NASA-like data. All are labeled SYNTHETIC.
    from fieldshift_core import StationDB
    from intelligence import seed_demo_history, demo_nasa_daily
    db=StationDB()
    db.set_setting('cloud_url','http://127.0.0.1:8766')
    if not db.get_setting('nasa_daily'):
        db.set_setting('nasa_daily',demo_nasa_daily(db.get_setting('location')))
    count=seed_demo_history(db)
    print(f'Seeded {count} new simulated historical readings.',flush=True)
    scripts=[('Cloud SQL simulator','cloud_mock.py'),
             ('ESP32 test receiver','esp32_receiver_sim.py'),
             ('ESP32 sensor simulator','esp32_simulator.py'),('FieldShift web dashboard','web_server.py')]
    procs=[]
    try:
        for title,script in scripts:
            child=subprocess.Popen([sys.executable,str(HERE/script)],cwd=HERE,env=env)
            procs.append((title,child))
            print(f'Started {title} (PID {child.pid})',flush=True)
            time.sleep(.45)
        if wait_http('http://127.0.0.1:8501/api/health',12):
            print('\nFIELD SHIFT READY: http://127.0.0.1:8501',flush=True)
            if not args.no_browser:webbrowser.open('http://127.0.0.1:8501')
        else:
            print('Web app did not respond. Check terminal errors.',flush=True)
        print('Press Ctrl+C to exit the demo.',flush=True)
        while True:
            failed=[(name,proc.returncode) for name,proc in procs if proc.poll() is not None]
            if failed:
                print('Component exited:',failed,flush=True)
                break
            time.sleep(.4)
    except KeyboardInterrupt:
        print('\nStopping demo...',flush=True)
    finally:
        for _,proc in reversed(procs):
            if proc.poll() is None:proc.terminate()
        for _,proc in reversed(procs):
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill()
        print('Stopped.',flush=True)

if __name__=='__main__':main()
