/**
 * Read-only private Steel API inventory runner. Execute only inside an owner
 * trusted runtime that already holds STEEL_API_KEY in its secret manager.
 * This script never creates/releases sessions, exports IDs or authorizes
 * migration. It cannot itself verify provider profile saved-close state.
 */
import {createSteelReadonlyClient} from './steel_inventory_readonly.mjs';
const allowed=new Set([
 'STEEL_INVENTORY_AUTH_UNAVAILABLE','STEEL_INVENTORY_PROJECT_UNVERIFIED',
 'STEEL_INVENTORY_ROUTE_DENIED','STEEL_INVENTORY_SCOPE_DENIED',
 'STEEL_INVENTORY_CURSOR_INVALID','STEEL_INVENTORY_RESPONSE_TOO_LARGE',
 'STEEL_INVENTORY_INVALID_RESPONSE','STEEL_INVENTORY_INVALID_JSON',
 'STEEL_INVENTORY_HTTP_UNCONFIRMED','STEEL_INVENTORY_RATE_LIMITED',
 'STEEL_INVENTORY_ACCESS_DENIED','STEEL_INVENTORY_LIVE_OR_AMBIGUOUS',
 'STEEL_INVENTORY_INVALID_SESSION','STEEL_INVENTORY_WRONG_PROJECT',
 'STEEL_INVENTORY_DUPLICATE_SESSION',
 'STEEL_INVENTORY_ACTIVE_OR_UNKNOWN_SESSION',
 'STEEL_INVENTORY_PAGINATION_CONFLICT','STEEL_INVENTORY_PAGE_LIMIT',
 'STEEL_INVENTORY_CLOCK_INVALID'
]);
try{
 const report=await createSteelReadonlyClient({
  apiKey:process.env.STEEL_API_KEY||'',
  // Must be the exact owner-confirmed Steel project ID, never guessed from
  // the dashboard's human-readable project name or organization name.
  projectId:process.env.STEEL_PROJECT_ID||''
 }).inspect();
 process.stdout.write(JSON.stringify(report)+'\n');
}catch(e){
 const code=allowed.has(e?.message)?e.message:'STEEL_INVENTORY_UNCONFIRMED';
 // Never include transport exceptions, provider IDs, email addresses, keys
 // or response bodies in a log or terminal output.
 process.stderr.write(code+'\n');
 process.exitCode=1;
}
