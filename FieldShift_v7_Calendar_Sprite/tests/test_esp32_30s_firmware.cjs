'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const fw=fs.readFileSync(path.join(root,'CropagandaESP32/CropagandaESP32.ino'),'utf8');
const template=fs.readFileSync(path.join(root,'CropagandaESP32/device_config.example.h'),'utf8');
const ignored=fs.readFileSync(path.join(root,'CropagandaESP32/.gitignore'),'utf8');
const api=fs.readFileSync(path.join(root,'FieldShift_v7_Calendar_Sprite/device_api.py'),'utf8');
const database=fs.readFileSync(path.join(root,'FieldShift_v7_Calendar_Sprite/tigerdata_store.py'),'utf8');

test('ESP32 sends at a thirty-second cadence, never five minutes or five seconds',()=>{
  assert.match(fw,/UPLOAD_INTERVAL_MS\s*=\s*30000UL/);
  assert.match(fw,/nextUploadAt\s*=\s*normalDue/);
  assert.match(fw,/Retry-After/);
  assert.match(fw,/HTTP_CODE|status\s*==\s*429/);
});

test('firmware posts to the authenticated Cropaganda endpoint with valid fields',()=>{
  assert.match(fw,/https:\/\/cropaganda\.garden\/api\/device\/ingest/);
  assert.match(fw,/\"Authorization\", String\(\"Bearer \"\) \+ CROPOGANDA_DEVICE_TOKEN/);
  assert.match(fw,/\\\"device_id\\\"/);
  for(const metric of ['temperature_c','pressure_hpa','altitude_m','rain_wetness_pct'])
    assert.ok(fw.includes(metric),'Missing metric '+metric);
});

test('no private device token or Wi-Fi credentials are committed',()=>{
  assert.match(ignored,/^device_config\.h$/m);
  assert.match(fw,/#include \"device_config\.h\"/);
  assert.match(template,/YOUR_WIFI_SSID/);
  assert.match(template,/YOUR_LONG_PRIVATE_PAIRING_TOKEN/);
  assert.match(fw,/tls\.setCACert\(CROPOGANDA_ROOT_CA_PEM\)/);
  assert.doesNotMatch(fw,/\n\s*tls\.setInsecure\(/);
});

test('server permits 30s ingestion with TigerData and archives 10-minute buckets unchanged',()=>{
  assert.match(api,/if tiger_enabled\(\):[\s\S]{0,150}CROPOGANDA_MIN_SENSOR_SECONDS','2'/);
  assert.match(api,/if age is not None and age<interval:/);
  assert.match(database,/bucket=datetime\.fromtimestamp\(int\(recorded\.timestamp\(\)\)\/\/600\*600/);
  assert.match(database,/ON CONFLICT DO NOTHING/);
});
