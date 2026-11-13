const {readFileSync}=require('fs');
const vm=require('vm');
const assert=require('assert');
const script=readFileSync('fresh_browser/index.html','utf8').split('<script>')[1].split('</script>')[0];
async function test(profile){
 const els=new Map();
 function get(id){if(!els.has(id))els.set(id,{value:'',textContent:'',style:{},dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},closest(){return get('parent-'+id)},replaceChildren(){this.options=[];this.value=''},add(o){(this.options??=[]).push(o)},removeAttribute(){}});return els.get(id)}
 let paired=false,actions=0,frames=0,timerId=0;
 const timers=new Map();
 const sandbox={AbortController,setTimeout(fn,ms){timers.set(++timerId,{fn,ms});return timerId},clearTimeout(id){timers.delete(id)},document:{hidden:false,getElementById:get,querySelectorAll(){return []}},window:{location:{pathname:'/owner/',hash:'#synthetic-offline-fixture'}},history:{replaceState(a,b,u){this.path=u}},Option:function(t,v){this.text=t;this.value=v},URL:{createObjectURL(){return 'blob:fixture'},revokeObjectURL(){}},Date,fetch:async(path,opts)=>{
 if(path==='./api/pair'){paired=true;assert.equal(JSON.parse(opts.body).token,'synthetic-offline-fixture')}
 if(path==='./api/action')actions++;
 if(path.startsWith('./api/screen'))frames++;
 let data=path==='./api/profiles'?{profiles:[{name:profile}]}:path==='./api/action'?{ok:true,title:'Neutral fixture',url:'https://example.com'}:path.startsWith('./api/tabs')?{tabs:[{id:'tab-1',title:'Neutral',url:'https://example.com',active:true}]}:{ok:true};
 return {ok:true,json:async()=>data,blob:async()=>({}),headers:{get(n){return {'X-AIB-Page':'tab-1','X-AIB-Origin':'https://example.com','X-AIB-Tabs':'1'}[n]||null}}}
 }};
 await vm.runInNewContext(script,sandbox);
 assert(paired);assert.equal(get('profile').value,profile);assert.equal(get('error').textContent,'');assert(get('message').textContent.includes(profile));assert.equal(sandbox.history.path,'/owner/');
 assert.equal(get('screen').dataset.pageId,'tab-1');assert(get('liveStatus').textContent.includes('Podgląd na żywo'));
 const tick=async()=>{const [id,t]=[...timers].find(([id,t])=>t.ms===2000);timers.delete(id);await t.fn()};
 assert.equal(actions,1);assert.equal(frames,1);
 await tick();assert.equal(frames,2);assert.equal(actions,1,'Refreshing the image must not resubmit a form');
 sandbox.document.hidden=true;await tick();assert.equal(frames,2,'No requests from hidden panels');
 sandbox.document.hidden=false;await tick();assert.equal(frames,3);
}
(async()=>{await test('acceptance-mobile-v2');await test('facebook-klinika');console.log('PASS owner UI: fixed profile, fragment removal, timed frame refresh, hidden-panel pause, no repeated form submission')})().catch(e=>{console.error(e);process.exitCode=1});

