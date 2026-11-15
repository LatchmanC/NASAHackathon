/* Browser-level isolated Farm Calendar -> Google export regression tests. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const src=fs.readFileSync(path.resolve(__dirname,'../public/static/app.js'),'utf8');
const start=src.indexOf('async function syncFarmTaskWithGoogle(id){');
const end=src.indexOf('function moveCalendarMonth(change){',start);
assert.ok(start>0&&end>start,'Could not locate manual Farm Calendar Google sync functions');
const code=src.slice(start,end);

function makeClient({connected=true,checked=true,mode='ready',googleFails=false,farmFails=false}={}){
  const fields={
    '#event-date':{value:'2026-12-02'},
    '#event-type':{value:'watering'},
    '#event-crop':{value:'Tomato'},
    '#event-note':{value:'Check soil moisture'},
    '#calendar-save-button':{disabled:false,textContent:'+ Save task'},
    '#google-task-sync-checkbox':{checked},
  };
  let calls=[],toast=[],lastSavedTask=null;
  const account={calendar:{value:[],revision:1,present:true}};
  const context={
    $:selector=>{assert.ok(fields[selector],'Unexpected element '+selector);return fields[selector];},
    crypto:{randomUUID:()=>'stable-manual-task-uuid'},
    farmCloudMode:mode,
    googleCalendarConnected:connected,
    farmCloudSections:account,
    calendarState:{tasks:[],selected:null,year:2026,month:10},
    renderCalendar:()=>{},
    showToast:(message,isError)=>toast.push({message,isError:!!isError}),
    confirm:()=>true,
    api:async(url,opts)=>{
      calls.push({url,opts});
      if(url==='/api/calendar'&&opts.method==='POST'){
        if(farmFails)throw Error('Farm database temporarily unavailable');
        const task={...opts.body,google_event_id:null};
        lastSavedTask=task;
        return {saved:true,events:[task],revision:2};
      }
      if(url.endsWith('/google-sync')){
        if(googleFails)throw Error('Google Calendar authorization expired');
        return {synced:true,revision:3,events:[{...lastSavedTask,google_event_id:'g-stable'}]};
      }
      throw Error('Unexpected call '+url);
    },
  };
  vm.createContext(context);
  vm.runInContext('let pendingCalendarSubmission=null;\n'+code+
    '\nthis.add=addCalendarEvent;this.sync=syncFarmTaskWithGoogle;'+
    'this.pending=()=>pendingCalendarSubmission;',context);
  return {context,fields,calls,toast,setGoogleFail:v=>{googleFails=v;},
          setFarmFail:v=>{farmFails=v;}};
}
test('connected Auth0 Save Task persists to farm before Google, using same stable task ID',async()=>{
  const c=makeClient();
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls.length,2);
  assert.equal(c.calls[0].url,'/api/calendar');
  assert.equal(c.calls[0].opts.body.id,'stable-manual-task-uuid');
  assert.equal(c.calls[1].url,'/api/farm/calendar/stable-manual-task-uuid/google-sync');
  assert.equal(c.calls[1].opts.body.confirmed,true);
  assert.equal(c.context.calendarState.tasks[0].google_event_id,'g-stable');
  assert.equal(c.fields['#event-note'].value,'');
  assert.equal(c.fields['#calendar-save-button'].disabled,false);
  assert.match(c.toast.at(-1).message,/saved in TigerData and added to Google Calendar/);
});
test('unchecked Google opt-in sends only to TigerData',async()=>{
  const c=makeClient({checked:false});
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls.length,1);
  assert.match(c.toast.at(-1).message,/Google Calendar not selected/);
});
test('disconnected Google account saves Farm task only',async()=>{
  const c=makeClient({connected:false});
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls.length,1);
  assert.match(c.toast.at(-1).message,/Connect Google Calendar/);
});
test('sample account never invokes Google and keeps browser save',async()=>{
  const c=makeClient({mode:'sample',connected:false});
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls.length,1);
  assert.match(c.toast.at(-1).message,/Demo task/);
});
test('Google outage retains saved farm task, clearly reports partial failure and permits retry',async()=>{
  const c=makeClient({googleFails:true});
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls.length,2);
  assert.equal(c.context.calendarState.tasks[0].id,'stable-manual-task-uuid');
  assert.equal(c.context.calendarState.tasks[0].google_event_id,null);
  assert.equal(c.toast.at(-1).isError,true);
  assert.match(c.toast.at(-1).message,/Farm task SAVED in TigerData/);
  c.setGoogleFail(false);
  await c.context.sync('stable-manual-task-uuid');
  assert.equal(c.context.calendarState.tasks[0].google_event_id,'g-stable');
  assert.equal(c.calls[2].url,'/api/farm/calendar/stable-manual-task-uuid/google-sync');
});
test('farm failure never calls Google and retries same stable ID',async()=>{
  const c=makeClient({farmFails:true});
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls.length,1);
  assert.equal(c.calls[0].opts.body.id,'stable-manual-task-uuid');
  assert.ok(c.context.pending());
  c.setFarmFail(false);
  await c.context.add({preventDefault(){}});
  assert.equal(c.calls[1].opts.body.id,'stable-manual-task-uuid');
  assert.equal(c.calls.length,3);
});
test('the connected-state control and per-task Google status are present',()=>{
  assert.match(src,/checkbox\.disabled=!connected/);
  assert.match(src,/googleCalendarConnected=Boolean\(r\.connected\)/);
  assert.match(src,/calendar-google-synced/);
  assert.match(src,/Send to Google/);
  assert.match(src,/Google Calendar event will remain/);
});
