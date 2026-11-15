/* Browser calendar sync tests using isolated functions from the shipped app.js. */
'use strict';
const assert=require('node:assert/strict');
const test=require('node:test');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.resolve(__dirname,'../public/static/app.js'),'utf8');
function slice(start,end){
  const i=source.indexOf(start),j=source.indexOf(end,i+start.length);
  assert.ok(i>=0&&j>i,'Could not locate '+start+' or '+end);
  return source.slice(i,j);
}
const migrateFn=slice('async function migrateLegacyCalendarOnce(){','async function loadFarmCloud(){');
const loadFn=slice('async function loadCalendar(){','async function addCalendarEvent(e){');

function migrationContext({legacy=[],ack=false,migrated=false,fail=false}={}){
  const values=new Map();
  if(ack)values.set('farm_cloud_import_ack','true');
  if(migrated)values.set('calendar_tigerdata_imported_v1','true');
  values.set('calendar',JSON.stringify(legacy));
  const posted=[];
  const ctx={
    fsKey:k=>'auth_a_'+k,
    legacyValue:(key,defaultValue=null)=>{
      const value=values.get(key);
      return value===undefined?defaultValue:JSON.parse(value);
    },
    localStorage:{setItem:(key,value)=>values.set(key.replace('auth_a_',''),value)},
    farmCloudSections:{calendar:{value:[],revision:0}},
    api:async(path,options)=>{
      posted.push({path,options});
      if(fail)throw Error('TigerData unavailable');
      return {results:{calendar:{action:'merged',count:1}},sections:{
        calendar:{value:options.body.sections.calendar,revision:1,present:true}}};
    }
  };
  vm.createContext(ctx);
  vm.runInContext(migrateFn+'\nthis.runMigration=migrateLegacyCalendarOnce;',ctx);
  return {ctx,posted,values};
}

test('old browser calendar tasks are automatically imported with an account-scoped key',async()=>{
  const {ctx,posted,values}=migrationContext({legacy:[{id:'old-1',date:'2026-11-15'}]});
  const result=await ctx.runMigration();
  assert.equal(result.status,'imported');
  assert.equal(posted.length,1);
  assert.equal(posted[0].path,'/api/farm/import');
  assert.deepEqual(JSON.parse(JSON.stringify(posted[0].options.body.sections.calendar)),
    [{id:'old-1',date:'2026-11-15'}]);
  assert.equal(JSON.parse(values.get('calendar_tigerdata_imported_v1')),true);
});

test('a previously migrated calendar is not imported twice or resurrected',async()=>{
  const {ctx,posted}=migrationContext({legacy:[{id:'deleted-task'}],migrated:true});
  assert.equal((await ctx.runMigration()).status,'already_handled');
  assert.equal(posted.length,0);
});

test('previously acknowledged or declined imports remain opt-in',async()=>{
  const {ctx,posted}=migrationContext({legacy:[{id:'old-task'}],ack:true});
  assert.equal((await ctx.runMigration()).status,'already_handled');
  assert.equal(posted.length,0);
});

test('failed cloud import retains browser tasks and no migration marker',async()=>{
  const {ctx,values}=migrationContext({legacy:[{id:'saved-task'}],fail:true});
  assert.equal((await ctx.runMigration()).status,'failed');
  assert.equal(values.has('calendar_tigerdata_imported_v1'),false);
  assert.equal(JSON.parse(values.get('calendar')).length,1);
});

function frontend({mode='ready',events=[],cloud={events:[{id:'cloud',date:'2026-11-15'}],revision:4},error=null}={}){
  const calls=[],status=[];
  const stateObj={tasks:events};
  const ctx={
    calendarState:stateObj,
    farmCloudMode:mode,
    farmCloudSections:{calendar:{value:events,revision:1,present:true}},
    state:{tab:'crops'},
    document:{visibilityState:'visible'},
    api:async(path)=>{
      calls.push(path);
      if(error)throw Error(error);
      return cloud;
    },
    renderCalendar:()=>calls.push('render'),
    calendarSyncNotice:(message,isError=false)=>status.push({message,isError}),
    showToast:()=>{},
  };
  vm.createContext(ctx);
  vm.runInContext(
    'let calendarLoadSerial=0;let calendarMutationEpoch=0;'+
    'let calendarLastFetch=0;let calendarFetchPending=false;\n'+loadFn+
    '\nthis.load=loadCalendar;this.refresh=refreshFarmCalendar;'+
    'this.bumpMutation=()=>{calendarMutationEpoch++;};'+
    'this.changeLastFetch=(value)=>{calendarLastFetch=value;};',
    ctx);
  return {ctx,calls,status};
}

test('calendar loads the cloud response, renders, and reports TigerData status',async()=>{
  const {ctx,calls,status}=frontend();
  await ctx.load();
  assert.equal(calls[0],'/api/calendar');
  assert.equal(calls.at(-1),'render');
  assert.equal(ctx.calendarState.tasks[0].id,'cloud');
  assert.equal(ctx.farmCloudSections.calendar.revision,4);
  assert.ok(status.at(-1).message.includes('TigerData'));
});

test('failed cloud reads preserve previously displayed tasks and visibly report an error',async()=>{
  const {ctx,calls,status}=frontend({
    events:[{id:'existing'}],error:'TigerData is offline'});
  await ctx.load();
  assert.equal(ctx.calendarState.tasks[0].id,'existing');
  assert.equal(calls.includes('render'),false);
  assert.equal(status.at(-1).isError,true);
});

test('cloud reads do not overwrite a new calendar mutation',async()=>{
  let release;
  const {ctx}=frontend();
  ctx.api=()=>new Promise(resolve=>{release=resolve;});
  const pending=ctx.load();
  ctx.bumpMutation();
  release({events:[{id:'stale'}],revision:1});
  await pending;
  assert.equal(ctx.calendarState.tasks.length,0);
});

test('calendar refresh skips hidden pages and throttles frequent checks',async()=>{
  const {ctx,calls}=frontend();
  ctx.state.tab='soil';
  await ctx.refresh();
  assert.equal(calls.length,0);
  ctx.state.tab='crops';
  await ctx.refresh();
  assert.ok(calls.includes('/api/calendar'));
  const first=calls.length;
  await ctx.refresh();
  assert.equal(calls.length,first);
});

test('authenticated API route reads the calendar directly from TigerData',()=>{
  assert.match(source,/if\(method==='GET'\)return api\('\/api\/farm\/calendar'/);
  assert.match(source,/loadAccount\(\)\.then\(\(\)=>\{/);
  assert.match(source,/if\(name==='crops'\)refreshFarmCalendar\(\)/);
  assert.match(source,/setInterval\(\(\)=>refreshFarmCalendar\(\),60000\)/);
});
