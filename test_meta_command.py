"""Synthetic contracts only: no real users, Meta access, login or publishing."""
import copy
import unittest
from meta_command import (MetaCommandError, parse_command, prepare_preview,
                          authorize_preview, verify_publication)
from connector_router import plan_operation

COMMAND='Użyj konta Meta 1, znajdź piąty wpis w wybranej grupie, przygotuj odpowiedź i pokaż ją do publikacji'


class Preview(unittest.TestCase):
 def setUp(self):
  self.bindings={1:{'profile':'Synthetic-One','identity_id':'synthetic-actor',
                    'owner_label':'Synthetic Owner','authorized':True}}
  self.observation={'profile':'Synthetic-One','identity_id':'synthetic-actor','authenticated':True,
                    'observed_at':1000,'membership_verified':True,'can_comment':True,'group_id':'101',
                    'ordered_post_urls':[f'https://www.facebook.com/groups/101/posts/{i}/' for i in range(201,207)]}
 def preview(self):return prepare_preview(COMMAND,self.bindings,self.observation,'Synthetic draft',now=1001)
 def test_route_is_exposed_through_existing_tool_without_start_or_publication(self):
  r=plan_operation('facebook',COMMAND)
  self.assertEqual(r['alias'],1);self.assertEqual(r['post_ordinal'],5)
  self.assertFalse(r['published']);self.assertFalse(r['browser_started'])
 def test_ten_aliases_and_numbered_posts(self):
  r=parse_command(COMMAND.replace('Meta 1','Meta 10').replace('piąty','5'))
  self.assertEqual((r['alias'],r['post_ordinal']),(10,5))
  self.assertEqual(parse_command(COMMAND.replace('wybranej grupie','wybranej grupie Spotted'))['post_ordinal'],5)
 def test_unsupported_or_publish_commands_never_default_to_another_identity(self):
  for c in [COMMAND.replace('Meta 1','Meta 11'),COMMAND.replace('Meta 1','Meta 0'),
            COMMAND.replace('Meta 1','Meta 1 i Meta 2'),COMMAND+' i opublikuj',
            COMMAND.replace('piąty','kolejny')]:
   with self.assertRaises(MetaCommandError):parse_command(c)
 def test_private_binding_required(self):
  with self.assertRaises(MetaCommandError):prepare_preview(COMMAND,{},self.observation,'draft',now=1001)
 def test_saved_profile_is_not_authenticated(self):
  self.observation['authenticated']=None
  with self.assertRaisesRegex(MetaCommandError,'AUTHENTICATION'):self.preview()
 def test_wrong_active_identity_blocks_preview(self):
  self.observation['identity_id']='another-actor'
  with self.assertRaisesRegex(MetaCommandError,'IDENTITY_MISMATCH'):self.preview()
 def test_no_group_comment_permission_blocks_preview(self):
  self.observation['can_comment']=False
  with self.assertRaisesRegex(MetaCommandError,'PERMISSION'):self.preview()
 def test_stale_and_future_evidence_block_preview(self):
  for t in [0,1002,float('nan')]:
   self.observation['observed_at']=t
   with self.assertRaisesRegex(MetaCommandError,'FRESH_READBACK'):self.preview()
 def test_fifth_is_frozen_as_exact_permalink_not_feed_position(self):
  p=self.preview();self.assertEqual(p['post_url'],'https://www.facebook.com/groups/101/posts/205/')
  self.assertEqual(p['status'],'awaiting_exact_approval');self.assertFalse(p['publish_allowed'])
 def test_duplicate_permalinks_do_not_silently_shift_ordinal(self):
  self.observation['ordered_post_urls'][1]=self.observation['ordered_post_urls'][0]
  with self.assertRaisesRegex(MetaCommandError,'ORDINAL'):self.preview()
 def test_insufficient_feed_is_not_zero_results(self):
  self.observation['ordered_post_urls']=self.observation['ordered_post_urls'][:4]
  with self.assertRaisesRegex(MetaCommandError,'ORDINAL'):self.preview()
 def test_exact_group_domain_and_no_secret_query(self):
  for url in ['https://www.facebook.com/groups/999/posts/205/',
              'https://www.facebook.com.evil.test/groups/101/posts/205/',
              'https://user:password@www.facebook.com/groups/101/posts/205/',
              'https://www.facebook.com/groups/101/posts/205/?token=private']:
   self.observation['ordered_post_urls'][4]=url
   with self.assertRaisesRegex(MetaCommandError,'EXACT_POST'):self.preview()
 def fresh(self,p):return {**self.observation,'post_url':p['post_url']}
 def test_exact_approval_returns_only_journal_metadata(self):
  p=self.preview();r=authorize_preview(p,self.bindings[1],self.fresh(p),p['approval_digest'],now=1001)
  self.assertEqual(r['operation_id'],p['operation_id']);self.assertFalse(r['published'])
 def test_approval_invalidated_by_text_or_identity_change(self):
  for field,value in [('text','Changed'),('identity_id','other')]:
   p=self.preview();p[field]=value
   with self.assertRaisesRegex(MetaCommandError,'APPROVAL'):authorize_preview(p,self.bindings[1],self.fresh(p),p['approval_digest'],now=1001)
 def test_target_change_after_approval_blocks_execution(self):
  p=self.preview();fresh=self.fresh(p);fresh['post_url']='https://www.facebook.com/groups/101/posts/206/'
  with self.assertRaisesRegex(MetaCommandError,'TARGET_CHANGED'):authorize_preview(p,self.bindings[1],fresh,p['approval_digest'],now=1001)
 def test_duplicate_request_uses_same_operation_id(self):
  self.assertEqual(self.preview()['operation_id'],self.preview()['operation_id'])
 def test_click_acknowledgement_cannot_confirm_publication(self):
  self.assertFalse(verify_publication(self.preview(),{'clicked':True}))
 def test_only_exact_comment_readback_after_reload_confirms(self):
  p=self.preview();r={'identity_id':p['identity_id'],'text':p['text'],'post_url':p['post_url'],
                     'observed_after_reload':True,'comment_id':'301'}
  self.assertTrue(verify_publication(p,r))
  for key,val in [('identity_id','other'),('text','other'),('observed_after_reload',False),('comment_id',None)]:
   self.assertFalse(verify_publication(p,{**r,key:val}))

if __name__=='__main__':unittest.main(verbosity=2)
