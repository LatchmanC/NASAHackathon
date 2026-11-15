/* Cropaganda 3-tab browser interface. No external JS dependencies. */
'use strict';
const $=s=>document.querySelector(s);
const $$=s=>Array.from(document.querySelectorAll(s));
const state={tab:'crops',overview:null,plan:null,history:[],nasa:null,localDays:{},toastTimer:null,locations:null,tigerLive:false};
const units={temperature_c:'°C',humidity_pct:'%',pressure_hpa:'hPa',altitude_m:'m',ph:'pH',rain_wetness_pct:'%',light_pct:'%',gas_index:'/100',soil_moisture_pct:'%'};
const metricInfo=[['temperature_c','Air temperature','☀'],['humidity_pct','Humidity','◉'],['pressure_hpa','Air pressure','⛅'],['soil_moisture_pct','Soil moisture index','◈'],['rain_wetness_pct','Rain plate wetness','☂'],['light_pct','Light sensor index','☼'],['altitude_m','Estimated altitude','△']];
// Live and History show only supported sensor metrics; raw stored data is unchanged.
const liveMetricInfo=metricInfo;
const easternTime=t=>{if(!t)return 'Never';const d=new Date(t);return Number.isNaN(d.getTime())?String(t):d.toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'});};
const nasaInfo={temperature_c:['Mean temperature','°C'],temperature_max_c:['Max temperature','°C'],temperature_min_c:['Min temperature','°C'],humidity_pct:['Relative humidity','%'],pressure_hpa:['Surface pressure','hPa'],precipitation_mm:['Daily precipitation','mm/day'],solar_mj_m2_day:['Solar radiation','MJ/m²/day'],wind_2m_ms:['Wind at 2 m','m/s'],wind_10m_ms:['Wind at 10 m','m/s'],dew_point_c:['Dew point','°C'],soil_wetness_fraction:['Modeled topsoil wetness','fraction']};
const comparable={temperature_c:'temperature_c',humidity_pct:'humidity_pct',pressure_hpa:'pressure_hpa'};
function html(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fixed(v,n=1){return v===null||v===undefined||v===''||!Number.isFinite(+v)?'—':Number(v).toFixed(n);}
function localTime(t){if(!t)return 'Never';const d=new Date(t);return Number.isNaN(d.getTime())?String(t):d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
function showToast(text,isError=false){const t=$('#toast');t.textContent=text;t.classList.remove('hidden');t.classList.toggle('error',isError);clearTimeout(state.toastTimer);state.toastTimer=setTimeout(()=>t.classList.add('hidden'),6000);}
// Verified Auth0 farm documents are loaded from TigerData, with old localStorage
// kept only as an opt-in migration source/backup. Sample accounts remain local.
// This account-aware prefix is for legacy records, not an authorization boundary.
let fsAccount='preview';
const fsKey=k=>'fieldshift_v9_'+fsAccount+'_'+k;
const farmKeys=['plan','location','calendar','rotation_scenarios'];
let farmCloudMode='loading';
let farmCloudSections={};
function legacyValue(k,fallback=null){
  try{const raw=localStorage.getItem(fsKey(k));return raw===null?fallback:JSON.parse(raw);}
  catch{return fallback;}
}
function saved(k,fallback=null){
  if(farmKeys.includes(k)){
    if(farmCloudMode==='ready'){
      const section=farmCloudSections[k];
      return section?.present?section.value:fallback;
    }
    if(farmCloudMode==='error')return fallback;
  }
  return legacyValue(k,fallback);
}
async function persist(k,v){
  if(farmKeys.includes(k)){
    if(farmCloudMode==='ready'){
      const previous=farmCloudSections[k]||{revision:0};
      const result=await api('/api/farm/state/'+encodeURIComponent(k),{
        method:'PUT',body:{value:v,expected_revision:previous.revision||0},timeout:22000
      });
      farmCloudSections[k]={value:result.value,revision:result.revision,present:true};
      return result;
    }
    if(farmCloudMode!=='sample')throw Error('TigerData is unavailable. Farm changes were NOT saved; refresh and retry.');
  }
  try{localStorage.setItem(fsKey(k),JSON.stringify(v));return {saved:true,storage:'browser'};}
  catch(e){throw Error('Browser storage unavailable; changes were not saved.');}
}
function cloudNotice(message,isError=false){
  const el=$('#farm-cloud-status');
  if(!el)return;
  el.textContent=message;
  el.classList.toggle('warn',isError);
}
function browserImportCandidates(){
  const choices={};
  for(const key of farmKeys){
    const value=legacyValue(key);
    if(value===null||value===undefined)continue;
    if((key==='calendar'||key==='rotation_scenarios')&&(!Array.isArray(value)||!value.length))continue;
    if(key==='location'&&/^(Demo|Test Farm)\b/i.test(value.label||''))continue;
    choices[key]=value;
  }
  return choices;
}
function showFarmImportOffer(){
  const banner=$('#farm-import-banner');
  if(!banner||farmCloudMode!=='ready')return;
  const entries=browserImportCandidates();
  const acknowledged=legacyValue('farm_cloud_import_ack');
  const candidateKeys=Object.keys(entries);
  banner.classList.toggle('hidden',candidateKeys.length===0||acknowledged===true);
  $('#farm-import-reopen').classList.toggle('hidden',candidateKeys.length===0);
  $('#farm-import-summary').textContent=candidateKeys.length?
    'This browser has older '+candidateKeys.map(x=>x.replaceAll('_',' ')).join(', ')+' data. Import it into your account without replacing existing cloud farm plans or locations.':
    'No earlier browser data was found.';
}
async function loadFarmCloud(){
  try{
    const result=await api('/api/farm/state',{timeout:22000});
    farmCloudSections=result.sections||{};
    farmCloudMode='ready';
    cloudNotice('● TigerData connected · Your farm data syncs across signed-in devices.');
    showFarmImportOffer();
    const loc=saved('location');
    if(loc){
      $('#location-label').textContent=loc.label;
      $('#location-current').textContent=loc.label;
    }
  }catch(e){
    farmCloudMode='error';
    cloudNotice('⚠ TigerData farm data unavailable: '+e.message+'. Existing browser records are preserved, but changes cannot be saved.',true);
    showToast('Farm cloud storage is unavailable. No farm changes will be saved until it reconnects.',true);
  }
}
async function importBrowserFarmData(){
  const btn=$('#farm-import-button');
  const sections=browserImportCandidates();
  if(!Object.keys(sections).length)return;
  btn.disabled=true;
  try{
    const result=await api('/api/farm/import',{method:'POST',body:{sections},timeout:30000});
    farmCloudSections=result.sections;
    localStorage.setItem(fsKey('farm_cloud_import_ack'),JSON.stringify(true));
    $('#farm-import-banner').classList.add('hidden');
    const actions=Object.entries(result.results||{}).map(([key,value])=>key+': '+value.action);
    cloudNotice('● TigerData import complete · '+actions.join(' · ')+'. Browser originals retained.');
    await Promise.allSettled([loadPlan(),loadCalendar(),initLocations()]);
    if(typeof soilLoad==='function')soilLoad(true);
    showToast('Browser farm data imported safely into TigerData.');
  }catch(e){showToast('Import failed; browser data is unchanged: '+e.message,true);}
  finally{btn.disabled=false;}
}
function currentLocation(){return saved('location',{mode:'coords',label:'Demo — New York City',latitude:40.7128,longitude:-74.006});}
async function api(path,opts={}){
  const method=opts.method||'GET';
  if(path==='/api/plan'&&method==='GET'){
    const plan=saved('plan');if(plan)return plan;
  }
  if(path==='/api/calendar'&&farmCloudMode==='ready'){
    if(method==='GET')return {events:saved('calendar',[]),storage:'TigerData'};
    if(method==='POST'){
      const result=await api('/api/farm/calendar',{method:'POST',body:opts.body||{},timeout:22000});
      farmCloudSections.calendar={value:result.events,revision:result.revision,present:true};
      smsSync();
      return result;
    }
  }
  if(path==='/api/calendar'&&farmCloudMode!=='sample')
    throw Error('TigerData calendar unavailable. Task was not saved.');
  if(path==='/api/calendar'){
    const events=saved('calendar',[]);
    if(method==='GET')return {events,storage:'browser only'};
    if(method==='POST'){
      const ev=opts.body||{};
      if(!/^\d{4}-\d{2}-\d{2}$/.test(ev.date)||!['planting','watering','harvest','fertilizing','inspection','other'].includes(ev.kind)||events.length>=500)throw Error('Enter a valid date and task type (maximum 500 tasks).');
      const entry={id:ev.id||crypto.randomUUID(),date:ev.date,kind:ev.kind,crop:String(ev.crop||'').slice(0,70),note:String(ev.note||'').slice(0,240),
        google_event_id:ev.google_event_id||null};
      if(events.some(x=>x.id===entry.id))return {saved:true,events,already_saved:true};
      const next=[...events,entry].sort((a,b)=>a.date.localeCompare(b.date));persist('calendar',next);smsSync();return {saved:true,events:next};
    }
  }
  if(path.startsWith('/api/calendar/')&&method==='DELETE'&&farmCloudMode==='ready'){
    const id=decodeURIComponent(path.split('/').pop());
    const result=await api('/api/farm/calendar/'+encodeURIComponent(id),{method:'DELETE',timeout:22000});
    farmCloudSections.calendar={value:result.events,revision:result.revision,present:true};
    smsSync();
    return result;
  }
  if(path.startsWith('/api/calendar/')&&method==='DELETE'&&farmCloudMode!=='sample')
    throw Error('TigerData calendar unavailable. Task was not deleted.');
  if(path.startsWith('/api/calendar/')&&method==='DELETE'){
    const id=decodeURIComponent(path.split('/').pop());const list=saved('calendar',[]),next=list.filter(x=>x.id!==id);
    if(next.length===list.length)throw Error('Task not found');
    persist('calendar',next);smsSync();return {deleted:true,events:next};
  }
  if(path==='/api/nasa?mode=auto&days=90'&&farmCloudMode==='sample'){
    const previous=saved('nasa');
    const location=currentLocation();
    const fresh=previous?.is_real_nasa&&previous.latitude===location.latitude&&
      previous.longitude===location.longitude&&
      (Date.now()-Date.parse(previous.fetched_at||''))<6*3600*1000;
    if(fresh)return {nasa_daily:previous,note:'REAL NASA POWER · saved in this browser (demo read-only)'};
    return api('/api/nasa?mode=real&days=90',{timeout:65000});
  }
  if(path==='/api/nasa?mode=auto&days=90'){
    const c=saved('nasa');const loc=currentLocation();
    if(c&&c.latitude===loc.latitude&&c.longitude===loc.longitude)return {nasa_daily:c,note:'Saved in this browser'};
    return {nasa_daily:null,note:'Download the NASA POWER history for your farm location'};
  }
  if((path==='/api/overview'||path.startsWith('/api/recorded')||path==='/api/charts')&&method==='GET'){
    path+=(path.includes('?')?'&':'?')+'view='+encodeURIComponent(saved('sensor_view','auto'));
  }
  if(path.startsWith('/api/nasa?')||path.startsWith('/api/weather?')){
    const l=currentLocation();const sep=path.includes('?')?'&':'?';
    path+=sep+'latitude='+encodeURIComponent(l.latitude)+'&longitude='+encodeURIComponent(l.longitude);
  }
  if(path==='/api/plan/advice'&&method==='POST'){
    opts.body={...opts.body,location:currentLocation(),nasa_excerpt:state.nasa?.is_real_nasa?(state.nasa.rows||[]).slice(-12):[],
      upcoming_calendar_tasks:saved('calendar',[]).filter(x=>x.date>=todayISO()).slice(0,15),
      sensor_view:saved('sensor_view','auto'),client_today:todayISO()};
  }
  const ctl=new AbortController();const timer=setTimeout(()=>ctl.abort(),opts.timeout||20000);
  try{
    const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-FieldShift-Request':'1'},body:opts.body===undefined?undefined:JSON.stringify(opts.body),signal:ctl.signal,cache:'no-store'});
    const j=await r.json();if(!r.ok)throw Error(j.detail||j.error||`HTTP ${r.status}`);
    if(path==='/api/plan'&&method==='POST'&&j.plan)await persist('plan',j.plan);
    if(path==='/api/location'&&method==='POST'&&j.location){await persist('location',j.location);localStorage.removeItem(fsKey('nasa'));smsSync();}
    if(path.startsWith('/api/nasa?mode=real')&&j.nasa_daily?.is_real_nasa)persist('nasa',j.nasa_daily);
    if(path.startsWith('/api/overview'))j.location=currentLocation();
    return j;
  }catch(e){if(e.name==='AbortError')throw Error('Request timed out; check internet/API status.');throw e;}
  finally{clearTimeout(timer);}
}

function tab(name){state.tab=name;$$('.navitem').forEach(n=>n.classList.toggle('active',n.dataset.tab===name));$$('.panel-tab').forEach(n=>n.classList.toggle('hidden',n.id!==`tab-${name}`));$('.sidebar').classList.remove('open');if(name==='live')loadLive();if(name==='nasa')loadNASA();if(name==='history')initArchive();if(name==='crops'&&!state.plan)loadPlan();}
let loadingLive=false;
let lastLivePoll=0;
async function loadLive(){
  if(loadingLive)return;
  loadingLive=true;lastLivePoll=Date.now();
  try{const o=await api('/api/overview',{timeout:12000});state.overview=o;updateLive(o);}
  catch(e){$('#sensor-state').textContent='Sensor station unavailable';$('#sync-message').textContent=e.message;showToast(e.message,true);}
  finally{loadingLive=false;}
}
function updateLive(o){const stateEl=$('#sensor-state');stateEl.className='state-chip'+(o.state==='live'?'':o.state==='offline'?' off':' warn');const names={live:'●  Live',demo:'◉  SYNTHETIC SAMPLE',stale:'◷  Sensor delayed',cloud_only:'◷  Last cloud record',offline:'○  Offline'};stateEl.textContent=names[o.state]||'Checking…';
  $('#location-label').textContent=o.location?.label||'Location not selected';$('#location-current').textContent=o.location?.label||'Location not selected';$('#side-status').textContent=o.state==='demo'?'Synthetic example only':o.state==='live'?'Receiving ESP32 data':o.pi_connected?'Station online · sensor stale':o.cloud_connected?'Station offline · cloud available':'Station offline';$('.statusdot').classList.toggle('online',o.state==='live');
  let message=o.last_reading_at?`Last sensor reading: ${localTime(o.last_reading_at)}`:'No recorded reading yet';message+=o.sensor_source==='SYNTHETIC_SAMPLE'?' · SYNTHETIC SAMPLE / NO ESP32 CONNECTED':'';message+=o.sensor_access_mode==='shared'?' · Shared device (read-only)':'';message+=o.last_cloud_sync?` · Last cloud sync: ${localTime(o.last_cloud_sync)}`:' · Cloud sync unconfirmed';if(o.pending_cloud!==null&&o.pending_cloud!==undefined)message+=` · ${o.pending_cloud} queued`;$('#sync-message').textContent=message;
  const m=o.latest||{};$('#live-metrics').innerHTML=liveMetricInfo.map(([key,label,icon])=>`<article class="metric-card"><div class="metric-top"><span>${html(label)}</span><span class="metric-icon">${icon}</span></div><div class="metric-value">${fixed(m[key])}<span class="metric-unit">${html(units[key])}</span></div><div class="metric-hint">${m[key]===undefined?'No measurement yet':o.sensor_source==='SYNTHETIC_SAMPLE'?'Synthetic sample, not an ESP32 reading':'Latest ESP32 measurement'}</div></article>`).join('');
  $('#storage-type').textContent=o.sensor_source==='SYNTHETIC_SAMPLE'?'Sample data only':o.sensor_source==='ESP32_TIGERDATA'?'TigerData near-live':o.sensor_source==='ESP32_SHARED_READONLY'?'Shared cloud sensor feed':o.cloud_connected?'Private cloud sensor storage':'Cloud unavailable';$('#stored-count').textContent=o.cloud_record_count??'—';$('#last-cloud-sync').textContent=localTime(o.last_cloud_sync);
  renderFlags(o.flags||[]);
}
async function loadHistory(){try{const d=await api('/api/recorded?limit=100&offset=0');state.history=d.readings||[];const keys=['recorded_at','temperature_c','humidity_pct','pressure_hpa','soil_moisture_pct','rain_wetness_pct','light_pct','altitude_m'];$('#history-table tbody').innerHTML=state.history.length?state.history.map(r=>'<tr>'+keys.map((k,i)=>`<td>${i===0?html(easternTime(r[k])):fixed(r[k])}</td>`).join('')+'</tr>').join(''):'<tr><td colspan="8">No cloud records yet.</td></tr>';$('#history-note').textContent=(farmCloudMode==='sample'?'SIMULATED DEMO · ':'')+`Showing ${state.history.length} example readings; ${d.total||0} total.`;}catch(e){$('#history-note').textContent='Cloud receiver unavailable: '+e.message;}}
function exportCSV(){if(!state.history.length){showToast('There are no displayed readings to export.',true);return;}const columns=['recorded_at','device_id',...Object.keys(units).filter(key=>key!=='gas_index'&&key!=='ph')];const csv=[columns.join(','),...state.history.map(row=>columns.map(c=>'"'+String(row[c]??'').replaceAll('"','""')+'"').join(','))].join('\r\n');const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='fieldshift_recent_readings.csv';a.click();URL.revokeObjectURL(url);showToast('Exported current history rows.');}
function renderFlags(flags){const el=$('#local-flags');el.innerHTML=flags.length?'<div class="flags-title">LOCAL SENSOR FLAGS (NOT OFFICIAL WARNINGS)</div>'+flags.map(f=>`<div class="flag"><strong>${html(f.event)}</strong><small>${html(f.description)}</small></div>`).join(''):'';}
async function loadWeather(){try{const data=await api('/api/weather?mode=live',{timeout:28000});const list=data.forecast||[];$('#weather-report').innerHTML=list.length?list.slice(0,5).map(d=>{const day=new Date(d.date+'T12:00:00Z').toLocaleDateString(undefined,{weekday:'short',timeZone:'UTC'});return `<div class="forecast-day"><strong>${html(day)}</strong><span class="weather-desc">${html(d.summary||'')}</span><span class="temp">${fixed(d.high_c,0)}° / ${fixed(d.low_c,0)}°</span><span class="rain">☂ ${fixed(d.rain_chance_pct,0)}%</span></div>`;}).join(''):'<div class="alert-unavailable">Forecast unavailable.</div>';$('#forecast-source').textContent=data.forecast_source||'';renderAlerts(data.alert_status||{});}catch(e){$('#weather-report').textContent='Forecast unavailable: '+e.message;$('#alert-section').textContent='Official alert status unavailable. Consult the relevant meteorological service.';}}
function renderAlerts(a){const box=$('#alert-section'), alerts=a.alerts||[];if(a.status==='demo'){box.innerHTML='<div class="alert-unavailable"><strong>SIMULATION ONLY</strong> — The following example alert is fictional.</div>'+alerts.slice(0,3).map(x=>`<div class="alert-item"><strong>${html(x.event)}</strong><p>${html(x.headline||'')}</p></div>`).join('');return;}if(a.status==='live'){box.innerHTML=alerts.length?alerts.slice(0,7).map(x=>`<div class="alert-item"><strong>${html(x.event)} · ${html(x.severity)}</strong><p>${html(x.headline||'')}</p><p>Expires ${html(localTime(x.expires))}</p></div>`).join(''):'<div class="alert-clear">No active NWS alerts returned at last successful check for this point.</div>';return;}box.innerHTML='<div class="alert-unavailable">⚠ Official warnings could not be verified. An unavailable check does not mean conditions are safe. '+html(a.message||'')+'</div>';}
function numeric(v){const x=Number(v);return v===null||v===undefined||v===''||!Number.isFinite(x)?null:x;}
function plotSVG(series,dates,minHeight=124){
  // Draw mini-charts using native SVG, so the dashboard works without a chart CDN.
  const W=500,H=132,left=41,right=7,top=11,bottom=22;
  const vals=series.flatMap(s=>dates.map(d=>numeric(s.values[d])).filter(v=>v!==null));
  if(!vals.length)return '<div class="chart-empty">No observations for this period</div>';
  let min=Math.min(...vals),max=Math.max(...vals),range=max-min;
  if(range<0.01){min-=1;max+=1;range=max-min;}else{min-=range*.09;max+=range*.09;range=max-min;}
  const fx=i=>left+(dates.length<=1?.5:i/(dates.length-1))*(W-left-right);
  const fy=v=>top+(max-v)/range*(H-top-bottom);
  let out=`<svg class="mini-plot" role="img" aria-label="Time series chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for(let i=0;i<=2;i++){const y=top+i*(H-top-bottom)/2;out+=`<line x1="${left}" y1="${y}" x2="${W-right}" y2="${y}" stroke="#edf1ec"/><text x="${left-7}" y="${y+3}" font-size="10" fill="#96a79b" text-anchor="end">${(max-i*range/2).toFixed(range<3?1:0)}</text>`;}
  series.forEach(s=>{let points=[];const segments=[];
    dates.forEach((d,i)=>{const v=numeric(s.values[d]);if(v===null){if(points.length)segments.push(points);points=[];return;}points.push([fx(i),fy(v),v,d]);});
    if(points.length)segments.push(points);
    segments.forEach(p=>{out+=`<polyline fill="none" stroke="${s.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" ${s.dashed?'stroke-dasharray="6 5"':''} points="${p.map(a=>a[0]+','+a[1]).join(' ')}"/>`;
      if(p.length<30)p.forEach(([x,y,v,d])=>{out+=`<circle cx="${x}" cy="${y}" r="2.7" fill="${s.color}"><title>${html(d)}: ${v.toFixed(2)}</title></circle>`;});
    });
  });
  const labels=[dates[0],dates[Math.floor(dates.length/2)],dates[dates.length-1]];
  labels.forEach((d,i)=>{if(!d)return;const x=i===0?left:i===1?(W+left-right)/2:W-right;out+=`<text x="${x}" y="${H-3}" fill="#9cab9e" font-size="10" text-anchor="${i===0?'start':i===1?'middle':'end'}">${html(d.slice(5))}</text>`;});
  return out+'</svg>';
}
function plotDates(series,availableDays){const all=new Set(series.flatMap(s=>Object.keys(s.values||{})));return [...all].sort().slice(-availableDays);}

async function loadNASA(){await Promise.allSettled([loadNasaMeasurements(),loadLocalDays(),loadWeather()]);}
async function loadNasaMeasurements(){
  try{
    const data=await api('/api/nasa?mode=auto&days=90',{timeout:110000});
    state.nasa=data.nasa_daily||null;
    if(farmCloudMode==='sample'&&state.nasa?.is_real_nasa)
      await persist('nasa',state.nasa);
    renderNASA(data.note||'');
  }catch(e){
    $('#nasa-source').textContent='NASA POWER unavailable for this location: '+e.message;
    showToast('NASA POWER request failed: '+e.message,true);
  }
}
async function loadLocalDays(){try{const d=await api('/api/charts',{timeout:20000});state.localDays=d.local_days||{};renderNASAChart();}catch(e){state.localDays={};}}
function renderNASA(note=''){const n=state.nasa,rows=n?.rows||[];if(!rows.length){$('#nasa-source').textContent='No daily NASA records loaded. Click Download latest NASA data. This requires internet.';$('#nasa-metrics').innerHTML='<div class="empty-card">No regional data loaded.</div>';$('#nasa-table tbody').innerHTML='<tr><td colspan="10">No NASA observations loaded.</td></tr>';$('#nasa-chart').innerHTML='';return;}
  const rec=[...rows].reverse();const latest=rec[0]||{};const status=n.is_real_nasa?'REAL NASA POWER REGIONAL DATA':'SYNTHETIC NASA-LIKE DEMONSTRATION — NOT NASA DATA';$('#nasa-source').textContent=`${status} · ${n.period||''} · Downloaded ${localTime(n.fetched_at)}${note?' · '+note:''}`;$('#nasa-date-range').textContent=n.period||'';
  const cards=[['temperature_c','Daily air temp'],['temperature_max_c','Daily max'],['humidity_pct','Relative humidity'],['precipitation_mm','Daily rain'],['solar_mj_m2_day','Solar radiation'],['wind_2m_ms','Wind 2 m']];$('#nasa-metrics').innerHTML=cards.map(([key,label])=>`<article class="metric-card"><div class="metric-top"><span>${html(label)}</span><span class="metric-icon">◉</span></div><div class="metric-value">${fixed(latest[key])}<span class="metric-unit">${html(nasaInfo[key]?.[1]||'')}</span></div><div class="metric-hint">${n.is_real_nasa?'NASA day':'Simulated day'} ${html(latest.date||'—')}</div></article>`).join('');
  const fields=['date','temperature_c','temperature_max_c','temperature_min_c','humidity_pct','pressure_hpa','precipitation_mm','solar_mj_m2_day','wind_2m_ms','soil_wetness_fraction'];$('#nasa-table tbody').innerHTML=rec.slice(0,18).map(r=>'<tr>'+fields.map((key,i)=>`<td>${i===0?html(r.date):fixed(r[key],key==='soil_wetness_fraction'?3:1)}</td>`).join('')+'</tr>').join('');renderNASAChart();}
function renderNASAChart(){const n=state.nasa,rows=n?.rows||[],key=$('#nasa-variable').value;if(!rows.length)return;const count=Number($('#chart-days').value)||35,shown=rows.slice(-count),dates=shown.map(r=>r.date);const nasaValues=Object.fromEntries(shown.map(r=>[r.date,r[key]]));const ns={values:nasaValues,color:'#527cbb',dashed:true};const series=[ns];let legend=n?.is_real_nasa?'<span><b class="nasa"></b> NASA POWER daily regional data</span>':'<span><b class="nasa"></b> SIMULATED regional climate (demo)</span>',note=n?.is_real_nasa?'Regional estimates at NASA POWER grid scale. Values may lag current date.':'SIMULATED DEMO climate — no NASA observations were retrieved.';
  if(comparable[key]){const lv={};for(const d of dates){let x=state.localDays[d];if(x&&x[comparable[key]]!=null)lv[d]=x[comparable[key]];}if(Object.keys(lv).length){series.unshift({values:lv,color:'#24714f'});legend='<span><b></b> '+(farmCloudMode==='sample'?'Simulated ESP32 values':'Local ESP32 daily average')+'</span>'+legend;note+=' Local values are averaged by UTC day.';}}
  else if(key==='soil_wetness_fraction')note='This NASA modeled soil wetness fraction is not a calibrated field moisture percentage.';
  else if(key==='precipitation_mm')note='NASA rainfall is a daily total; the rain detector measures wetness, not rainfall depth.';
  else if(key==='solar_mj_m2_day')note='NASA solar energy and the photoresistor light index have different units.';
  $('#nasa-chart').innerHTML='<div class="chart-legend">'+legend+'</div><div class="nasa-chart-wrap">'+plotSVG(series,dates)+'</div>';$('#nasa-comparison-note').textContent=note;}
async function fetchNASA(){
  const b=$('#fetch-nasa');
  b.disabled=true;b.textContent='Downloading NASA POWER…';
  try{
    const d=await api('/api/nasa?mode=real&days=90',{timeout:65000});
    state.nasa=d.nasa_daily||null;
    if(farmCloudMode==='sample'&&state.nasa?.is_real_nasa)await persist('nasa',state.nasa);
    renderNASA(d.note||'');
    showToast('Real NASA POWER regional history loaded'+
      (farmCloudMode==='sample'?' in Demo Mode (browser-only cache).':'.'));
  }catch(e){showToast('NASA POWER download failed: '+e.message,true);}
  finally{b.disabled=false;b.textContent='Download latest NASA data';}
}
function cropRow(c={}){const row=document.createElement('div');row.className='crop-entry';
  const stages=['Planning','Germination','Seedling','Vegetative','Flowering','Fruiting','Maturing','Harvested'];
  row.innerHTML=`<div class="crop-entry-heading"><span>Crop</span><button class="remove-crop" title="Remove crop">×</button></div>
    <div class="crop-fields"><div><label>Crop name</label><input class="crop-name" maxlength="70" placeholder="e.g. Tomato" value="${html(c.name||'')}"></div><div><label>Area</label><input class="crop-area" type="number" min="0.01" step="0.1" value="${html(c.area??1)}"></div><div><label>Growth stage</label><select class="crop-stage">${stages.map(s=>`<option ${s===c.stage?'selected':''}>${s}</option>`).join('')}</select></div></div>
    <div class="crop-fields extra"><div><label>Planted on (optional)</label><input type="date" class="crop-date" value="${html(c.planted_on||'')}"></div><div><label>Variety (optional)</label><input class="crop-variety" maxlength="80" placeholder="Cultivar" value="${html(c.variety||'')}"></div></div>`;
  row.querySelector('.remove-crop').addEventListener('click',()=>{row.remove();updateAllocation();});
  row.querySelectorAll('input,select').forEach(el=>el.addEventListener('input',updateAllocation));return row;
}
function updateAllocation(){const size=Number($('#farm-size').value)||0;
  const used=$$('.crop-area').reduce((a,b)=>a+(Number(b.value)||0),0),remaining=size-used;
  const el=$('#allocation-summary');el.classList.toggle('over',remaining < -0.0001);
  el.textContent=`Allocated: ${used.toFixed(2)} / ${size.toFixed(2)} ${$('#area-unit').value} · ${remaining>=0?remaining.toFixed(2)+' remaining':'Overallocated by '+Math.abs(remaining).toFixed(2)}`;
  if(typeof renderCalendar==='function')renderCalendar();
}
async function loadPlan(){try{const p=await api('/api/plan');state.plan=p;
  $('#farm-size').value=p.total_area??5;$('#area-unit').value=p.area_unit||'acres';$('#farm-notes').value=p.notes||'';
  $('#crop-list').replaceChildren(...(p.crops||[]).map(c=>cropRow(c)));updateAllocation();renderCalendar();}
  catch(e){showToast(e.message,true);}}
function collectPlan(){return {total_area:Number($('#farm-size').value),area_unit:$('#area-unit').value,
  notes:$('#farm-notes').value,crops:$$('.crop-entry').map(el=>({name:el.querySelector('.crop-name').value.trim(),
    area:Number(el.querySelector('.crop-area').value),stage:el.querySelector('.crop-stage').value,
    planted_on:el.querySelector('.crop-date').value,variety:el.querySelector('.crop-variety').value.trim()}))};}
async function savePlan(){try{const r=await api('/api/plan',{method:'POST',body:collectPlan()});
  $('#plan-save-status').textContent=farmCloudMode==='ready'?'Saved in TigerData':'Saved in sample browser storage';showToast('Farm plan saved.');}
  catch(e){showToast(e.message,true);}}
// Chat is tab-session scoped, not localStorage or TigerData. The previous
// turns are attached to the next Gemini request for a genuine conversation.
let fieldyTurns=[];
const fieldySessionKey=()=> 'cropaganda_fieldy_tab_v1_'+fsAccount;
function fieldyLoadHistory(){
  try{
    const stored=JSON.parse(sessionStorage.getItem(fieldySessionKey())||'[]');
    fieldyTurns=Array.isArray(stored)?stored.filter(x=>
      x&&['user','assistant'].includes(x.role)&&typeof x.content==='string').slice(-20):[];
  }catch(e){fieldyTurns=[];}
  fieldyRenderConversation();
}
function fieldyStoreHistory(){
  // Limits browser storage and request size; no conversation is stored on server.
  fieldyTurns=fieldyTurns.slice(-20);
  try{sessionStorage.setItem(fieldySessionKey(),JSON.stringify(fieldyTurns));}
  catch(e){showToast('Chat continues in this tab but browser session storage is unavailable.',true);}
}
function fieldyClearHistory(){
  if(!confirm('Clear this tab\'s Fieldy conversation? This does not change farm or calendar records.'))return;
  fieldyTurns=[];
  try{sessionStorage.removeItem(fieldySessionKey());}catch(e){}
  fieldyRenderConversation();
}
function renderFieldyAdvice(a){
  // Convert *only* safe escaped **emphasis** into bold. No model HTML executes.
  const answer=html(String(a?.answer||'No answer returned.')).replace(/\*\*([^\n*]{1,130})\*\*/g,'<strong>$1</strong>');
  const assumptions=(Array.isArray(a?.assumptions)?a.assumptions:[]).map(x=>`<li>${html(x)}</li>`).join('');
  const sources=(Array.isArray(a?.source_notes)?a.source_notes:[]).map(x=>`<li>${html(x)}</li>`).join('');
  const highlights=(Array.isArray(a?.highlights)?a.highlights:[]).slice(0,4).filter(x=>x&&x.label&&x.value).map(x=>
    `<div class="fieldy-highlight"><span class="fieldy-highlight-label">${html(x.label)}</span>`+
    `<strong class="fieldy-highlight-value">${html(x.value)}</strong>`+
    `<span class="fieldy-highlight-source">Source: ${html(x.source||'Not specified')}</span></div>`).join('');
  return `<div class="fieldy-message-content">${answer}</div>`+
    (highlights?`<div class="fieldy-highlights" aria-label="Key insights">${highlights}</div>`:'')+
    (assumptions?`<div class="fieldy-section"><b>Assumptions / estimates</b><ul>${assumptions}</ul></div>`:'')+
    (sources?`<div class="fieldy-section"><b>Data used / limitations</b><ul>${sources}</ul></div>`:'');
}
function fieldyRenderConversation(pending=null,error=''){
  const box=$('#fieldy-chat-history');
  if(!box)return;
  const entries=fieldyTurns.map(turn=>{
    const user=turn.role==='user';
    const label=user?'You':turn.provider==='demo'?'Fieldy · Demonstration':'Fieldy · Powered by Gemini';
    const body=user?`<div class="fieldy-message-content">${html(turn.content)}</div>`:
      renderFieldyAdvice(turn.advice||{answer:turn.content});
    return `<div class="fieldy-message ${user?'fieldy-message-user':'fieldy-message-assistant'}">`+
      `<div class="fieldy-message-label">${label}</div>${body}</div>`;
  });
  if(!entries.length)entries.push('<p class="fieldy-welcome">Hi, farmer! 🌱 Ask me about your crops, farm conditions, or the Soil &amp; Rotation guide. I can follow up on earlier questions in this tab.</p>');
  if(pending){
    entries.push(`<div class="fieldy-message fieldy-message-user"><div class="fieldy-message-label">You</div><div class="fieldy-message-content">${html(pending)}</div></div>`);
    entries.push('<div class="fieldy-message fieldy-message-assistant thinking"><div class="fieldy-message-label">'+(farmCloudMode==='sample'?'Fieldy · Demo':'Fieldy · Gemini')+'</div>Reviewing your question and available farm/soil information…</div>');
  }
  if(error)entries.push(`<p class="fieldy-welcome" role="alert">${html(error)}</p>`);
  box.innerHTML=entries.join('');
  box.scrollTop=box.scrollHeight;
}
function fieldyAddTurn(role,content,advice=null,provider='gemini'){
  fieldyTurns.push({role,content:String(content).slice(0,7000),advice,provider});
  fieldyStoreHistory();
  fieldyRenderConversation();
}
function fieldySoilView(){
  if(typeof soilState==='undefined')return {};
  const location=currentLocation();
  if(!Number.isFinite(Number(location?.latitude))||!Number.isFinite(Number(location?.longitude)))
    return {};
  const crop=typeof SOIL_CROPS!=='undefined'?SOIL_CROPS.find(x=>x.id===soilState.crop):null;
  const profile=soilState.profile?.status==='ok'?soilState.profile.profile:null;
  return {latitude:location.latitude,longitude:location.longitude,
    profile_status:soilState.profile?.status,
    profile:profile||null,
    context:soilState.context||null,
    crop_guide:crop?{name:crop.name,type:crop.type,family:crop.family,water:crop.water,
      soil:crop.soil,watch:crop.watch,soilTip:crop.soilTip,season:crop.season,
      before:crop.before,after:crop.after}:null,
    rotation_goal:$('#soil-rotation-goal')?.value||null,
    current_crop:$('#soil-current-crop')?.value||null};
}
let pendingFieldyCalendar=null;
async function confirmFieldyCalendar(){
  if(!pendingFieldyCalendar)return;
  const p=pendingFieldyCalendar,button=$('#fieldy-calendar-yes');
  button.disabled=true;
  try{
    const status=await api('/api/google/status');
    if(!status.connected){
      showToast('Connect Google Calendar first, then confirm this task again.',true);
      $('#google-calendar-status').textContent='Connect Google Calendar to enable the two-calendar confirmation.';
      return;
    }
    // Google is written first; local farm calendar is only added if it succeeded.
    // The idempotent request ID prevents double Google events after retries.
    const g=await api('/api/google/events',{method:'POST',body:{...p,confirmed:true,
      request_id:p.request_id},timeout:28000});
    const r=await api('/api/calendar',{method:'POST',body:{...p,id:p.request_id,
      google_event_id:g.event_id}});
    calendarState.tasks=r.events;
    const parts=p.date.split('-').map(Number);
    calendarState.year=parts[0];calendarState.month=parts[1]-1;
    calendarState.selected=p.date;renderCalendar();
    pendingFieldyCalendar=null;persist('fieldy_calendar_pending',null);
    $('#fieldy-calendar-confirmation').classList.add('hidden');
    fieldyAddTurn('assistant','Added '+(calendarKinds[p.kind]||'Farm task')+
      (p.crop?' for '+p.crop:'')+' on '+prettyDay(p.date)+
      ' to both your farm calendar and Google Calendar.');
    showToast('Saved to Farm Calendar and Google Calendar.');
  }catch(err){showToast('Could not sync both calendars: '+err.message,true);}
  finally{button.disabled=false;}
}
function dismissFieldyCalendar(){
  pendingFieldyCalendar=null;persist('fieldy_calendar_pending',null);
  $('#fieldy-calendar-confirmation').classList.add('hidden');
  showToast('Calendar proposal dismissed; nothing was added.');
}
function showFieldyCalendarProposal(raw){
  if(!raw||!/^\d{4}-\d{2}-\d{2}$/.test(raw.date)||!calendarKinds[raw.kind])return;
  pendingFieldyCalendar={date:raw.date,kind:raw.kind,crop:String(raw.crop||'').slice(0,70),
    note:String(raw.note||'').slice(0,240),request_id:raw.request_id||crypto.randomUUID().replaceAll('-','')};
  persist('fieldy_calendar_pending',pendingFieldyCalendar);
  $('#fieldy-calendar-proposal').textContent=(calendarKinds[raw.kind]||'Farm task')+
    (raw.crop?' · '+raw.crop:'')+' — '+prettyDay(raw.date);
  $('#fieldy-calendar-confirmation').classList.remove('hidden');
}
async function loadGoogleCalendarStatus(){
  const badge=$('#google-calendar-badge'),button=$('#connect-google-calendar');
  if(farmCloudMode==='sample'){
    badge.textContent='Demo only';
    $('#google-calendar-status').textContent='Google Calendar is unavailable in demo mode. Add simulated farm tasks below.';
    button.disabled=true;button.textContent='Unavailable in demo';
    $('#disconnect-google-calendar').classList.add('hidden');
    return;
  }
  try{
    const r=await api('/api/google/status');
    badge.textContent=r.connected?'● Connected':r.configured?'Not connected':'Setup required';
    $('#google-calendar-status').textContent=r.message||'';
    button.disabled=!r.configured;
    button.textContent=r.connected?'Reconnect Google Calendar':'Connect Google Calendar';
    $('#disconnect-google-calendar').classList.toggle('hidden',!r.connected);
    const query=new URLSearchParams(location.search);
    if(query.has('google_calendar')){
      showToast(query.get('google_calendar')==='connected'?'Google Calendar connected. Now confirm your pending task.':
        'Google Calendar connection was not completed.',query.get('google_calendar')!=='connected');
      history.replaceState(null,'',location.pathname);
    }
  }catch(e){badge.textContent='Unavailable';$('#google-calendar-status').textContent=e.message;}
}
async function askGemini(){
  const promptBox=$('#farm-question');
  const typed=promptBox.value.trim();
  if(!typed)return;
  if(pendingFieldyCalendar&&/^(yes|yeah|yep|sure|confirm|add it|yes please|do it)[.!\s]*$/i.test(typed)){
    promptBox.value='';
    await confirmFieldyCalendar();return;
  }
  if(pendingFieldyCalendar&&/^(no|nope|cancel|not now)[.!\s]*$/i.test(typed)){
    promptBox.value='';
    dismissFieldyCalendar();return;
  }
  const btn=$('#ask-gemini');
  if(btn.disabled)return;
  btn.disabled=true;btn.textContent='Fieldy is thinking…';
  // Only successful, bounded turns are sent; history is always scoped to
  // this browser tab and signed-in account.
  const prior=fieldyTurns.slice(-12).map(t=>({role:t.role,content:t.content.slice(0,1400)}));
  fieldyRenderConversation(typed);
  try{
    const req={plan:collectPlan(),model:'gemini-3.5-flash-lite',question:typed,
      chat_history:prior,soil_view:fieldySoilView(),weather_mode:'live'};
    const r=await api('/api/plan/advice',{method:'POST',body:req,timeout:110000});
    if(!r.advice_structured)throw Error('Gemini returned an unexpected response.');
    fieldyTurns.push({role:'user',content:typed.slice(0,2500)});
    fieldyTurns.push({role:'assistant',content:String(r.advice_structured.answer||'').slice(0,7000),
      advice:r.advice_structured,provider:r.provider||'gemini'});
    fieldyStoreHistory();
    fieldyRenderConversation();
    promptBox.value='';
    pendingFieldyCalendar=null;persist('fieldy_calendar_pending',null);
    $('#fieldy-calendar-confirmation').classList.add('hidden');
    if(r.calendar_proposal)showFieldyCalendarProposal(r.calendar_proposal);
  }catch(e){
    fieldyRenderConversation(null,'Could not answer yet: '+e.message+' — your question is still in the text box.');
    showToast(e.message,true);
  }finally{btn.disabled=false;btn.textContent=farmCloudMode==='sample'?'✦ Ask demo Fieldy':'✦ Ask Fieldy for advice';}
}
async function loadGeminiStatus(){
  try{
    const status=await api('/api/gemini/status');
    if(status.mode==='sample'){
      $('#advisor-key-status').textContent='Demo mode, key not available · Scripted sample advice only.';
      const badge=$('.gemini-watermark');
      badge.textContent='✦ Demo mode, key not available';
      badge.setAttribute('aria-label','Demo mode. Gemini key unavailable to public demo accounts');
      $('#ask-gemini').textContent='✦ Ask demo Fieldy';
    }else{
      $('#advisor-key-status').textContent=status.configured?'● Gemini ready · Verified Auth0 account':'○ '+(status.note||'Gemini unavailable');
    }
  }catch(e){$('#advisor-key-status').textContent='Gemini settings unavailable';}
}

function fillSelect(element, values, placeholder) {
  const select = $(element);
  const previous = select.value;
  select.replaceChildren();
  const initial = document.createElement('option');initial.value='';initial.textContent=placeholder;
  select.appendChild(initial);
  values.forEach(([key,label])=>{const option=document.createElement('option');option.value=key;option.textContent=label;select.appendChild(option);});
  select.disabled = values.length===0;
  if(values.some(([key])=>key===previous))select.value=previous;
}
async function initLocations(){
  try {
    const result=await api('/api/locations/catalog');state.locations=result.countries;
    const countries=Object.entries(state.locations).map(([key,v])=>[key,v.name]).sort((a,b)=>a[1].localeCompare(b[1]));
    fillSelect('#country-select',countries,'Select a country');
    // Choose a useful default, but show the farm's previously saved selection when available.
    $('#country-select').value='US';updateRegions();
    $('#region-select').value='New York';updateCities();$('#city-select').value='New York City';
    const location=saved('location')||(await api('/api/overview')).location;
    if(location?.mode==='preset'){
      for(const [code,country] of Object.entries(state.locations)){
        let found=false;
        for(const [region,cities] of Object.entries(country.regions)){
          for(const city of Object.keys(cities)){
            if(location.label!==`${city}, ${region}, ${country.name}`)continue;
            $('#country-select').value=code;updateRegions();
            $('#region-select').value=region;updateCities();$('#city-select').value=city;
            found=true;break;
          }
          if(found)break;
        }
        if(found)break;
      }
    }else if(location?.mode==='coords'&&!String(location.label).includes('DEMO')){
      document.querySelector('input[name="loc-mode"][value="coords"]').checked=true;
      $('#lat').value=location.latitude;$('#lon').value=location.longitude;locationMode();
    }
  }catch(e){showToast('Could not load built-in locations: '+e.message,true);}
}
function updateRegions(){
  const record=state.locations?.[$('#country-select').value];
  fillSelect('#region-select',Object.keys(record?.regions||{}).sort((a,b)=>a.localeCompare(b)).map(v=>[v,v]),'Select state / region');
  updateCities();
}
function updateCities(){
  const cities=state.locations?.[$('#country-select').value]?.regions?.[$('#region-select').value]||{};
  fillSelect('#city-select',Object.keys(cities).sort((a,b)=>a.localeCompare(b)).map(v=>[v,v]),'Select a city');
}
function locationMode(){const mode=$('input[name="loc-mode"]:checked').value;$('#area-field').classList.toggle('hidden',mode!=='preset');$('#coordinate-fields').classList.toggle('hidden',mode!=='coords');}
async function saveLocation(){
  const mode=$('input[name="loc-mode"]:checked').value;
  const data=mode==='preset'?{mode,country:$('#country-select').value,region:$('#region-select').value,city:$('#city-select').value}
    :{mode,latitude:Number($('#lat').value),longitude:Number($('#lon').value)};
  if(mode==='preset'&&(!data.country||!data.region||!data.city)){showToast('Select country, state / region and city first.',true);return;}
  const btn=$('#save-location');btn.disabled=true;
  try{const r=await api('/api/location',{method:'POST',body:data,timeout:32000});
    $('#location-label').textContent=r.location.label;$('#location-current').textContent=r.location.label;
    $('#location-message').textContent=farmCloudMode==='ready'?'Farm location saved in TigerData.':'Sample farm location saved in this browser.';
    state.nasa=null;
    if(farmCloudMode==='ready')$('#location-message').textContent='Farm location saved in TigerData and registered for automatic daily NASA POWER sync.';
    showToast('Farm location updated.');await loadLive();
  }catch(e){$('#location-message').textContent=e.message;showToast(e.message,true);}
  finally{btn.disabled=false;}
}
// Farm calendar: manual tasks persist through the API. Crop planting dates
// are derived from the crop list, so changing a planting date moves its marker.
const calendarState={year:new Date().getFullYear(),month:new Date().getMonth(),selected:'',tasks:[]};
const calendarKinds={planting:'Planting',watering:'Watering',harvest:'Harvest',fertilizing:'Fertilizing',inspection:'Inspection',other:'Other'};
function dateISO(y,m,d){return `${y}-${String(m+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;}
function todayISO(){const d=new Date();return dateISO(d.getFullYear(),d.getMonth(),d.getDate());}
function prettyDay(s){const p=s.split('-').map(Number);return new Date(p[0],p[1]-1,p[2]).toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'});}
function calendarPlantings(){return collectPlan().crops.filter(c=>/^\d{4}-\d{2}-\d{2}$/.test(c.planted_on)).map((c,i)=>({id:`plant-${i}`,date:c.planted_on,kind:'planting',crop:c.name,note:'Planting date from crop list',derived:true}));}
function allCalendarEvents(){return [...calendarState.tasks,...calendarPlantings()];}
function chooseCalendarDay(s){calendarState.selected=s;$('#event-date').value=s;renderCalendar();}
function renderCalendar(){
  const c=calendarState;
  $('#calendar-label').textContent=new Date(c.year,c.month,1).toLocaleDateString(undefined,{month:'long',year:'numeric'});
  if(!c.selected)c.selected=todayISO();
  if(!$('#event-date').value)$('#event-date').value=c.selected;
  $('#calendar-selected-label').textContent=prettyDay(c.selected);
  const all=allCalendarEvents();
  const first=new Date(c.year,c.month,1).getDay();
  const days=new Date(c.year,c.month+1,0).getDate();
  const slots=Math.ceil((first+days)/7)*7;
  const grid=$('#calendar-grid');grid.replaceChildren();
  for(let i=0;i<slots;i++){
    const day=i-first+1;
    const dt=new Date(c.year,c.month,day);
    const date=dateISO(dt.getFullYear(),dt.getMonth(),dt.getDate());
    const events=all.filter(e=>e.date===date);
    const cell=document.createElement('button');cell.type='button';cell.className='calendar-day';
    if(dt.getMonth()!==c.month)cell.classList.add('other-month');
    if(date===c.selected)cell.classList.add('selected');
    if(date===todayISO())cell.classList.add('today');
    cell.setAttribute('aria-label',`${prettyDay(date)}, ${events.length} tasks`);
    const number=document.createElement('span');number.className='calendar-number';number.textContent=String(dt.getDate());cell.appendChild(number);
    const marks=document.createElement('span');marks.className='calendar-marks';
    events.slice(0,3).forEach(ev=>{const dot=document.createElement('i');dot.className='event-dot '+(calendarKinds[ev.kind]?ev.kind:'other');dot.title=`${calendarKinds[ev.kind]||'Task'} ${ev.crop||''}`;marks.appendChild(dot);});
    if(events.length>3){const more=document.createElement('span');more.textContent=`+${events.length-3}`;marks.appendChild(more);}
    cell.appendChild(marks);cell.onclick=()=>{c.year=dt.getFullYear();c.month=dt.getMonth();chooseCalendarDay(date);};grid.appendChild(cell);
  }
  const events=all.filter(e=>e.date===c.selected);
  const list=$('#calendar-events');list.replaceChildren();
  if(!events.length){const empty=document.createElement('p');empty.className='muted calendar-empty';empty.textContent='No tasks scheduled for this date.';list.appendChild(empty);}
  events.forEach(event=>{
    const row=document.createElement('div');row.className='calendar-event';
    const dot=document.createElement('i');dot.className='event-dot '+event.kind;row.appendChild(dot);
    const desc=document.createElement('div');desc.className='calendar-event-description';
    const name=document.createElement('strong');name.textContent=(calendarKinds[event.kind]||'Task')+(event.crop?' · '+event.crop:'');desc.appendChild(name);
    if(event.note){const note=document.createElement('small');note.textContent=event.note;desc.appendChild(note);}row.appendChild(desc);
    if(!event.derived){const remove=document.createElement('button');remove.className='calendar-remove';remove.textContent='×';remove.title='Delete task';remove.setAttribute('aria-label','Delete task');remove.onclick=()=>deleteCalendarEvent(event.id);row.appendChild(remove);}
    list.appendChild(row);
  });
  const suggestions=$('#crop-suggestions');suggestions.replaceChildren();
  collectPlan().crops.forEach(c=>{const option=document.createElement('option');option.value=c.name;suggestions.appendChild(option);});
}
async function loadCalendar(){try{const r=await api('/api/calendar');calendarState.tasks=r.events||[];renderCalendar();}catch(e){showToast('Calendar unavailable: '+e.message,true);}}
async function addCalendarEvent(e){e.preventDefault();
  const payload={date:$('#event-date').value,kind:$('#event-type').value,crop:$('#event-crop').value.trim(),note:$('#event-note').value.trim()};
  try{const r=await api('/api/calendar',{method:'POST',body:payload});calendarState.tasks=r.events;calendarState.selected=payload.date;
    const parts=payload.date.split('-').map(Number);calendarState.year=parts[0];calendarState.month=parts[1]-1;
    $('#event-note').value='';renderCalendar();showToast('Calendar task saved.');}catch(err){showToast(err.message,true);}
}
async function deleteCalendarEvent(id){try{const r=await api('/api/calendar/'+encodeURIComponent(id),{method:'DELETE'});calendarState.tasks=r.events;renderCalendar();showToast('Task deleted.');}catch(e){showToast(e.message,true);}}
function moveCalendarMonth(change){const d=new Date(calendarState.year,calendarState.month+change,1);calendarState.year=d.getFullYear();calendarState.month=d.getMonth();renderCalendar();}


let archiveReady=false;
function archiveView(){return saved('sensor_view','auto');}
function archiveLocation(){return currentLocation();}
function initArchive(){
  archiveReady=true;
  // Refresh the list each visit so newly archived dates become selectable.
  loadArchiveDates();
}
async function loadArchiveDates(){
  const select=$('#archive-date'),previous=select.value,status=$('#archive-message');
  try{
    const s=await api('/api/history/status');
    if(!s.configured){
      select.replaceChildren(new Option('TigerData not configured',''));
      $('#archive-snapshot').replaceChildren(new Option('No saved timestamps',''));
      status.textContent='TigerData is not connected yet. No sample data will be generated.';
      return;
    }
    const data=await api('/api/history/dates?view='+encodeURIComponent(archiveView()));
    select.replaceChildren(new Option('Select a saved date',''));
    for(const day of data.dates||[]){
      const label=new Date(day+'T12:00:00Z').toLocaleDateString(undefined,
        {weekday:'short',month:'long',day:'numeric',year:'numeric',timeZone:'America/New_York'});
      select.add(new Option(label+' · '+day,day));
    }
    if((data.dates||[]).includes(previous))select.value=previous;
    status.textContent=data.dates?.length?(data.demo?'SIMULATED DEMO archive · ':'')+'Choose a date, then an example timestamp.':
      (data.demo?'No simulated readings available.':'No historical ESP32 data yet. Only real uploaded readings will appear here.');
    await loadArchiveTimes();
  }catch(e){status.textContent='History unavailable: '+e.message;}
}
async function loadArchiveTimes(){
  const day=$('#archive-date').value,select=$('#archive-snapshot');
  if(!day){select.replaceChildren(new Option('Select a date',''));return;}
  try{
    const data=await api('/api/history/snapshots?day='+encodeURIComponent(day)+'&view='+encodeURIComponent(archiveView()));
    select.replaceChildren(new Option('Select a saved time',''));
    for(const snap of data.snapshots){
      const option=new Option(easternTime(snap.recorded_at)+' · '+snap.device_id,snap.bucket_at);
      select.add(option);
    }
    $('#archive-message').textContent=data.snapshots.length?
      (data.demo?'SIMULATED DEMO · ':'')+data.snapshots.length+' example timestamp(s) on '+day+'.':
      (data.demo?'No example readings for this date.':'No archived ESP32 readings on '+day+'.');
  }catch(e){
    select.replaceChildren(new Option('Saved times unavailable',''));
    $('#archive-message').textContent='Unable to load saved times: '+e.message;
  }
}
async function loadArchiveEntry(){
  const day=$('#archive-date').value,bucket=$('#archive-snapshot').value;
  if(!day||!bucket){showToast('Choose a day and a saved timestamp first.',true);return;}
  const l=archiveLocation();
  try{
    const query='day='+encodeURIComponent(day)+'&bucket='+encodeURIComponent(bucket)+
      '&latitude='+encodeURIComponent(l.latitude)+'&longitude='+encodeURIComponent(l.longitude)+
      '&view='+encodeURIComponent(archiveView());
    const d=await api('/api/history/entry?'+query,{timeout:22000});
    const reading=d.sensor||{};
    $('#archive-sensor-time').textContent='Device '+(reading.device_id||'—')+' · '+easternTime(reading.recorded_at)+
      ' · '+(d.demo?'SIMULATED sensor':d.sensor_access==='shared'?'Shared read-only ESP32':'Account ESP32');
    $('#archive-sensor-cards').innerHTML=metricInfo.map(([key,label,icon])=>
      '<article class="metric-card"><div class="metric-top"><span>'+html(label)+
      '</span><span class="metric-icon">'+icon+'</span></div><div class="metric-value">'+fixed(reading[key])+
      '<span class="metric-unit">'+html(units[key])+'</span></div><div class="metric-hint">'+(d.demo?'SIMULATED DEMO reading':'Saved ESP32 reading')+'</div></article>').join('');
    $('#archive-message').textContent=d.demo?'SIMULATED DEMO history · Not authentic ESP32 or TigerData records.':
      'Loaded authentic saved ESP32 reading for '+day+'.';
  }catch(e){showToast('Unable to load history: '+e.message,true);}
}
function attach(){
  $$('.navitem').forEach(n=>n.addEventListener('click',()=>tab(n.dataset.tab)));
  $('#mobile-menu').onclick=()=>$('.sidebar').classList.toggle('open');
  $('#refresh-button').onclick=()=>tab(state.tab);
  $('#history-details').addEventListener('toggle',e=>{if(e.target.open)loadHistory();});
  $('#export-csv').onclick=exportCSV;
  $('#archive-date').onchange=loadArchiveTimes;
  $('#archive-load').onclick=loadArchiveEntry;
  $('#fetch-nasa').onclick=fetchNASA;$('#change-nasa-location').onclick=()=>tab('crops');
  $('#nasa-variable').onchange=renderNASAChart;$('#chart-days').onchange=renderNASAChart;
  $('#sensor-view').onchange=e=>{persist('sensor_view',e.target.value);loadLive();loadHistory();loadLocalDays();};
  $$('input[name="loc-mode"]').forEach(n=>n.addEventListener('change',locationMode));
  $('#country-select').onchange=updateRegions;$('#region-select').onchange=updateCities;
  $('#save-location').onclick=saveLocation;
  $('#farm-size').oninput=updateAllocation;$('#area-unit').onchange=updateAllocation;
  $('#add-crop').onclick=()=>{$('#crop-list').appendChild(cropRow({name:'',area:1,stage:'Planning'}));updateAllocation();};
  $('#save-farm').onclick=savePlan;$('#ask-gemini').onclick=askGemini;$('#pair-device').onclick=pairDevice;
  $('#fieldy-clear-chat').addEventListener('click',fieldyClearHistory);
  $('#farm-question').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();askGemini();}
  });
  $('#fieldy-calendar-yes').onclick=confirmFieldyCalendar;
  $('#fieldy-calendar-no').onclick=dismissFieldyCalendar;
  $('#connect-google-calendar').onclick=()=>location.assign('/api/google/connect');
  $('#disconnect-google-calendar').onclick=async()=>{
    if(!confirm('Disconnect Google Calendar? Farm tasks already saved here remain.'))return;
    try{await api('/api/google/disconnect',{method:'POST',body:{}});await loadGoogleCalendarStatus();}
    catch(e){showToast(e.message,true);}
  };
  $('#generate-share-token').onclick=generateViewingToken;
  $('#join-shared-device').onclick=joinSharedDevice;
  $('#disconnect-shared-device').onclick=disconnectSharedDevice;
  $('#revoke-shared-device').onclick=revokeSharedDevice;
  $('#calendar-prev').onclick=()=>moveCalendarMonth(-1);
  $('#calendar-next').onclick=()=>moveCalendarMonth(1);
  $('#calendar-today').onclick=()=>{const d=new Date();calendarState.year=d.getFullYear();calendarState.month=d.getMonth();chooseCalendarDay(todayISO());};
  $('#calendar-form').addEventListener('submit',addCalendarEvent);
  $('#farm-import-button').addEventListener('click',importBrowserFarmData);
  $('#farm-import-reopen').addEventListener('click',()=>{
    localStorage.removeItem(fsKey('farm_cloud_import_ack'));
    showFarmImportOffer();
    $('#farm-import-banner').scrollIntoView({block:'center',behavior:'smooth'});
  });
  $('#farm-cloud-refresh').addEventListener('click',async()=>{
    if(farmCloudMode==='sample'){showToast('Sample farm data is stored in this browser.');return;}
    if(!confirm('Reload your farm from TigerData? Unsaved edits on this page will be lost.'))return;
    farmCloudMode='loading';
    await loadFarmCloud();
    if(farmCloudMode==='ready'){
      await Promise.allSettled([loadPlan(),loadCalendar(),initLocations()]);
      if(typeof soilLoad==='function')soilLoad(true);
      showToast('Farm data refreshed from TigerData.');
    }
  });
  $('#farm-import-skip').addEventListener('click',()=>{
    localStorage.setItem(fsKey('farm_cloud_import_ack'),JSON.stringify(true));
    $('#farm-import-banner').classList.add('hidden');
    cloudNotice('● TigerData connected · Kept existing cloud data. Old browser entries remain on this device.');
  });
}
async function pairDevice(){
  const box=$('#device-pair-result'),button=$('#pair-device');
  const id=($('#device-id').value||'esp32-01').trim();
  button.disabled=true;box.textContent='Generating a private device token…';
  try{
    const r=await api('/api/device/token',{method:'POST',body:{device_id:id}});
    box.replaceChildren();
    const label=document.createElement('p');label.textContent='Private token (copy once and keep secret):';
    const input=document.createElement('textarea');input.readOnly=true;input.rows=3;input.style.width='100%';input.value=r.token;
    const copy=document.createElement('button');copy.type='button';copy.className='secondary-btn';copy.textContent='Copy device token';
    copy.onclick=()=>navigator.clipboard.writeText(r.token).then(()=>showToast('Device token copied.'));
    const note=document.createElement('p');note.className='footnote';
    note.textContent=`Upload to ${r.upload_url} no more frequently than once every ${Math.round(r.min_interval_seconds/60)} minutes. Your token expires after ${r.expires_days} days. Never commit the token to GitHub.`;
    box.append(label,input,copy,note);
  }catch(e){box.textContent='Unable to pair ESP32: '+e.message;showToast(e.message,true)}
  finally{button.disabled=false;}
}
function showPrivateToken(boxId,token,title){
  const box=$(boxId);
  box.replaceChildren();
  const label=document.createElement('p');label.textContent=title;
  const input=document.createElement('textarea');input.value=token;input.readOnly=true;input.rows=3;input.style.width='100%';
  const copy=document.createElement('button');copy.type='button';copy.className='secondary-btn';copy.textContent='Copy viewing token';
  copy.onclick=()=>navigator.clipboard.writeText(token).then(()=>showToast('Viewing token copied.'));
  box.append(label,input,copy);
}
async function generateViewingToken(){
  const button=$('#generate-share-token'),box=$('#share-token-result');
  button.disabled=true;box.textContent='Generating view-only access…';
  try{
    const device_id=($('#share-device-id').value||'esp32-01').trim();
    const r=await api('/api/device/share/token',{method:'POST',body:{device_id}});
    showPrivateToken('#share-token-result',r.token,'Share this view-only token with the other Auth0 account. It expires in 180 days.');
  }catch(e){box.textContent='Could not generate viewing token: '+e.message;showToast(e.message,true);}
  finally{button.disabled=false;}
}
async function loadSharedDeviceStatus(){
  try{
    const s=await api('/api/device/share/status');
    $('#shared-device-status').textContent=s.connected?'Connected to shared ESP32: '+s.device_id+' · Read-only':'No shared ESP32 is linked to this account.';
  }catch(e){$('#shared-device-status').textContent='Shared device status unavailable: '+e.message;}
}
async function joinSharedDevice(){
  const token=$('#shared-device-token').value.trim();
  if(!token){showToast('Paste a viewing token first.',true);return;}
  const button=$('#join-shared-device');button.disabled=true;
  try{
    const r=await api('/api/device/share/join',{method:'POST',body:{token}});
    $('#shared-device-token').value='';
    persist('sensor_view','shared');$('#sensor-view').value='shared';
    showToast('Shared ESP32 '+r.device_id+' connected.');
    await loadSharedDeviceStatus();await loadLive();await loadHistory();await loadLocalDays();
  }catch(e){showToast('Could not connect shared device: '+e.message,true);}
  finally{button.disabled=false;}
}
async function disconnectSharedDevice(){
  if(!confirm('Disconnect the shared ESP32 from this account?'))return;
  try{
    await api('/api/device/share/disconnect',{method:'POST',body:{}});
    persist('sensor_view','auto');$('#sensor-view').value='auto';
    showToast('Shared ESP32 disconnected.');await loadSharedDeviceStatus();await loadLive();await loadHistory();
  }catch(e){showToast(e.message,true);}
}
async function revokeSharedDevice(){
  if(!confirm('Revoke every viewing token you generated for your ESP32? Other accounts will lose access.'))return;
  try{
    await api('/api/device/share/revoke',{method:'POST',body:{}});
    showToast('All previous viewing tokens revoked.');
  }catch(e){showToast(e.message,true);}
}
async function loadAccount(){
  try{
    const data=await api('/api/auth/me');const account=$('#account-box');
    if(!data.authenticated){window.location.replace('/');return;}
    if(data.authenticated){
      fsAccount='auth_'+String(data.user?.sub||'').replace(/[^a-z0-9_-]/gi,'_').slice(0,80);
      fieldyLoadHistory();
      $('#sensor-view').value=saved('sensor_view','auto');
      farmCloudMode=data.user?.mode==='sample'?'sample':'loading';
      const demo=farmCloudMode==='sample';
      $('#demo-mode-banner').classList.toggle('hidden',!demo);
      $('#device-pair-panel').classList.toggle('hidden',demo);
      if(demo){
        if(!saved('location'))await persist('location',{mode:'coords',label:'Test Farm — San Diego, California',latitude:32.7157,longitude:-117.1611,resolution:'sample city-center coordinates'});
        if(!saved('plan'))await persist('plan',await api('/api/plan'));
        if(!saved('calendar')){
          const day=delta=>{const d=new Date();d.setDate(d.getDate()+delta);return dateISO(d.getFullYear(),d.getMonth(),d.getDate());};
          await persist('calendar',[
            {id:'demo-inspection',date:day(2),kind:'inspection',crop:'Corn',note:'SIMULATED: Inspect mock irrigation and plant health.'},
            {id:'demo-watering',date:day(4),kind:'watering',crop:'Tomato',note:'SIMULATED: Check pretend soil moisture before watering.'},
            {id:'demo-harvest',date:day(9),kind:'harvest',crop:'Potato',note:'SIMULATED: Example harvest preparation.'}
          ]);
        }
        $('#fetch-nasa').textContent='Download latest NASA data';
      }
      $('#farm-cloud-refresh').classList.toggle('hidden',farmCloudMode==='sample');
      if(demo)cloudNotice('SIMULATED DEMO · Farm data stays in this browser; no TigerData access.');
      else await loadFarmCloud();
      account.textContent='Signed in: '+(data.user?.name||data.user?.email||'Farmer')+' · ';
      const link=document.createElement('a');link.href='/auth/logout';link.textContent='Sign out';account.appendChild(link);
    }else{fsAccount='preview';account.textContent='Public preview · Browser-only farm plan';}
  }catch(e){farmCloudMode='error';cloudNotice('Unable to load farm cloud account.',true);console.warn('Account status unavailable',e);}
}
attach();
// ---------- Text alerts (Twilio) ----------
function smsPayload(){return {location:currentLocation(),calendar:saved('calendar',[])};}
function smsResultText(r){const res=r.results||[];if(!res.length)return r.message||'Nothing to send.';const ok=res.filter(x=>x.sent).length;return ok===res.length?`Sent to ${res.map(x=>x.to).join(', ')}.`:'Not sent: '+(res.find(x=>!x.sent)?.error||'unknown error');}
async function loadSmsStatus(){
  if(farmCloudMode==='sample'){
    state.sms=null;
    $('#sms-badge').textContent='Demo only';
    $('#sms-status').textContent='SIMULATED DEMO · Text alerts and Twilio messaging are disabled. No SMS will be sent.';
    for(const id of ['#sms-link','#sms-test','#sms-alert','#sms-remind'])$(id).disabled=true;
    return;
  }
  try{const s=await api('/api/sms/status');state.sms=s;
  $('#sms-badge').textContent=!s.configured?'Not set up':s.linked_to_me?'● Linked':s.linked?'Linked to another account':'Not linked';
  $('#sms-status').textContent=!s.configured?'Twilio is not configured on the server yet (see TWILIO_SETUP.md).':
    `Texts go to ${s.recipients.join(', ')||'(no number set)'} from ${s.from_number}. `+(s.linked_to_me?`Your farm is linked; ${s.tasks_synced} calendar task(s) synced for automatic evening reminders.`:'Press "Link my farm to texts" so alerts, STATUS and reminders use your farm.');
  $('#sms-link').textContent=s.linked_to_me?'Re-sync farm to texts':'Link my farm to texts';
}catch(e){$('#sms-badge').textContent='Unavailable';$('#sms-status').textContent='Text messages unavailable: '+e.message;}}
function smsSync(){if(state.sms?.linked_to_me)api('/api/sms/sync',{method:'POST',body:smsPayload()}).catch(()=>{});}
async function smsAction(btn,path,body){const b=$(btn),label=b.textContent;b.disabled=true;b.textContent='Sending…';
  try{const r=await api(path,{method:'POST',body:body??{},timeout:25000});showToast(path==='/api/sms/link'?`Farm linked. ${r.tasks_synced} calendar task(s) synced.`:(r.demo?'Demo alert: ':'')+smsResultText(r));await loadSmsStatus();}
  catch(e){showToast(e.message,true);}finally{b.disabled=false;b.textContent=label;}}
function initSms(){
  $('#sms-link').addEventListener('click',()=>smsAction('#sms-link','/api/sms/link',smsPayload()));
  $('#sms-test').addEventListener('click',()=>smsAction('#sms-test','/api/sms/test'));
  $('#sms-alert').addEventListener('click',()=>smsAction('#sms-alert','/api/sms/demo-alert'));
  $('#sms-remind').addEventListener('click',()=>smsAction('#sms-remind','/api/sms/remind-now',smsPayload()));
  loadSmsStatus();
}
loadAccount().then(()=>{
  api('/api/health').then(h=>{state.tigerLive=farmCloudMode!=='sample'&&!!h.tigerdata_configured;}).catch(()=>{});
  initLocations();loadLive();loadSharedDeviceStatus();loadPlan();loadCalendar();loadGeminiStatus();loadGoogleCalendarStatus();initSms();
  const pending=saved('fieldy_calendar_pending');
  if(pending)showFieldyCalendarProposal(pending);
  // No browser-only location writes: location updates are committed atomically to TigerData.
});
// Poll every two seconds ONLY with TigerData. Legacy Vercel Blob must stay
// on the 30-second cadence to protect limited cloud operation quotas.
setInterval(()=>{
  if(state.tab==='live'&&document.visibilityState==='visible'&&
     Date.now()-lastLivePoll >= (state.tigerLive?2000:30000))loadLive();
},2000);
