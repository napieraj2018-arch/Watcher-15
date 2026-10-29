/* NEON FREE shadow vault: public health only, all private routes fail closed.
 * No database client, vault token, archive payload, credential or session API.
 * This never changes existing Floot or Render production.
 */
const HEADERS = {
  "content-type":"application/json; charset=utf-8",
  "cache-control":"no-store",
  "x-content-type-options":"nosniff",
  "referrer-policy":"no-referrer"
};
const json=(obj,status)=>new Response(JSON.stringify(obj),{status,headers:HEADERS});
export default {
 async fetch(request){
  const path=new URL(request.url).pathname;
  if(path==="/health" && request.method==="GET"){
   return json({status:"staging_locked",browser_available:false,
     write_enabled:false,profile_restored:false,source:"floot",
     storage_backend:"neon_staging"},200);
  }
  if(path==="/health" && request.method==="HEAD")
   return new Response(null,{status:200,headers:HEADERS});
  return json({error:"NEON_STAGING_WRITE_DISABLED",
    browser_available:false,write_enabled:false},503);
 }
};
