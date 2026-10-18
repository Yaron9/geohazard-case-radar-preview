import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
from platform_media import parse_captions,article_records,collect_platform,platform_of,canonical_media_url

class PlatformTests(unittest.TestCase):
 def test_platform_host_validation(self):
  self.assertEqual(platform_of('https://v.douyin.com/abc/'),'douyin')
  for url in ['https://douyin.com.evil.example/x','file:///etc/passwd','https://user:password@mp.weixin.qq.com/s/x']:
   with self.assertRaises(ValueError):platform_of(url)
 def test_caption_timestamps_are_preserved(self):
  result=parse_captions(b'WEBVTT\n\n00:00:01.200 --> 00:00:04.000\nEarly evacuation\n\n00:00:04.100 --> 00:00:07.000\nNo casualties\n','vtt')
  self.assertEqual(result[0],{'start':1.2,'end':4.0,'text':'Early evacuation'})
 def test_automatic_json_caption(self):
  result=parse_captions(b'{"events":[{"tStartMs":1200,"dDurationMs":500,"segs":[{"utf8":"evacuate"}]}]}','json3')
  self.assertEqual(result[0]['start'],1.2)
 def test_missing_caption_never_becomes_verified_evidence(self):
  article={'title':'滑坡成功避险','url':'https://www.bilibili.com/video/BV123','body':'','capturedAt':'2026-01-01','publishedAt':'','publisher':'发布者','media':{'platform':'bilibili','textStatus':'missing'}}
  result=article_records(article,{'id':'video-discovery'},True)[0]
  self.assertEqual(result['resourceKind'],'video-lead');self.assertTrue(all(not f['quote'] and not f['confirmed'] for f in result['evidence']))
 def test_wechat_reader_failure_is_explicit_and_lead_retains_link(self):
  candidate={'url':'https://mp.weixin.qq.com/s/test','title':'滑坡成功避险','accountName':'县融媒体'}
  with patch('platform_media.search_wechat',return_value=([candidate],[{'provider':'搜狗微信','status':'success','url':'https://weixin.sogou.com/'}])),patch('platform_media.read_wechat',side_effect=RuntimeError('验证码')):
   records,run=collect_platform({'id':'wechat-discovery','name':'公众号','type':'wechat-search','query':'滑坡','url':'https://weixin.sogou.com/'})
  self.assertEqual(run['status'],'partial');self.assertEqual(records[0]['resourceKind'],'article-lead');self.assertIn('验证码',run['failures'][0]['message'])
 def test_exact_wechat_identity_discards_tracking_not_account(self):
  a=canonical_media_url('https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=x&scene=25')
  b=canonical_media_url('https://mp.weixin.qq.com/s?__biz=def&mid=123&idx=1&sn=x')
  self.assertNotEqual(a,b);self.assertNotIn('scene',a)
 def test_single_video_failure_does_not_report_success(self):
  with patch('platform_media.read_video',side_effect=RuntimeError('登录限制')):
   records,run=collect_platform({'id':'v','name':'视频','type':'video','url':'https://www.douyin.com/video/123'})
  self.assertEqual(records,[]);self.assertEqual(run['status'],'failure');self.assertEqual(run['httpStatus'],0)

if __name__=='__main__':unittest.main()
