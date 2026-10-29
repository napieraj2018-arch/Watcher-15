import {strict as assert} from "node:assert";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import handler from "./staging/index.mjs";
const BASE="https://vault-stage.example.test";
test("staging health is truthful and cannot establish profile auth",async()=>{
 const res=await handler.fetch(new Request(BASE+"/health"));
 const j=await res.json();
 assert.equal(res.status,200);
 assert.equal(res.headers.get("cache-control"),"no-store");
 assert.equal(res.headers.get("access-control-allow-origin"),null);
 assert.equal(j.status,"staging_locked");
 assert.equal(j.browser_available,false);
 assert.equal(j.write_enabled,false);
 assert.equal(j.profile_restored,false);
});
test("HEAD health reveals no private contents",async()=>{
 const r=await handler.fetch(new Request(BASE+"/health",{method:"HEAD"}));
 assert.equal(r.status,200);
 assert.equal(await r.text(),"");
});
for(const route of ["/_api/profile-vault","/_api/task-vault",
 "/_api/engine-profile","/_api/provider-recovery","/mcp",
 "/owner-mobile/login"]){
 test("refuses all browser and vault operations "+route,async()=>{
  for(const method of ["GET","POST"]){
   const r=await handler.fetch(new Request(BASE+route,{
    method,...(method==="POST"?{body:'{"action":"save"}'}:{})}));
   assert.equal(r.status,503);
   assert.equal((await r.json()).write_enabled,false);
  }
 });
}
test("DB schema cannot enable live writer without reviewed DDL change",()=>{
 const s=readFileSync(new URL("./001_staging_schema.sql",import.meta.url),"utf8");
 for(const n of ["browser_profiles","browser_profile_versions","browser_engine_profiles",
  "browser_task_checkpoints","browser_control_leases","browser_profile_events",
  "browser_account_attempts","vault_config","vault_migration_guard"])
  assert.ok(s.includes("CREATE TABLE "+n)||s.includes("CREATE TABLE "+n+"("),n);
 assert.ok(s.includes("CHECK(NOT write_enabled)"));
 assert.ok(s.includes("IS DISTINCT FROM"));
 assert.ok(s.includes("reason <> 'update'"));
 assert.doesNotMatch(s,/\b(?:DROP|TRUNCATE)\s+(?:TABLE\s+)?/i);
 assert.doesNotMatch(s,/\bDELETE\s+FROM\b/i);
});
test("staging health function contains no profile/DB write or outgoing fetch",()=>{
 const s=readFileSync(new URL("./staging/index.mjs",import.meta.url),"utf8");
 assert.doesNotMatch(s,/\b(?:INSERT\s+INTO|UPDATE\s+browser_profiles|SELECT\s+encrypted_state|new\s+Pool|new\s+Client)\b/i);
 assert.doesNotMatch(s,/\bfetch\s*\(\s*["']https?:/i);
});
