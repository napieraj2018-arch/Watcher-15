/* Owner Neon staging: read-only DB connectivity, no private row data. */
import postgres from 'postgres';
const headers={'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const output=(obj,status)=>new Response(JSON.stringify(obj),{status,headers});
let lastAt=0,lastResult=null;
export default {async fetch(request){
 let path;try{path=new URL(request.url).pathname}catch{return output({status:'unavailable'},400)}
 if(request.method!=='GET'||path!=='/health')return output({status:'not_found'},404);
 if(lastResult&&Date.now()-lastAt<60000)return output(lastResult.body,lastResult.status);
 let db;
 try{
  const url=process.env.DATABASE_URL;
  if(typeof url!=='string'||!url.startsWith('postgres'))return output({status:'no_database'},503);
  db=postgres(url,{max:1,connect_timeout:5,idle_timeout:5,prepare:false});
  const rows=await db`SELECT mode,write_enabled FROM vault_migration_guard WHERE only_row=true`;
  const locked=rows.length===1&&rows[0].mode==='staging_read_only'&&rows[0].write_enabled===false;
  const body={status:locked?'staging_locked':'guard_unconfirmed',database_reachable:true,browser_available:false,write_enabled:false};
  const status=locked?200:503;lastResult={body,status};lastAt=Date.now();
  return output(body,status);
 }catch{return output({status:'database_unconfirmed',browser_available:false,write_enabled:false},503)}
 finally{if(db)try{await db.end({timeout:2})}catch{}}
}};