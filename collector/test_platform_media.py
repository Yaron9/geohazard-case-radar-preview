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
 def test_media_metadata_change_creates_new_material_version(self):
  from crawl import merge_feed
  article={'title':'滑坡成功避险','url':'https://www.bilibili.com/video/BV123','body':'','capturedAt':'2026-01-01','publishedAt':'','publisher':'发布者','media':{'platform':'bilibili','textStatus':'missing','accountName':'旧作者'}}
  old=article_records(article,{'id':'v'},True)[0]
  new=article_records({**article,'media':{**article['media'],'accountName':'已核实作者'}},{'id':'v'},True)[0]
  self.assertNotEqual(old['fingerprint'],new['fingerprint'])
  items,_,changed=merge_feed({'items':[old]},[new]);self.assertEqual(changed,1);self.assertEqual(items[0]['history'][0]['media']['accountName'],'旧作者')
 def test_video_platform_rules_have_distinct_identity(self):
  from platform_media import source_suggestion
  a={'title':'滑坡','url':'https://www.bilibili.com/video/BV123','media':{'platform':'bilibili','accountName':'县融媒体'}}
  b={**a,'url':'https://www.douyin.com/video/123','media':{'platform':'douyin','accountName':'县融媒体'}}
  self.assertNotEqual(source_suggestion(a)['source']['url'],source_suggestion(b)['source']['url'])
 def test_bilibili_inline_captions_without_video_stream_are_supported(self):
  from platform_media import read_video
  from unittest.mock import MagicMock
  metadata={'title':'滑坡提前撤离','id':'BV123','webpage_url':'https://www.bilibili.com/video/BV123','formats':[], 'subtitles':{'zh-Hans':[{'ext':'srt','data':'1\n00:00:01,250 --> 00:00:03,000\n提前撤离52人\n'}]}}
  downloader=MagicMock();downloader.__enter__.return_value.extract_info.return_value=metadata
  with patch('yt_dlp.YoutubeDL',return_value=downloader) as factory:
   article=read_video(metadata['webpage_url'])
  options=factory.call_args.args[0];self.assertTrue(options['writesubtitles']);self.assertTrue(options['ignore_no_formats_error']);self.assertEqual(article['media']['textStatus'],'platform-caption');self.assertEqual(article['media']['segments'][0]['start'],1.25);self.assertIn('52人',article['body'])
 def test_wechat_visible_date_fills_standard_published_date(self):
  from platform_media import read_wechat
  html='<h1 id="activity-name">滑坡成功避险</h1><span id="js_name">县融媒体</span><span id="publish_time">2026年10月17日</span><div id="js_content">'+('提前转移群众，无人员伤亡。'*15)+'</div>'
  soup=BeautifulSoup(html,'html.parser')
  with patch('crawl.fetch',return_value=(soup,'https://mp.weixin.qq.com/s/test',html.encode())):
   article=read_wechat('https://mp.weixin.qq.com/s/test')
  self.assertEqual(article['publishedAt'],'2026-10-17');self.assertEqual(article['media']['accountName'],'县融媒体')
 def test_drill_video_does_not_enter_case_leads(self):
  from crawl import merge_feed
  article={'title':'地质灾害应急避险演练','url':'https://www.bilibili.com/video/BV123','body':'','capturedAt':'2026-01-01','publishedAt':'','publisher':'发布者','media':{'platform':'bilibili','textStatus':'missing'}}
  self.assertEqual(article_records(article,{'id':'v'},True),[])
  old={**article,'id':'old-drill','resourceKind':'video-lead'}
  items,_,_=merge_feed({'items':[old]},[]);self.assertEqual(items,[])
 def test_single_video_failure_does_not_report_success(self):
  with patch('platform_media.read_video',side_effect=RuntimeError('登录限制')):
   records,run=collect_platform({'id':'v','name':'视频','type':'video','url':'https://www.douyin.com/video/123'})
  self.assertEqual(records,[]);self.assertEqual(run['status'],'failure');self.assertEqual(run['httpStatus'],0)

if __name__=='__main__':unittest.main()
