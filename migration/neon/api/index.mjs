import {createApi} from './core.mjs';
import {createStore} from './store.mjs';
// DATABASE_URL is injected by Neon at runtime and is never logged or returned.
// Missing owner authorization deliberately leaves every private API inaccessible.
const digest=process.env.AIB_STAGE_API_TOKEN_SHA256||'';
let database=null;
if(/^[a-f0-9]{64}$/.test(digest)&&process.env.DATABASE_URL){
 try{database=createStore(process.env.DATABASE_URL)}catch{}
}
export default createApi({database,tokenSha256:digest});
