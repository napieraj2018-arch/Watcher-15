const {readFileSync}=require('fs');
const vm=require('vm');
const assert=require('assert');
const script=readFileSync('fresh_browser/index.html','utf8').split('<script>')[1].split('</script>')[0];
async function test(profile){
 const els=new Map();
 function get(id){if(!els.has(id))els.set(id,{value:'',textContent:'',style:{},dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},closest(){return get('parent-'+id)},replaceChildren(){this.options=[];this.value=''},add(o){(this.options??=[]).push(o)},removeAttribute(){}});return els.get(id)}
 let paired=false;
 const sandbox={document:{getElementById:get,querySelectorAll(){return []}},window:{location:{pathname:'/owner/',hash:'#synthetic-offline-fixture'}},history:{replaceState(a,b,u){this.path=u}},Option:function(t,v){this.text=t;this.value=v},URL:{createObjectURL(){return 'blob:fixture'},revokeObjectURL(){}},Date,fetch:async(path,opts)=>{
 if(path==='./api/pair'){paired=true;assert.equal(JSON.parse(opts.body).token,'synthetic-offline-fixture')}
 let data=path==='./api/profiles'?{profiles:[{name:profile}]}:path==='./api/action'?{ok:true,title:'Neutral fixture',url:'https://example.com'}:{ok:true};
 return {ok:true,json:async()=>data,blob:async()=>({})}
 }};
 await vm.runInNewContext(script,sandbox);
 assert(paired);assert.equal(get('profile').value,profile);assert.equal(get('error').textContent,'');assert(get('message').textContent.includes(profile));assert.equal(sandbox.history.path,'/owner/');
}
(async()=>{await test('acceptance-mobile-v2');await test('facebook-klinika');console.log('PASS offline UI initialization: fixed profile selection, one-use exchange request, fragment removal, no error for neutral and clinic profiles')})().catch(e=>{console.error(e);process.exitCode=1});
