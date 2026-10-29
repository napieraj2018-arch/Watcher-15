import os, base64, secrets, unittest
os.environ['AIB_FRESH_DATABASE_URL']='postgresql://fixture.invalid/db'
os.environ['AIB_FRESH_ADMIN_TOKEN']=secrets.token_urlsafe(40)
os.environ['AIB_FRESH_DATA_KEY']=base64.b64encode(secrets.token_bytes(32)).decode()
os.environ['AIB_FRESH_MCP_TOKEN']=secrets.token_urlsafe(40)
import server
from fastapi.testclient import TestClient
class Security(unittest.TestCase):
 def test_auth_perimeter(self):
  with TestClient(server.app) as c:
   for path in ['/api/profiles','/api/screen?name=fixture','/api/status']:
    self.assertEqual(c.get(path).status_code,401)
   self.assertEqual(c.post('/mcp',json={'method':'tools/list','id':1}).status_code,401)
 def test_mcp_discovery(self):
  with TestClient(server.app) as c:
   r=c.post('/mcp',headers={'authorization':'Bearer '+server.MCP_TOKEN},json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
   self.assertEqual(r.status_code,200)
   self.assertEqual(r.json()['result']['tools'][0]['name'],'fresh_browser')
 def test_cipher_authentication(self):
  k=secrets.token_bytes(32);sealed=server.seal(b'private',k)
  self.assertNotIn(b'private',sealed)
  self.assertEqual(server.unseal(sealed,k),b'private')
  with self.assertRaises(Exception):server.unseal(sealed[:-1]+bytes([sealed[-1]^1]),k)
 def test_urls(self):
  for url in ['http://example.com','https://127.0.0.1','https://localhost/','https://host.internal','https://user:pw@example.com','https://example.com:1234/']:
   with self.assertRaises(server.HTTPException):server.safe_url(url)
 def test_csrf(self):
  with TestClient(server.app) as c:
   c.cookies.set(server.COOKIE,server.session_value())
   self.assertEqual(c.post('/api/action',json={}).status_code,403)
   self.assertEqual(c.post('/api/action',headers={'x-aib-request':'same-origin','origin':'https://evil.invalid'},json={}).status_code,403)
 def test_blob_policy(self):
  with TestClient(server.app) as c:
   self.assertIn("img-src 'self' data: blob:",c.get('/').headers['content-security-policy'])
if __name__=='__main__':unittest.main()
