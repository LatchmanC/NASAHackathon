/* Verify demo public-provider UX and labels are wired through the frontend. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const staticDir=path.resolve(__dirname,'../public/static');
const app=fs.readFileSync(path.join(staticDir,'app.js'),'utf8');
const soil=fs.readFileSync(path.join(staticDir,'soil-rotation.js'),'utf8');
const home=fs.readFileSync(path.join(staticDir,'home.js'),'utf8');
const html=fs.readFileSync(path.resolve(__dirname,'../public/dashboard.html'),'utf8');
test('Demo automatic NASA data uses REAL public regional records, not synthetic fixtures',()=>{
  assert.match(app,/return api\('\/api\/nasa\?mode=real&days=90'/);
  assert.match(app,/previous\?\.is_real_nasa/);
  assert.match(app,/await persist\('nasa',state\.nasa\)/);
  assert.match(app,/REAL NASA POWER/);
});
test('Demo real weather uses same Open-Meteo endpoint as authenticated users',()=>{
  assert.match(app,/api\('\/api\/weather\?mode=live'/);
  assert.match(home,/farmCloudMode==='sample'\|\|/);
});
test('Demo soil UI displays real public map and source attributions',()=>{
  assert.match(soil,/LIVE USDA soil map for example Demo location/);
  assert.match(soil,/REAL USDA map unit at the example demo coordinates/);
  assert.match(soil,/PUBLIC APIs · DEMO LOCATION/);
  assert.doesNotMatch(soil,/Live USDA and OpenStreetMap maps are not loaded/);
});
test('Demo labelling still distinguishes simulated farm/sensors from public sources',()=>{
  assert.match(html,/Example farm, ESP32 sensors, sensor history and calendar tasks are simulated/);
  assert.match(html,/NASA POWER, Open-Meteo, NWS/);
  assert.match(app,/Demo mode, key not available/);
  assert.match(app,/farmCloudMode==='sample'\?'✦ Ask demo Fieldy'/);
});
