/* Frontend-only Fieldy regression tests; no browser or Gemini key required. */
'use strict';
const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../public/static/app.js'),'utf8');

function between(a,b){
  const start=source.indexOf(a),stop=source.indexOf(b,start+a.length);
  assert.ok(start>=0&&stop>start,a+' and '+b+' must exist');
  return source.slice(start,stop);
}
const html=val=>String(val??'').replace(/[&<>"']/g,ch=>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

function context(){
  const saved=new Map();
  const chat={innerHTML:'',scrollTop:0,scrollHeight:200};
  const box={};
  const root={
    html,fsAccount:'auth_account_a',sessionStorage:{
      getItem:key=>saved.get(key)??null,
      setItem:(key,value)=>saved.set(key,value),
      removeItem:key=>saved.delete(key)
    },
    $:key=>key==='#fieldy-chat-history'?chat:box,
    showToast:()=>{},confirm:()=>true
  };
  vm.createContext(root);
  const code=between('let fieldyTurns=[];','function fieldySoilView(){');
  vm.runInContext(code+
    '\nthis.fieldyActions={render:renderFieldyAdvice,load:fieldyLoadHistory,add:fieldyAddTurn,clear:fieldyClearHistory,turns:()=>fieldyTurns,key:fieldySessionKey,append:fieldyRenderConversation};',
    root);
  return {root,chat,saved,act:root.fieldyActions};
}

test('Gemini attribution and live chat history stay in sessionStorage only',()=>{
  const {root,act,saved,chat}=context();
  act.add('user','What about wet soil?');
  act.add('assistant','Avoid planting before the soil is workable.',
    {answer:'**Wet soil** can delay planting.',highlights:[]});
  assert.ok(chat.innerHTML.includes('Powered by Gemini'));
  assert.ok(saved.has(act.key()));
  assert.equal(act.turns().length,2);
  act.load();
  assert.equal(act.turns().length,2);
  assert.equal(saved.has(act.key()),true);
  assert.equal(root.localStorage,undefined);
});

test('clear chat does not delete farm records',()=>{
  const {act,saved}=context();
  act.add('user','My corn?');
  assert.equal(act.turns().length,1);
  act.clear();
  assert.equal(act.turns().length,0);
  assert.equal(saved.has(act.key()),false);
});

test('Gemini data highlights bold important metrics with escaped output',()=>{
  const {act}=context();
  const rendered=act.render({
    answer:'Drainage is **poor**. <script>alert(1)</script>',
    highlights:[{label:'Soil pH <danger>',value:'6.3 <unsafe>',source:'USDA & survey'}],
    assumptions:['Observed <nowhere>'],source_notes:['No probe data']
  });
  assert.ok(rendered.includes('<strong>poor</strong>'));
  assert.ok(rendered.includes('class="fieldy-highlight"'));
  assert.ok(rendered.includes('&lt;script&gt;'));
  assert.ok(!rendered.includes('<script>'));
  assert.ok(rendered.includes('6.3 &lt;unsafe&gt;'));
  assert.ok(rendered.includes('USDA &amp; survey'));
});

test('demo responses are explicitly distinguished from Gemini requests',()=>{
  const {act,chat}=context();
  act.add('assistant','This is fictional test advice.',{answer:'A demo only.'},'demo');
  assert.ok(chat.innerHTML.includes('Fieldy · Demonstration'));
  assert.ok(!chat.innerHTML.includes('Powered by Gemini'));
});

test('history caps at twenty turns and does not serialize unrelated local data',()=>{
  const {act,saved}=context();
  for(let i=0;i<27;i++)act.add('user','Question '+i);
  assert.equal(act.turns().length,20);
  assert.equal(JSON.parse(saved.get(act.key())).length,20);
});

test('frontend passes session history and Soil & Rotation view to Gemini',()=>{
  assert.match(source,/chat_history:prior,soil_view:fieldySoilView\(\)/);
  assert.match(source,/fieldyTurns\.slice\(-12\)/);
  assert.match(source,/soilState\.profile/);
  assert.match(source,/soilState\.context/);
  assert.match(source,/sessionStorage\.setItem/);
});
