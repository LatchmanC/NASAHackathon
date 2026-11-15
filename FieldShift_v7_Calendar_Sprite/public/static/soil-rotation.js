/* Cropaganda Soil & Crop Rotation: real USDA soil survey, optional SMAP, reference guide.
   This module shares the existing Auth0-backed api(), account-specific saved()/persist(),
   navigation, crop plan, weather and calendar without changing their storage or tokens. */
'use strict';

const SOIL_CROPS=[
 {id:'corn',name:'Field Corn',emoji:'🌽',family:'Cereal grass',type:'Cash grain',water:'High',soil:'Well-drained soils, adequate fertility and moisture',season:'Warm season',before:'Soybeans or another appropriate legume',after:'Winter cereal rye or another locally suitable cover',benefit:'High-yielding cash grain where water, nutrients and markets support it.',watch:'Water and heat stress near tasseling and silking can be especially costly; scout for pests.',soilTip:'Review drainage and water-holding capacity. Poor drainage and high water demand both deserve attention.',aliases:['maize','field corn','corn']},
 {id:'soybeans',name:'Soybeans',emoji:'🫛',family:'Legume',type:'Cash crop',water:'Moderate',soil:'Well to moderately well drained soils',season:'Warm season',before:'Corn or another non-legume cash crop',after:'Winter cereal rye or winter wheat when locally appropriate',benefit:'Can diversify a grain rotation and biologically fix nitrogen when properly nodulated.',watch:'Nitrogen fixed is not a guaranteed credit for the next crop. Monitor seedling disease and harvest residue.',soilTip:'Check waterlogging risks, pH and inoculation requirements with local extension guidance.',aliases:['soybean','soybeans','soya']},
 {id:'winter_wheat',name:'Winter Wheat',emoji:'🌾',family:'Cereal grass',type:'Overwinter grain',water:'Low–moderate',soil:'Variety-dependent; avoid poorly drained fields during establishment',season:'Fall planted, summer harvested',before:'Legumes or an early-harvest cash crop',after:'Summer cover crop or short-season rotation where climate permits',benefit:'Provides a living crop over winter and can shorten exposure of bare soil.',watch:'Check overwintering, seeding window, disease, and herbicide carryover.',soilTip:'Survey drainage and field trafficability before fall establishment.',aliases:['wheat','winter wheat']},
 {id:'sorghum',name:'Grain Sorghum',emoji:'🌾',family:'Cereal grass',type:'Drought-tolerant grain',water:'Relatively low',soil:'Well-drained soils; warm-season establishment',season:'Warm season',before:'Legume or an appropriate fallow/cover rotation',after:'Winter cover crop if moisture allows',benefit:'Can offer an alternative to corn in some warmer, water-limited systems.',watch:'Check local grain buyers, stand establishment and sorghum aphid pressure.',soilTip:'Consider regional temperature and crop maturity windows in addition to moisture.',aliases:['sorghum','milo']},
 {id:'chickpeas',name:'Chickpeas',emoji:'🫘',family:'Legume',type:'Pulse cash crop',water:'Low–moderate',soil:'Well-drained soil; poor fit for prolonged waterlogging',season:'Region-dependent',before:'Non-legume cereal rotation',after:'Winter cereal or cover crop where disease rotation permits',benefit:'Diversifies crop families and can fix atmospheric nitrogen under suitable conditions.',watch:'Sensitive to waterlogging; moisture and local fungal disease pressure need monitoring.',soilTip:'If USDA identifies poor drainage, flag chickpeas for additional field verification.',aliases:['chickpea','garbanzo']},
 {id:'alfalfa',name:'Alfalfa',emoji:'☘️',family:'Perennial legume',type:'Forage',water:'Moderate–high',soil:'Deep, well-drained soils; pH and fertility important',season:'Multi-year perennial',before:'Cash grain or forage renovation',after:'Grain crop after planned stand termination',benefit:'Deep-rooted perennial ground cover, forage production and biological nitrogen fixation.',watch:'Water requirements can be substantial; establishment and local forage markets matter.',soilTip:'Check drainage, field pH, root-depth restrictions and irrigation availability.',aliases:['alfalfa']},
 {id:'crimson_clover',name:'Crimson Clover + Radish',emoji:'🌺',family:'Legume + brassica mix',type:'Winter cover crop',water:'Cool-season',soil:'Locally adapted fields with suitable establishment window',season:'Fall through spring',before:'After summer cash-crop harvest',after:'Plant following crop after correct cover termination',benefit:'Can provide seasonal living cover, nutrient cycling and rotational diversity.',watch:'Termination timing, frost survival, seed cost and herbicide plant-back restrictions vary.',soilTip:'Mixes need species- and field-specific seeding recommendations.',aliases:['clover','radish','crimson']},
 {id:'cereal_rye',name:'Winter Cereal Rye',emoji:'🌱',family:'Cereal grass',type:'Winter cover crop',water:'Cool-season',soil:'Adaptable to many soils; locally verify',season:'Fall through spring',before:'Following summer grain or vegetable harvest',after:'Cash crop after termination and moisture check',benefit:'Maintains winter soil cover and can reduce erosion exposure and nutrient losses.',watch:'In a dry spring, growth may use water needed by the next crop; termination management matters.',soilTip:'Plan termination before the next crop using local conditions, equipment and herbicide label.',aliases:['cereal rye','winter rye','rye']}
];
const soilState={profile:null,smap:null,context:null,loading:false,loadedKey:null,lastLoaded:0,pane:'overview',crop:'corn',mapZoom:0};
const soilEl=sel=>document.querySelector(sel);
function soilTag(text){return html(text??'—');}
function soilNum(value,digits=1,suffix=''){return value===null||value===undefined||!Number.isFinite(+value)?'—':Number(value).toFixed(digits)+suffix;}
function soilSavedLocation(){
 const loc=saved('location');
 if(!loc||!Number.isFinite(Number(loc.latitude))||!Number.isFinite(Number(loc.longitude))||/^(Demo|Test Farm)\b/i.test(loc.label||''))return null;
 return loc;
}
function soilOpenPane(name){
 if(!['overview','map','context','crops','rotation'].includes(name))name='overview';
 soilState.pane=name;
 document.querySelectorAll('.soil-pane').forEach(p=>p.classList.toggle('hidden',p.id!=='soil-pane-'+name));
 document.querySelectorAll('.soil-subtab').forEach(b=>{const active=b.dataset.soilPane===name;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
 if(name==='map')soilRenderMaps();
 if(name==='context')soilShowContext(soilState.context);
 if(name==='crops')soilRenderCropGuide();
 if(name==='rotation')soilRenderRotation();
}
function soilShowUsda(data){
 const profile=data?.status==='ok'?data.profile:null;
 soilEl('#soil-usda-state').textContent=data?.message||'Select a farm location to look up USDA soil surveys.';
 soilEl('#soil-usda-state').classList.toggle('warn',!profile);
 soilEl('#soil-metric-texture').textContent=profile?.texture||'—';
 soilEl('#soil-metric-texture-note').textContent=profile?.selection_reason==='rated_alternative'?'Secondary mapped component · '+(profile.mapunit_name||'USDA map unit'):(profile?.mapunit_name||'Not available for the selected point');
 soilEl('#soil-metric-drainage').textContent=profile?(profile.drainage_class||'Not rated'):'—';
 const details=profile?[
  ['Map unit',profile.mapunit_name],['Soil component',profile.component],
  ['Component selection',profile.selection_reason==='rated_alternative'?'Rated secondary component (dominant: '+(profile.dominant_component||'unrated')+')':'Dominant map-unit component'],
  ['Component coverage',soilNum(profile.component_pct,0,'% of unit')],
  ['Surface texture',profile.texture],
  ['Drainage class',profile.drainage_class||'Not rated'],['Survey slope',soilNum(profile.slope_pct,1,'%')],
  ['Organic matter (survey)',soilNum(profile.organic_matter_pct,1,'%')],
  ['Survey pH (not ESP32)',soilNum(profile.ph_water,1)],
  ['Depth of sampled horizon',profile.depth_top_cm==null||profile.depth_bottom_cm==null?'—':profile.depth_top_cm+'–'+profile.depth_bottom_cm+' cm'],
  ['Hydrologic soil group',profile.hydrologic_group],
  ['Available water capacity',soilNum(profile.available_water_cm_per_cm,3,' cm/cm')],
  ['Clay / silt / sand',profile.clay_pct==null?'—':[soilNum(profile.clay_pct,0),soilNum(profile.silt_pct,0),soilNum(profile.sand_pct,0)].join(' / ')+' %']
 ]:[];
 soilEl('#soil-profile-fields').innerHTML=details.map(([name,value])=>'<div class="soil-attr"><span>'+soilTag(name)+'</span><strong>'+soilTag(value)+'</strong></div>').join('')||'<div class="soil-chart-empty">No confirmed soil attributes were returned.</div>';
 soilEl('#soil-map-attributes').innerHTML=(profile?[
 ['Map unit key',profile.mapunit_key],['Map unit name',profile.mapunit_name],['Survey area',profile.survey_area],['Dominant component',profile.component]
 ]:[]).map(([name,val])=>'<div class="soil-attr"><span>'+soilTag(name)+'</span><strong>'+soilTag(val)+'</strong></div>').join('');
 soilRenderContext();
 soilRenderRotation();
}
function soilGraph(series){
 if(!series.length)return '<div class="soil-chart-empty">No quality-passing SMAP observations for the last 30 days.</div>';
 const width=540,height=172,left=42,right=12,top=13,bottom=27;
 const values=series.map(x=>x.soil_moisture_m3_m3);
 const min=Math.max(0,Math.min(...values)-.035),max=Math.min(1,Math.max(...values)+.035);
 const den=Math.max(.02,max-min);
 const x=i=>left+(i/(Math.max(1,series.length-1)))*(width-left-right);
 const y=v=>top+(1-(v-min)/den)*(height-top-bottom);
 const path=series.map((p,i)=>(i?'L':'M')+x(i).toFixed(1)+','+y(p.soil_moisture_m3_m3).toFixed(1)).join(' ');
 const first=series[0],last=series[series.length-1];
 return '<svg class="soil-chart" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="Quality-passing SMAP surface moisture samples by date">'+
   [0,.5,1].map(f=>{const v=min+(max-min)*f;const pos=y(v);return '<line x1="'+left+'" y1="'+pos+'" x2="'+(width-right)+'" y2="'+pos+'" stroke="#e5ebe4" />'+
   '<text x="1" y="'+(pos+4)+'" font-size="11" fill="#849588">'+(v*100).toFixed(0)+'%</text>';}).join('')+
   '<path d="'+path+'" fill="none" stroke="#2e8658" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'+
   series.map((p,i)=>'<circle cx="'+x(i)+'" cy="'+y(p.soil_moisture_m3_m3)+'" r="3" fill="#3b9b66"><title>'+p.date+': '+(p.soil_moisture_m3_m3*100).toFixed(1)+'% volumetric</title></circle>').join('')+
   '<text x="'+left+'" y="'+(height-5)+'" fill="#849588" font-size="10">'+first.date+'</text>'+
   '<text x="'+(width-right)+'" y="'+(height-5)+'" fill="#849588" font-size="10" text-anchor="end">'+last.date+'</text></svg>'+
   '<div class="soil-chart-caption"><span>AM overpass · volumetric m³/m³ shown as percentage</span><span>Latest '+last.date+'</span></div>';
}
function soilShowSmap(data){
 const latest=data?.status==='ok'?data.latest:null;
 soilEl('#soil-metric-smap').textContent=latest?soilNum(latest.soil_moisture_m3_m3*100,1,'% vol.'):'—';
 soilEl('#soil-metric-smap-date').textContent=latest?'Observed '+latest.date+' · quality checked':data?.status==='setup_required'?'Earth Engine connection not configured':'No satellite reading available';
 soilEl('#soil-smap-state').textContent=data?.message||'No SMAP data available.';
 soilEl('#soil-smap-state').classList.toggle('warn',!latest);
 soilEl('#soil-smap-chart').innerHTML=data?.status==='ok'?soilGraph(data.readings||[]):'<div class="soil-chart-empty">'+soilTag(data?.message||'Satellite sampling unavailable.')+'</div>';
 soilRenderContext();
 soilRenderRotation();
}

function soilAttrRows(rows){
 return rows.filter(([,v])=>v!==null&&v!==undefined&&v!=='').map(([k,v])=>
  '<div class="soil-attr"><span>'+soilTag(k)+'</span><strong>'+soilTag(v)+'</strong></div>').join('');
}
function soilShowContext(data){
 const c=data?.climate||{},t=data?.terrain||{},w=data?.water||{},p=data?.prism_reference||{},cdl=data?.land_cover||{};
 const msg=(item, fallback)=>item?.status==='ok'?'Verified provider response · '+(item.source||'public source'):
  (item?.message||fallback);
 const set=(selector,value)=>{const el=soilEl(selector);if(el)el.innerHTML=value;};
 const setText=(selector,value)=>{const el=soilEl(selector);if(el)el.textContent=value;};
 setText('#soil-climate-status',msg(c,'No climate data loaded.'));
 set('#soil-climate-fields',soilAttrRows([
  ['Annual mean temperature',soilNum(c.annual_mean_air_temp_c,1,' °C')],
  ['July mean daily maximum',soilNum(c.july_max_temp_c,1,' °C')],
  ['Mean daily precipitation',soilNum(c.annual_average_precip_mm_day,2,' mm/day')],
  ['Annualized precipitation',soilNum(c.annual_equivalent_precip_mm,0,' mm')],
  ['Mean daily solar radiation',soilNum(c.mean_solar_radiation_mj_m2_day,2,' MJ/m²')],
  ['Relative humidity',soilNum(c.relative_humidity_pct,1,'%')],
  ['Pressure',soilNum(c.surface_pressure_kpa,1,' kPa')]
 ].filter(([k,v])=>c.status==='ok'&&v!=='—'&&!v.startsWith('— '))));
 setText('#soil-terrain-status',msg(t,'No terrain data loaded.'));
 set('#soil-terrain-fields',soilAttrRows(t.status==='ok'?[
   ['Elevation',soilNum(t.elevation_m,1,' m')],
   ['Northward slope transect',soilNum(t.northward_transect_slope_pct,1,'%')],
   ['Interpretation','One-direction terrain estimate, not USDA drainage']
 ]:[]));
 setText('#soil-water-status',msg(w,'No USGS water gauge data loaded.'));
 set('#soil-water-fields',soilAttrRows(w.status==='ok'?[
  ['Nearby reporting gauges',w.station_count],
  ...((w.readings||[]).slice(0,4).map(r=>[(r.station||'Gauge')+' · '+(r.parameter||'reading'),soilNum(r.value,2,' '+(r.unit||''))]))
 ]:[]));
 setText('#soil-cdl-status',cdl.status==='ok'?'USDA Cropland Data Layer 30 m classifications; maps land cover, not exact farm cropping history.':(cdl.message||'USDA CDL sampling unavailable or not yet connected.'));
 set('#soil-cdl-fields',soilAttrRows((cdl.samples||[]).map(x=>
   [String(x.year)+' land cover',x.status==='ok'?(x.land_cover+' · code '+x.code):x.status==='unavailable'?'Provider unavailable':'No classification reported'])));
 setText('#soil-prism-status',p.status==='reference_only'?
  'Historical PRISM grid sample near '+p.location_name+', '+p.distance_from_farm_km+' km from selected point; NOT a farm observation.':
  p.message||'PRISM archive point not available near this location.');
 set('#soil-prism-fields',soilAttrRows(p.status==='reference_only'?[
  ['Reference location',p.location_name],
  ['2022 precipitation',soilNum(p.year_2022?.precip_mm,0,' mm')],
  ['2022 annual mean temperature',soilNum(p.year_2022?.mean_temp_c,1,' °C')],
  ['2022 mean maximum',soilNum(p.year_2022?.max_temp_c,1,' °C')],
  ['2022 mean minimum',soilNum(p.year_2022?.min_temp_c,1,' °C')],
  ['2022 dew point',soilNum(p.year_2022?.dewpoint_c,1,' °C')],
  ['2022 solar total',soilNum(p.year_2022?.solar_total_mj_m2_day,1,' MJ/m²/day')],
  ['2022 sloped solar radiation',soilNum(p.year_2022?.solar_slope_mj_m2_day,1,' MJ/m²/day')],
  ['2016 mean minimum',soilNum(p.year_2016?.min_temp_c,1,' °C')],
  ['2016 mean maximum',soilNum(p.year_2016?.max_temp_c,1,' °C')],
  ['2016 dew point',soilNum(p.year_2016?.dewpoint_c,1,' °C')],
  ['2016 sloped solar radiation',soilNum(p.year_2016?.solar_slope_mj_m2_day,1,' MJ/m²/day')]
 ]:[]));
 const sourceList=(data?.other_sources||[]);
 set('#soil-other-sources',sourceList.map(row=>
  '<div class="soil-attr"><span>'+soilTag(row.name)+' · '+soilTag(row.status.replaceAll('_',' '))+'</span>'+
  '<strong>'+(row.url?'<a href="'+encodeURI(row.url)+'" target="_blank" rel="noopener noreferrer">Official source ↗</a>':soilTag(row.note))+'</strong></div>').join(''));
}

function soilRenderContext(){
 const selected=(saved('plan')?.crops||[]).filter(c=>String(c?.name||'').trim()).slice(0,4);
 const p=soilState.profile?.status==='ok'?soilState.profile.profile:null;
 const m=soilState.smap?.status==='ok'?soilState.smap.latest:null;
 const climate=soilState.context?.climate;
 const land=soilState.context?.land_cover;
 const recentCdl=land?.samples?.find(r=>r.status==='ok');
 const details=[
  p?{title:'Published map unit',description:p.mapunit_name||'USDA map unit'}:{title:'Soil survey',description:'No confirmed USDA map-unit attributes loaded'},
  m?{title:'SMAP regional context',description:'Last quality-passing surface moisture sample: '+soilNum(m.soil_moisture_m3_m3*100,1,'% volume')+' ('+m.date+')'}:{title:'Satellite moisture',description:'Not yet available; no estimates substituted'},
  climate?.status==='ok'?{title:'Historical regional climate',description:'NASA POWER mean air temperature '+soilNum(climate.annual_mean_air_temp_c,1,' °C')+'; annualized precipitation '+soilNum(climate.annual_equivalent_precip_mm,0,' mm')+'. Not current weather.'}:{title:'Historical regional climate',description:'NASA POWER regional climatology not available'},
  recentCdl?{title:'USDA classified land cover',description:recentCdl.year+' · '+recentCdl.land_cover+' (30 m pixel, not confirmed planted crop).'}:{title:'USDA classified land cover',description:'No verified map-classification response available'}
 ];
 soilEl('#soil-crop-context').innerHTML='<div class="soil-crop-context">'+details.map(d=>'<div class="soil-context-item"><strong>'+soilTag(d.title)+'</strong>'+soilTag(d.description)+'</div>').join('')+'</div>'+
 (selected.length?'<p class="soil-note">Your crops: '+selected.map(c=>soilTag(c.name)).join(', ')+'. Explore the Crop Guide to compare their general requirements with the actual published soil properties above.</p>':
 '<p class="soil-note">No farm crops saved yet. Add them under My Farm before planning rotations.</p>');
}
function soilRenderMaps(){
 const loc=soilSavedLocation(),img=soilEl('#soil-map-image'),iframe=soilEl('#soil-osm');
 if(!loc){
  img.removeAttribute('src');iframe.removeAttribute('src');
  soilEl('#soil-map-notice').textContent='Save an actual farm location in My Farm to view a soil map.';
  return;
 }
 const lat=Number(loc.latitude),lon=Number(loc.longitude),d=.025*Math.pow(2,-soilState.mapZoom);
 if(soilState.mapZoom< -3)soilState.mapZoom=-3;
 if(soilState.mapZoom>4)soilState.mapZoom=4;
 const bb=[lon-d,lat-d,lon+d,lat+d];
 const soilParams=new URLSearchParams({SERVICE:'WMS',VERSION:'1.1.1',REQUEST:'GetMap',LAYERS:'MapunitPoly',STYLES:'',SRS:'EPSG:4326',BBOX:bb.map(x=>x.toFixed(5)).join(','),WIDTH:'850',HEIGHT:'530',FORMAT:'image/png',TRANSPARENT:'FALSE'});
 img.src='https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDM.wms?'+soilParams;
 img.onerror=()=>{soilEl('#soil-map-notice').textContent='USDA WMS map image is unavailable. Use the official Web Soil Survey link or retry later.';};
 img.onload=()=>{soilEl('#soil-map-notice').textContent='USDA mapped soil polygons at approximately '+Math.round(d*111*2)+' km across. Zoom to inspect published map boundaries.';};
 const radius=.035;
 const osmBounds=[lon-radius,lat-radius,lon+radius,lat+radius].map(x=>x.toFixed(5)).join('%2C');
 iframe.src='https://www.openstreetmap.org/export/embed.html?bbox='+osmBounds+'&layer=mapnik&marker='+encodeURIComponent(lat+','+lon);
 soilEl('#soil-map-location').textContent='Location: '+(loc.label||'Saved farm')+' ('+lat.toFixed(4)+', '+lon.toFixed(4)+'). These maps are not a surveyed field boundary.';
}
function soilRenderCropGuide(){
 const q=(soilEl('#soil-crop-search').value||'').trim().toLowerCase();
 const list=SOIL_CROPS.filter(c=>[c.name,c.family,c.type,c.benefit,c.water].some(x=>x.toLowerCase().includes(q)));
 soilEl('#soil-crop-library').innerHTML=list.map(c=>'<button type="button" class="soil-crop-option'+(soilState.crop===c.id?' active':'')+'" data-crop-id="'+c.id+'"><span class="emoji">'+c.emoji+'</span><strong>'+soilTag(c.name)+'</strong><small>'+soilTag(c.type)+'</small></button>').join('')||'<p class="soil-note">No matching crops in this reference library.</p>';
 const crop=SOIL_CROPS.find(c=>c.id===soilState.crop)||SOIL_CROPS[0];
 const p=soilState.profile?.status==='ok'?soilState.profile.profile:null;
 const site=p?'<div class="soil-explainer"><strong>Farm soil context:</strong> Published USDA map unit '+soilTag(p.mapunit_name||'—')+'; drainage '+soilTag(p.drainage_class||'not provided')+'. '+soilTag(crop.soilTip)+' This is not a verified crop-suitability result.</div>':
 '<div class="soil-explainer">Site-specific assessment is unavailable until the official USDA soil profile is retrieved. Crop descriptions remain general guidance.</div>';
 soilEl('#soil-crop-detail').innerHTML='<div class="soil-crop-detail-header"><span>'+crop.emoji+'</span><div><h2>'+soilTag(crop.name)+'</h2><p>'+soilTag(crop.family)+' · '+soilTag(crop.season)+'</p></div></div>'+
 '<div class="soil-crop-info"><div><h3>Growing requirements</h3><p><b>Water:</b> '+soilTag(crop.water)+'</p><p><b>Typical soil:</b> '+soilTag(crop.soil)+'</p></div>'+
 '<div><h3>Rotation opportunities</h3><p><b>Follow:</b> '+soilTag(crop.before)+'</p><p><b>Follow with:</b> '+soilTag(crop.after)+'</p></div>'+
 '<div><h3>Benefits and watch-outs</h3><p>'+soilTag(crop.benefit)+'</p><p>'+soilTag(crop.watch)+'</p></div></div>'+
 '<div style="margin-top:18px">'+site+'</div>';
}
function soilFirstCrop(name){
 const s=String(name||'').toLowerCase();
 return SOIL_CROPS.find(c=>c.aliases.some(alias=>s.includes(alias)))||null;
}
function soilPopulateCrops(){
 const box=soilEl('#soil-current-crop'),selected=box.value;
 const fromFarm=(saved('plan')?.crops||[]).map(c=>String(c.name||'').trim()).filter(Boolean);
 const all=[...new Set([...fromFarm,...SOIL_CROPS.filter(c=>c.type!=='Winter cover crop').map(c=>c.name)])];
 box.replaceChildren(...all.map(name=>new Option(name,name)));
 if(all.includes(selected))box.value=selected;
}
let soilSuggestedPlan=null;
function soilRenderRotation(){
 const box=soilEl('#soil-current-crop');
 const current=box.value||'Field Corn',base=soilFirstCrop(current);
 const goal=soilEl('#soil-rotation-goal').value;
 const climate=soilState.context?.climate;
 const p=soilState.profile?.status==='ok'?soilState.profile.profile:null;
 const poorlyDrained=/poorly|very poorly/i.test(p?.drainage_class||'');
 const next=goal==='water'?'sorghum':goal==='cover'?'soybeans':'chickpeas';
 let nextCrop=SOIL_CROPS.find(c=>c.id===next);
 if(poorlyDrained&&next==='chickpeas')nextCrop=SOIL_CROPS.find(c=>c.id==='soybeans');
 if(nextCrop?.id===base?.id)nextCrop=SOIL_CROPS.find(c=>c.id==='winter_wheat');
 const cover=goal==='cover'&&!poorlyDrained?'crimson_clover':'cereal_rye';
 const coverCrop=SOIL_CROPS.find(c=>c.id===cover);
 const main={name:current,emoji:base?.emoji||'🌱',phase:'Current crop',description:'Existing farm crop — details from your saved plan or selection'};
 const midway={name:coverCrop.name,emoji:coverCrop.emoji,phase:'Between crops (where season allows)',description:'Consider local planting and termination windows'};
 const final={name:nextCrop.name,emoji:nextCrop.emoji,phase:'Potential next cash/forage crop',description:'Candidate to verify with local climate, markets and soil test'};
 soilSuggestedPlan={steps:[main,midway,final],goal,location:soilSavedLocation()?.label||null,generated_at:new Date().toISOString()};
 soilEl('#soil-rotation-preview').innerHTML=soilSuggestedPlan.steps.map(x=>'<div class="soil-step"><span class="emoji">'+x.emoji+'</span><small>'+soilTag(x.phase)+'</small><strong>'+soilTag(x.name)+'</strong><p>'+soilTag(x.description)+'</p></div>').join('');
 const notes=[
  goal==='water'?'Drought-resilience priority: evaluate sorghum or another regionally suitable lower-water option; rotation success depends on planting temperature and market access.':
  goal==='cover'?'Soil-cover priority: evaluate living cover between cash crops, considering spring water use and termination timing.':
  'Crop-family diversity priority: consider a different crop family, with disease break, buyer, and drainage constraints.',
  poorlyDrained?'USDA lists poor drainage for the mapped component; chickpeas are not suggested without site verification.':
  p?'Published USDA survey shows '+(p.drainage_class||'unspecified drainage')+' drainage for the selected component.':
  'No USDA soil survey is loaded; the candidate sequence is general guidance only.',
  soilState.smap?.latest?'NASA SMAP is regional 9 km surface moisture; do not interpret it as water available to plant roots.':
  'No quality-passing SMAP values are used for this suggestion.',
  climate?.status==='ok'?'NASA POWER historical regional averages: annual temperature '+soilNum(climate.annual_mean_air_temp_c,1,' °C')+' and annualized precipitation '+soilNum(climate.annual_equivalent_precip_mm,0,' mm')+'. Use local seasonal planting windows; these are not farm forecasts.':'NASA POWER historical climate is currently unavailable; the sequence is reference guidance.',
  'No yield, economic return, nitrogen credit, erosion reduction, or crop-fit percentage is predicted.'
 ];
 soilEl('#soil-rotation-reason').innerHTML=notes.map(x=>'<p>'+soilTag(x)+'</p>').join('');
 const savedPlans=saved('rotation_scenarios',[]);
 soilEl('#soil-rotation-saved').textContent=Array.isArray(savedPlans)&&savedPlans.length?'Saved rotation drafts in this browser: '+savedPlans.length:'No rotation drafts saved yet.';
}
function soilSaveRotation(){
 if(!soilSuggestedPlan)return;
 if(!confirm('Save this rotation as a draft in your browser? This does not create calendar events or change your farm plan.'))return;
 const previous=saved('rotation_scenarios',[]);
 const drafts=Array.isArray(previous)?previous:[];
 if(drafts.length>=30){showToast('Up to 30 saved rotation drafts are supported.',true);return;}
 persist('rotation_scenarios',[...drafts,{...soilSuggestedPlan,id:crypto.randomUUID()}]);
 soilRenderRotation();showToast('Rotation draft saved. Farm calendar was not changed.');
}
async function soilLoad(force=false){
 if(soilState.loading)return;
 const loc=soilSavedLocation();
 if(!loc){
  soilEl('#soil-location').textContent='No saved farm location. Open My Farm to select your farm.';
  soilShowUsda({status:'no_location',message:'Select your actual farm location in My Farm to request USDA soil properties.'});
  soilShowSmap({status:'no_location',message:'SMAP needs a farm coordinate to locate regional satellite observations.'});
  soilShowContext({});
  soilRenderMaps();return;
 }
 const key=loc.latitude+','+loc.longitude;
 if(!force&&soilState.loadedKey===key&&Date.now()-soilState.lastLoaded<3600000)return;
 soilState.loading=true;
 soilState.loadedKey=key;
 soilEl('#soil-refresh').disabled=true;
 soilEl('#soil-location').textContent='Saved farm · '+(loc.label||Number(loc.latitude).toFixed(4)+', '+Number(loc.longitude).toFixed(4));
 soilEl('#soil-usda-state').textContent='Querying the USDA Soil Data Mart…';
 soilEl('#soil-smap-state').textContent='Checking NASA SMAP sampling…';
 const qs='latitude='+encodeURIComponent(loc.latitude)+'&longitude='+encodeURIComponent(loc.longitude)+(force?'&refresh=true':'');
 try{
  const [usda,smap,context]=await Promise.allSettled([api('/api/soil/profile?'+qs,{timeout:52000}),api('/api/soil/smap?'+qs,{timeout:57000}),api('/api/soil/context?'+qs,{timeout:58000})]);
  if(soilSavedLocation()&&key!==soilSavedLocation().latitude+','+soilSavedLocation().longitude)return;
  soilState.profile=usda.status==='fulfilled'?usda.value:{status:'unavailable',message:'USDA soil profile request failed. No values were inferred.'};
  soilState.smap=smap.status==='fulfilled'?smap.value:{status:'unavailable',message:'SMAP request failed. No satellite values were inferred.'};
  soilState.context=context.status==='fulfilled'?context.value:{status:'unavailable',message:'Source-context request failed. No climate or terrain data were inferred.'};
  // Retry failed upstream requests after one minute, not the normal one-hour UI interval.
  const retrySoon=[soilState.profile,soilState.smap,soilState.context].some(x=>x?.status==='unavailable');
  soilState.lastLoaded=Date.now()-(retrySoon?3540000:0);
  soilEl('#soil-source-time').textContent='Source check · '+new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
  soilShowUsda(soilState.profile);
  soilShowSmap(soilState.smap);
  soilShowContext(soilState.context);
  soilRenderMaps();
 }finally{soilState.loading=false;soilEl('#soil-refresh').disabled=false;}
}
function soilInit(){
 soilPopulateCrops();
 soilRenderCropGuide();
 soilRenderContext();
 soilOpenPane(soilState.pane);
 if(!soilEl('#account-box').textContent.includes('Signed in:'))return;
 soilLoad();
}
const soilBeforeTab=tab;
tab=function(name){soilBeforeTab(name);if(name==='soil')soilInit();};
document.querySelectorAll('.soil-subtab').forEach(button=>button.addEventListener('click',()=>soilOpenPane(button.dataset.soilPane)));
document.addEventListener('click',e=>{
 const btn=e.target.closest('[data-soil-pane-go]');
 if(btn){soilOpenPane(btn.dataset.soilPaneGo);return;}
 const crop=e.target.closest('[data-crop-id]');
 if(crop){soilState.crop=crop.dataset.cropId;soilRenderCropGuide();}
});
soilEl('#soil-crop-search').addEventListener('input',soilRenderCropGuide);
soilEl('#soil-current-crop').addEventListener('change',soilRenderRotation);
soilEl('#soil-rotation-goal').addEventListener('change',soilRenderRotation);
soilEl('#soil-save-rotation').addEventListener('click',soilSaveRotation);
soilEl('#soil-refresh').addEventListener('click',()=>soilLoad(true));
soilEl('#soil-map-zoom-in').addEventListener('click',()=>{soilState.mapZoom=Math.min(4,soilState.mapZoom+1);soilRenderMaps();});
soilEl('#soil-map-zoom-out').addEventListener('click',()=>{soilState.mapZoom=Math.max(-3,soilState.mapZoom-1);soilRenderMaps();});
const soilAccountObserver=new MutationObserver(()=>{
 if(state.tab==='soil'&&soilEl('#account-box').textContent.includes('Signed in:'))soilInit();
});
soilAccountObserver.observe(soilEl('#account-box'),{childList:true,subtree:true});
// Farm plan/location changes already run through the shared persist() wrapper.
const soilOldPersist=persist;
persist=function(key,value){
 soilOldPersist(key,value);
 if(key==='plan'&&state.tab==='soil'){soilPopulateCrops();soilRenderContext();soilRenderRotation();}
 if(key==='location'){
  soilState.loadedKey=null;soilState.profile=null;soilState.smap=null;soilState.context=null;soilState.lastLoaded=0;
  if(state.tab==='soil')soilLoad(true);
 }
};
if(state.tab==='soil')soilInit();
