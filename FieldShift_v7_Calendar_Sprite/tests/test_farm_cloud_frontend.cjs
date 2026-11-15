/* node:test regression checks for the exact sync functions shipped in app.js. */
'use strict';
const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../public/static/app.js'),'utf8');

function functionSlice(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a+1);
  assert.ok(a>=0 && b>a,'Could not locate '+start);
  return source.slice(a,b);
}
const importedSource=functionSlice('async function autoImportLegacyFarm(){','function farmCloudLocationLabels(){');
const refreshingSource=functionSlice('async function refreshFarmCloud(force=false){','async function importBrowserFarmData(){');

function buildImportContext({candidates={},ack=false,failed=[]}={}){
  const storage=new Map();
  if(ack)storage.set('farm_cloud_import_ack','true');
  const log=[];
  const ctx={
    storage,log,
    legacyValue:(key,fallback=null)=>storage.has(key)?JSON.parse(storage.get(key)):fallback,
    browserImportCandidates:()=>candidates,
    farmCloudSections:{},
    api:async(url,opts)=>{
      assert.equal(url,'/api/farm/import');
      const key=Object.keys(opts.body.sections)[0];
      log.push(key);
      if(failed.includes(key))throw Error('Invalid '+key);
      return {sections:{[key]:{value:opts.body.sections[key],revision:1,present:true}},
              results:{[key]:{action:'imported'}}};
    },
    localStorage:{setItem:(key,value)=>storage.set(key,value)},
    fsKey:(key)=>key
  };
  vm.createContext(ctx);
  vm.runInContext(importedSource+'\nthis.runImport=autoImportLegacyFarm;this.changed=farmSectionChanged;',ctx);
  return ctx;
}

test('auto-import prioritizes the calendar, then other farm documents',async()=>{
  const ctx=buildImportContext({candidates:{
    plan:{total_area:1},calendar:[{id:'original-task'}],location:{latitude:42,longitude:-76}
  }});
  const result=await ctx.runImport();
  assert.equal(result.imported,3);
  assert.deepEqual(ctx.log,['calendar','plan','location']);
  assert.equal(ctx.legacyValue('farm_cloud_import_ack'),true);
  assert.equal(ctx.legacyValue('farm_cloud_auto_imported_v1').calendar,true);
});

test('previously imported or skipped data is not automatically re-imported',async()=>{
  const ctx=buildImportContext({candidates:{calendar:[{id:'old-task'}]},ack:true});
  const r=await ctx.runImport();
  assert.equal(r.skipped,true);
  assert.equal(ctx.log.length,0);
});

test('failed legacy plan cannot block calendar and successful section is never retried',async()=>{
  const ctx=buildImportContext({candidates:{
    plan:{old:true},calendar:[{id:'real-task'}]
  },failed:['plan']});
  const first=await ctx.runImport();
  assert.equal(first.imported,1);
  assert.deepEqual(ctx.log,['calendar','plan']);
  assert.equal(ctx.legacyValue('farm_cloud_import_ack'),null);
  const second=await ctx.runImport();
  assert.equal(second.imported,0);
  assert.deepEqual(ctx.log,['calendar','plan','plan']);
});

test('revisions and payload updates trigger a refresh; identical rows do not',()=>{
  const ctx=buildImportContext();
  const a={revision:1,present:true,value:[{id:'a'}]};
  assert.equal(ctx.changed(a,{revision:1,present:true,value:[{id:'a'}]}),false);
  assert.equal(ctx.changed(a,{revision:2,present:true,value:[{id:'a'}]}),true);
  assert.equal(ctx.changed(a,{revision:1,present:true,value:[{id:'b'}]}),true);
});

function buildRefreshContext({dirtyPlan=false,busy=0,sections,remote}={}){
  const calls=[];
  const ctx={calls,
    api:async(url)=>{
      calls.push('get');
      assert.equal(url,'/api/farm/state');
      return {sections:remote};
    },
    cloudNotice:(message,isError)=>calls.push({message,isError}),
    loadPlan:async()=>calls.push('plan'),
    loadCalendar:async()=>calls.push('calendar'),
    initLocations:async()=>calls.push('location'),
    smsSync:()=>calls.push('sms'),
    farmCloudLocationLabels:()=>calls.push('labels'),
    farmKeys:['plan','location','calendar','rotation_scenarios'],
    farmCloudSections:sections,
    state:{tab:'crops'},
  };
  vm.createContext(ctx);
  vm.runInContext(
    'let farmCloudRefreshing=false;let farmCloudBusy='+busy+
    ';let farmCloudMode="ready";let farmCloudLastChecked=0;'+
    'let farmPlanDirty='+dirtyPlan+';let farmLocationDirty=false;\n'+
    'function farmSectionChanged(a,b){return (a?.revision||0)!==(b?.revision||0) || Boolean(a?.present)!==Boolean(b?.present) || JSON.stringify(a?.value??null)!==JSON.stringify(b?.value??null);}\n'+
    refreshingSource+
    '\nthis.runRefresh=refreshFarmCloud;this.getSections=()=>farmCloudSections;',ctx
  );
  return ctx;
}

test('background refresh loads changed calendar but preserves unsaved plan edits',async()=>{
  const old={
    plan:{revision:1,present:true,value:{notes:'previous'}},
    calendar:{revision:1,present:true,value:[{id:'a'}]},
    location:{revision:0,present:false,value:null},
    rotation_scenarios:{revision:0,present:false,value:null}
  };
  const latest={
    ...old,
    plan:{revision:2,present:true,value:{notes:'another device'}},
    calendar:{revision:2,present:true,value:[{id:'a'},{id:'b'}]}
  };
  const ctx=buildRefreshContext({dirtyPlan:true,sections:old,remote:latest});
  await ctx.runRefresh(true);
  assert.equal(ctx.getSections().plan.revision,1);
  assert.equal(ctx.getSections().calendar.revision,2);
  assert.ok(ctx.calls.includes('calendar'));
  assert.ok(!ctx.calls.includes('plan'));
  assert.equal(ctx.calls.some(v=>v.isError&&v.message.includes('unsaved edits')),true);
});

test('fresh auto-refresh is skipped when another cloud write is active',async()=>{
  const old={plan:{revision:1,present:true,value:{notes:'old'}}};
  const ctx=buildRefreshContext({busy:1,sections:old,remote:old});
  await ctx.runRefresh(true);
  assert.ok(!ctx.calls.includes('get'));
});
