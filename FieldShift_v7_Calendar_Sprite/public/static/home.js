/* Cropaganda overview and navigation. Preserve existing app.js APIs and browser storage.
   No simulated weather, sensor, or market values are displayed here. */
'use strict';

const CROP_REFERENCE=[
 {match:['corn','maize'],name:'Field Corn',icon:'🌽',role:'Cash grain',water:'High water demand',tip:'Pay particular attention to irrigation during pollination.',watch:'Consider winter ground cover after harvest.'},
 {match:['soybean','soya'],name:'Soybeans',icon:'🫛',role:'Rotation legume',water:'Moderate water demand',tip:'Can help diversify a cereal-heavy rotation.',watch:'Monitor disease pressure and consider winter ground cover.'},
 {match:['wheat'],name:'Winter Wheat',icon:'🌾',role:'Overwinter grain',water:'Low–moderate water demand',tip:'Living winter cover can help protect exposed soil.',watch:'Check local winter-hardy varieties and sowing windows.'},
 {match:['sorghum','milo'],name:'Grain Sorghum',icon:'🌾',role:'Drought-tolerant grain',water:'Lower seasonal water demand',tip:'An option worth evaluating in warmer, water-limited rotations.',watch:'Check local markets and scout for aphids.'},
 {match:['chickpea','garbanzo'],name:'Chickpeas',icon:'🫘',role:'Pulse crop',water:'Lower water demand',tip:'Legume rotation option for suitable well-drained fields.',watch:'Avoid waterlogged soils; scout for fungal diseases.'},
 {match:['alfalfa'],name:'Alfalfa',icon:'☘️',role:'Perennial forage',water:'Moderate–high water demand',tip:'Perennial ground cover can help hold soil in place.',watch:'Establishment and forage markets matter.'},
 {match:['crimson clover','clover','radish'],name:'Crimson Clover + Radish',icon:'🌺',role:'Cover crop mix',water:'Cool-season growth',tip:'Can provide living cover between cash crops.',watch:'Plan termination timing and check herbicide carryover.'},
 {match:['cereal rye','winter rye','rye'],name:'Cereal Rye',icon:'🌱',role:'Winter cover crop',water:'Cool-season growth',tip:'Can limit bare ground exposure over winter.',watch:'Terminate early enough before a dry spring planting.'}
];
function cropReference(name){
 const clean=String(name||'').toLowerCase();
 return CROP_REFERENCE.find(c=>c.match.some(part=>clean.includes(part)))||null;
}
function dashboardLocation(){
 const selected=saved('location');
 return selected&&Number.isFinite(Number(selected.latitude))&&Number.isFinite(Number(selected.longitude))&&!/^(Demo|Test Farm)\b/i.test(selected.label||'')
    ?selected:null;
}
function displayDay(dateValue){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(dateValue||''))return 'Date not set';
 const p=dateValue.split('-').map(Number);
 return new Date(p[0],p[1]-1,p[2]).toLocaleDateString(undefined,{month:'short',day:'numeric'});
}
function homeEmpty(target,message,tabName,label){
 const box=$(target);
 if(!box)return;
 box.innerHTML='<div class="home-empty"><p>'+html(message)+'</p><button type="button" class="home-text-link" data-go="'+html(tabName)+'">'+html(label)+'</button></div>';
}
function renderHomeCrops(){
 const p=saved('plan');
 const crops=(Array.isArray(p?.crops)?p.crops:[]).filter(c=>c&&String(c.name||'').trim());
 const count=$('#home-crop-count');
 if(count)count.textContent=crops.length?crops.length+' saved crops':'Not yet configured';
 if(!crops.length){homeEmpty('#home-crops','Your saved crops will appear here. Add your first crop in My Farm.','crops','Set up my farm');return;}
 const shown=[...crops].sort((a,b)=>(Number(b.area)||0)-(Number(a.area)||0)).slice(0,4);
 $('#home-crops').innerHTML=shown.map(c=>{
   const ref=cropReference(c.name);
   const icon=ref?.icon||'🌱';
   const area=Number(c.area);
   const land=Number.isFinite(area)&&area>0?area.toLocaleString(undefined,{maximumFractionDigits:2})+' '+(p.area_unit||'acres'):'Area not entered';
   const stage=String(c.stage||'Not specified');
   const variety=c.variety?' · '+String(c.variety):'';
   return '<button class="home-crop-item" type="button" data-go="crops">'+
     '<span class="home-crop-emoji" aria-hidden="true">'+icon+'</span><span class="home-crop-copy">'+
     '<strong>'+html(c.name)+'</strong><small>'+html(stage+variety)+'</small>'+
     (c.planted_on?'<small>Planted '+html(displayDay(c.planted_on))+'</small>':'')+
     '</span><span class="home-crop-area">'+html(land)+'<span aria-hidden="true"> ›</span></span></button>';
 }).join('');
 if(crops.length>4)$('#home-crops').insertAdjacentHTML('beforeend','<p class="home-more">+'+(crops.length-4)+' more crops in My Farm</p>');
}
function renderHomeTasks(){
 const tasks=saved('calendar',[]);
 const crops=saved('plan')?.crops||[];
 const derived=Array.isArray(crops)?crops.filter(c=>/^\d{4}-\d{2}-\d{2}$/.test(c.planted_on||'')).map(c=>({date:c.planted_on,kind:'planting',crop:c.name,note:'Planting date from crop list'})):[];
 const actual=Array.isArray(tasks)?tasks:[];
 const upcoming=[...actual,...derived].filter(e=>/^\d{4}-\d{2}-\d{2}$/.test(e.date||'')&&e.date>=todayISO()).sort((a,b)=>a.date.localeCompare(b.date));
 const count=$('#home-task-count');
 if(count)count.textContent=upcoming.length+' upcoming';
 if(!upcoming.length){homeEmpty('#home-tasks','No upcoming farm tasks in your saved calendar.','calendar','Open calendar');return;}
 $('#home-tasks').innerHTML=upcoming.slice(0,3).map(e=>
  '<button class="home-task-item" type="button" data-go="calendar"><span class="home-task-date">'+html(displayDay(e.date))+'</span>'+
  '<span><strong>'+html((calendarKinds[e.kind]||'Farm task')+(e.crop?' · '+e.crop:''))+'</strong><small>'+html(e.note||'')+'</small></span><span aria-hidden="true">›</span></button>'
 ).join('');
}
function renderHomeSensor(o){
 const label=$('#home-sensor-status'),detail=$('#home-sensor-detail'),value=$('#home-sensor-value');
 if(!label||!detail||!value)return;
 const real=o&&o.state==='live'&&o.sensor_source!=='SYNTHETIC_SAMPLE';
 label.className='home-status-label'+(real?' good':'');
 if(!o){label.textContent='Checking device';detail.textContent='Waiting for the field station status.';value.textContent='—';return;}
 if(o.sensor_source==='SYNTHETIC_SAMPLE'){
   label.textContent='Demonstration only';detail.textContent='Synthetic sample—not real ESP32 measurements.';value.textContent='—';return;
 }
 if(real){
   label.textContent='● Device online';
   const temp=o.latest?.temperature_c;
   value.textContent=temp!==null&&temp!==undefined&&Number.isFinite(+temp)?fixed(temp,1)+'°C':'Live';
   detail.textContent='Real ESP32 upload · '+(o.last_reading_at?easternTime(o.last_reading_at):'just updated');
 }else{
   label.textContent=o.state==='stale'?'◷ Sensor delayed':'○ ESP32 offline';
   value.textContent='—';
   detail.textContent=o.last_reading_at?'Last actual reading '+easternTime(o.last_reading_at):'No real sensor upload received yet.';
 }
 renderHomeAlert();
}
let latestHomeWeather=null;
let latestHomeWeatherAt=0;
let homeWeatherLocation='';
let homeWeatherPending=false;
function renderHomeWeather(data){
 const current=data?.current,days=data?.forecast||[];
 const temperature=$('#home-weather-temperature');
 if(current&&Number.isFinite(+current.temperature_c)){
   temperature.textContent=fixed(current.temperature_c,0)+'°C';
   $('#home-weather-condition').textContent=current.summary||'Current conditions';
   const more=[];
   if(current.feels_like_c!==null&&current.feels_like_c!==undefined)more.push('Feels like '+fixed(current.feels_like_c,0)+'°C');
   if(current.humidity_pct!==null&&current.humidity_pct!==undefined)more.push('Humidity '+fixed(current.humidity_pct,0)+'%');
   if(current.wind_kmh!==null&&current.wind_kmh!==undefined)more.push('Wind '+fixed(current.wind_kmh,0)+' km/h');
   $('#home-weather-meta').textContent=more.join(' · ')||'Open-Meteo current conditions';
 }else{
   temperature.textContent='—';
   $('#home-weather-condition').textContent='Current weather unavailable';
   $('#home-weather-meta').textContent='No current observation returned.';
 }
 const forecastDays=days.slice(0,3);
 $('#home-weather-days').innerHTML=forecastDays.length?forecastDays.map((d,i)=>{
   const day=i===0?'Today':i===1?'Tomorrow':displayDay(d.date);
   return '<button type="button" class="home-weather-day" data-go="nasa"><span>'+html(day)+'</span>'+
    '<strong>'+html(d.summary||'Forecast')+'</strong><span>'+fixed(d.high_c,0)+'° / '+fixed(d.low_c,0)+'°</span>'+
    '<small>☂ '+fixed(d.rain_chance_pct,0)+'%</small></button>';
 }).join(''):'<p class="home-muted">Forecast unavailable for this location.</p>';
 $('#home-weather-source').textContent=data?.forecast_source||'Weather unavailable · Open-Meteo';
}
function renderHomeAlert(){
 const root=$('#home-alert-link');if(!root)return;
 const a=latestHomeWeather?.alert_status||{};
 const alerts=Array.isArray(a.alerts)?a.alerts:[];
 const realSensorFlags=state.overview?.state==='live'&&state.overview?.sensor_source!=='SYNTHETIC_SAMPLE'?
   (state.overview.flags||[]):[];
 root.classList.remove('home-alert-danger','home-alert-watch','home-alert-clear','home-alert-unknown');
 let level='unknown',title='Checking official weather alerts',description='Fetching the latest information for your saved farm location.',link='Weather & NASA',go='nasa';
 if(a.status==='live'&&alerts.length){
   const severity={Extreme:0,Severe:1,Moderate:2,Minor:3,Unknown:4};
   const ordered=[...alerts].sort((a,b)=>(severity[a.severity]??4)-(severity[b.severity]??4));
   const first=ordered[0];
   level='danger';title=first.event||'Official weather alert';
   description=(first.headline||first.description||'An active weather alert was returned.').slice(0,210);
   if(alerts.length>1)description+=' · '+(alerts.length-1)+' additional alert(s)';
   link='View official warnings';
 }else if(realSensorFlags.length){
   const f=realSensorFlags[0];
   level='watch';title=f.event||'Field sensor condition';
   description=(f.description||'A measured sensor condition needs review.')+' · Local sensor flag, not an official weather warning.';
   link='Inspect live sensors';go='live';
 }else if(a.status==='live'){
   level='clear';title='No active NWS alerts returned';
   description='Last successful official check for this farm point. Weather conditions can change; review the full forecast.';
   link='See weather details';
 }else if(a.status==='demo'){
   level='unknown';title='Demonstration account';
   description='Reference alerts are simulated; no official warning status is implied.';
 }else if(a.status==='unavailable'){
   level='unknown';title='Official alerts could not be verified';
   description='An unavailable check does not mean the weather is safe. Consult your local weather authority.';
 }else if(!dashboardLocation()){
   level='unknown';title='Choose your farm location';
   description='Select a real farm location to load current conditions and check available official alerts.';
   go='crops';link='Set farm location';
 }
 root.classList.add('home-alert-'+level);
 $('#home-alert-eyebrow').textContent=level==='danger'?'OFFICIAL WEATHER ALERT':level==='watch'?'FIELD SENSOR NOTICE':level==='clear'?'LATEST WEATHER CHECK':'ALERT STATUS';
 $('#home-alert-title').textContent=title;
 $('#home-alert-detail').textContent=description;
 $('#home-alert-cta').textContent=link+'  ›';
 root.dataset.go=go;
}
function renderHome(){
 const loc=dashboardLocation();
 $('#home-location-summary').textContent=loc?'Farm location · '+(loc.label||'Selected coordinates'):'Set your location in My Farm to personalize conditions';
 $('#home-date').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'});
 renderHomeCrops();
 renderHomeTasks();
 renderHomeSensor(state.overview);
 renderHomeAlert();
}
async function loadHomeWeather(force=false){
 if(homeWeatherPending)return;
 const loc=dashboardLocation();
 const account=$('#account-box').textContent||'';
 if(!account.includes('Signed in:'))return;
 if(!loc){
   latestHomeWeather=null;latestHomeWeatherAt=0;homeWeatherLocation='';
   renderHomeWeather(null);renderHomeAlert();return;
 }
 const key=loc.latitude+','+loc.longitude;
 if(!force&&latestHomeWeather&&homeWeatherLocation===key&&Date.now()-latestHomeWeatherAt<900000)return;
 homeWeatherPending=true;
 $('#home-weather-source').textContent='Checking Open-Meteo and official warnings…';
 try{
   const data=await api('/api/weather?mode=live',{timeout:33000});
   // Location can change during a request: don't display an old location's weather.
   const current=dashboardLocation();
   if(!current||key!==current.latitude+','+current.longitude)return;
   latestHomeWeather=data;latestHomeWeatherAt=Date.now();homeWeatherLocation=key;
   renderHomeWeather(data);renderHomeAlert();
 }catch(e){
   latestHomeWeather={alert_status:{status:'unavailable'},forecast:[],current:null};
   latestHomeWeatherAt=0;homeWeatherLocation=key;
   renderHomeWeather(null);
   $('#home-weather-source').textContent='Weather service unavailable. Open Weather & NASA for details.';
   renderHomeAlert();
 }finally{homeWeatherPending=false;}
}
function mountCropReferenceGuide(){
 const target=$('#tab-crops .planner-layout');
 if(!target||$('#crop-reference-guide'))return;
 const section=document.createElement('section');section.className='card section-gap';section.id='crop-reference-guide';
 section.innerHTML='<details><summary class="home-guide-summary">🌾 Crop & rotation reference guide <span class="home-guide-count">8 examples</span></summary>'+
   '<p class="home-guide-disclaimer">Adapted from the provided planning prototype. These are general crop characteristics—not live NASA/USDA measurements, current market prices, or a substitute for local agronomy advice.</p>'+
   '<div class="home-reference-grid">'+CROP_REFERENCE.map(c=>
   '<article class="home-reference-card"><div class="home-reference-title"><span>'+c.icon+'</span><strong>'+html(c.name)+'</strong></div>'+
   '<small>'+html(c.role)+' · '+html(c.water)+'</small><p>'+html(c.tip)+'</p><p class="home-reference-caution"><b>Watch:</b> '+html(c.watch)+'</p></article>').join('')+'</div></details>';
 target.insertAdjacentElement('afterend',section);
}
function organizePanels(){
 const fieldy=$('#tab-fieldy'),calendar=$('#tab-calendar');
 const advisor=$('#tab-crops .advisor-panel');
 if(fieldy&&advisor)fieldy.appendChild(advisor);
 const farmCalendar=$('#tab-crops .crop-calendar');
 if(calendar&&farmCalendar)calendar.appendChild(farmCalendar);
 const sms=$('#sms-panel');
 if(calendar&&sms)calendar.appendChild(sms);
 const banner=$('.preview-banner');
 if(banner)$('#tab-crops').appendChild(banner);
 // The detailed crop reference now lives in Soil & Rotation.
}
organizePanels();
const previousTab=tab;
tab=function(name){
 if(!$('#tab-'+name))name='home';
 previousTab(name);
 if(name==='home'){
   renderHome();
   loadHomeWeather();
   if(!state.overview||Date.now()-lastLivePoll>12000)loadLive();
 }
};
const previousUpdateLive=updateLive;
updateLive=function(o){
 previousUpdateLive(o);
 renderHomeSensor(o);
};
const previousPersist=persist;
persist=function(k,v){
 previousPersist(k,v);
 if(k==='plan'||k==='calendar'||k==='location'){
   renderHome();
   if(k==='location')loadHomeWeather(true);
 }
};
document.addEventListener('keydown',event=>{
 const item=event.target.closest('[data-go][role="link"]');
 if(item&&(event.key==='Enter'||event.key===' ')){event.preventDefault();item.click();}
});
document.addEventListener('click',event=>{
 const trigger=event.target.closest('[data-go]');
 if(!trigger)return;
 const name=trigger.dataset.go;
 if(!$('#tab-'+name))return;
 tab(name);
 if(location.hash!=='#'+name)history.replaceState(null,'',location.pathname+'#'+name);
 if(name==='fieldy')$('#farm-question').focus();
});
$$('.navitem').forEach(button=>button.addEventListener('click',()=>{
 const name=button.dataset.tab;
 if($('#tab-'+name))history.replaceState(null,'',location.pathname+'#'+name);
}));
window.addEventListener('hashchange',()=>{
 const name=location.hash.slice(1);
 if($('#tab-'+name))tab(name);
});
const authObserver=new MutationObserver(()=>{
 if($('#account-box').textContent.includes('Signed in:')){
   renderHome();loadHomeWeather();
 }
});
authObserver.observe($('#account-box'),{childList:true,subtree:true});
const initialHash=location.hash.slice(1);
tab($('#tab-'+initialHash)?initialHash:'home');
setInterval(()=>{
 if(state.tab!=='home'||document.visibilityState!=='visible')return;
 renderHome();
 loadHomeWeather();
 if(Date.now()-lastLivePoll>(state.tigerLive?12000:30000))loadLive();
},15000);
