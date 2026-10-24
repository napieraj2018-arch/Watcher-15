"""Strict fake-HTTP contract tests. No Floot production requests."""
import unittest
import httpx
from youtube_floot_cas import FlootOAuthCAS, CASUnconfirmed, URL, secret

VALID = 'youtube-v1:'+'a'*64+':'+'b'*64

class CASUnitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.payloads=[]
        self.status=200
        self.response={'found':False}
        self.response_raw=None
        def reply(req):
            self.payloads.append((req.url,req.headers,req.content))
            if self.response_raw is not None: return httpx.Response(self.status,content=self.response_raw)
            return httpx.Response(self.status,json=self.response)
        self.cas=FlootOAuthCAS('X'*48,transport=httpx.MockTransport(reply))

    async def test_read_missing(self):
        self.assertIsNone(await self.cas.read(VALID))
        self.assertEqual(str(self.payloads[0][0]),URL)
        self.assertIn('Bearer ',self.payloads[0][1]['authorization'])
    async def test_read_existing(self):
        self.response={'found':True,'revision':3,'envelope':'encrypted'}
        self.assertEqual(await self.cas.read(VALID),(3,'encrypted'))
    async def test_insert(self):
        self.response={'revision':1}
        self.assertEqual(await self.cas.write(VALID,None,'sealed'),1)
        self.assertIn(b'"expectedRevision":null',self.payloads[0][2])
    async def test_update_revision(self):
        self.response={'revision':4}
        self.assertEqual(await self.cas.write(VALID,3,'sealed'),4)
    async def test_conflict(self):
        self.status=409
        with self.assertRaisesRegex(CASUnconfirmed,'CONFLICT'):await self.cas.write(VALID,None,'sealed')
    async def test_unauthorized(self):
        self.status=401
        with self.assertRaisesRegex(CASUnconfirmed,'UNAUTHORIZED'):await self.cas.read(VALID)
    async def test_missing_endpoint_fails_closed(self):
        self.status=404
        with self.assertRaisesRegex(CASUnconfirmed,'UNAVAILABLE'):await self.cas.read(VALID)
    async def test_redirect_refused(self):
        self.status=302
        with self.assertRaisesRegex(CASUnconfirmed,'UNAVAILABLE'):await self.cas.read(VALID)
    async def test_html_refused(self):
        self.response_raw=b'<!DOCTYPE html> no vault'
        with self.assertRaisesRegex(CASUnconfirmed,'UNCONFIRMED'):await self.cas.read(VALID)
    async def test_invalid_keys_block_before_network(self):
        for key in ('../foo','youtube-v1:x', 'youtube-v1:'+'z'*64+':'+'b'*64, '',None):
            with self.assertRaisesRegex(CASUnconfirmed,'INVALID_KEY'):await self.cas.read(key)
        self.assertEqual(self.payloads,[])
    async def test_invalid_envelopes_block_before_network(self):
        for value in ('', 'z'*150001, None):
            with self.assertRaisesRegex(CASUnconfirmed,'INVALID_WRITE'):await self.cas.write(VALID,None,value)
        self.assertEqual(self.payloads,[])
    async def test_invalid_revision_block_before_network(self):
        for value in (-1,True,0,'2'):
            with self.assertRaisesRegex(CASUnconfirmed,'INVALID_WRITE'):await self.cas.write(VALID,value,'ciphertext')
        self.assertEqual(self.payloads,[])
    async def test_revision_must_be_exact_increment(self):
        self.response={'revision':50}
        with self.assertRaisesRegex(CASUnconfirmed,'WRITE_UNCONFIRMED'):await self.cas.write(VALID,2,'sealed')
    async def test_missing_or_bad_found_rejected(self):
        for result in ({},{'found':True,'revision':1,'envelope':''},{'found':1,'revision':1,'envelope':'encrypted'}):
            self.response=result
            with self.assertRaisesRegex(CASUnconfirmed,'RESPONSE_INVALID'):await self.cas.read(VALID)
    async def test_provider_private_errors_not_reflected(self):
        self.status=500;self.response_raw=b'secret-do-not-leak'
        with self.assertRaises(CASUnconfirmed) as cm:await self.cas.read(VALID)
        self.assertNotIn('secret-do-not-leak',str(cm.exception))
    async def test_no_arbitrary_network_destination(self):
        self.response={'found':False}
        await self.cas.read(VALID)
        self.assertEqual([str(c[0]) for c in self.payloads],[URL])
    async def test_separate_key_labels(self):
        self.assertNotEqual(secret('X'*48,'youtube-aesgcm-data-v1'),secret('X'*48,'youtube-floot-cas-bearer-v1'))
    async def test_short_master_key_fails_closed(self):
        with self.assertRaisesRegex(CASUnconfirmed,'MASTER_KEY_REQUIRED'):FlootOAuthCAS('x')

if __name__=='__main__':unittest.main()
