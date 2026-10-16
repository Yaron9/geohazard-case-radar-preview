import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
from crawl import article_data, canonical_url, merge_feed, split_report, allowed_article_url, discovery_title, crawl_rss, crawl_search
from bs4 import BeautifulSoup

class CollectorTests(unittest.TestCase):
    def test_official_metadata_and_compilation(self):
        first='2024年6月16日，福建发生滑坡。巡查发现裂缝，立即报告并组织转移，无人员伤亡。'*4
        second='2024年7月10日，湖北发生滑坡。群众提前撤离，现场持续监测并封控道路，无人员伤亡。'*4
        html=f'<meta name="ArticleTitle" content="年度成功避险典型案例"><meta name="PubDate" content="2025-05-12 11:20:00"><div class="TRS_Editor"><p>1.福建松溪滑坡灾害避险</p><p>{first}</p><p>2.湖北秭归滑坡灾害避险</p><p>{second}</p></div>'
        article=article_data(BeautifulSoup(html,'html.parser'),'https://www.cgs.gov.cn/report.html',{'publisher':'发布机构','id':'test'})
        records=split_report(article)
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['publishedAt'],'2025-05-12')
        self.assertEqual(records[0]['eventDate'],'2024-06-16')
        self.assertEqual(records[0]['url'],records[1]['url'])
        self.assertFalse(any(e['confirmed'] for r in records for e in r['evidence']))
        self.assertTrue(all(e['quote'] in r['body'] for r in records for e in r['evidence'] if e['quote']))
    def test_incremental_and_version_history(self):
        record={'id':'a','fingerprint':'one','body':'原文','capturedAt':'t1','firstSeenAt':'t1','version':1,'publishedAt':'2024-01-01'}
        items,added,changed=merge_feed({'items':[]},[record.copy()])
        self.assertEqual((added,changed),(1,0))
        repeated,added,changed=merge_feed({'items':items},[record.copy()])
        self.assertEqual((len(repeated),added,changed),(1,0,0))
        newer={**record,'fingerprint':'two','body':'正文更新','capturedAt':'t2','firstSeenAt':'t2'}
        updated,added,changed=merge_feed({'items':items},[newer])
        self.assertEqual((added,changed),(0,1))
        self.assertEqual(updated[0]['version'],2)
        self.assertEqual(updated[0]['history'][0]['body'],'原文')
        self.assertEqual(updated[0]['firstSeenAt'],'t1')
    def test_local_media_titles_and_allowed_subdomains(self):
        self.assertTrue(discovery_title('湖南通报年度十大转移避险避灾案例'))
        self.assertTrue(discovery_title('发现山体裂缝，村民连夜撤离'))
        self.assertTrue(discovery_title('巡查发现滑坡险情，及时组织转移'))
        self.assertFalse(discovery_title('公告：地质灾害防治资质审批结果'))
        source={'allowedHosts':['rednet.cn']}
        self.assertTrue(allowed_article_url('https://moment.rednet.cn/a.html',source,'https://hn.rednet.cn/'))
        self.assertFalse(allowed_article_url('https://rednet.cn.evil.example/a.html',source,'https://hn.rednet.cn/'))
        self.assertFalse(allowed_article_url('https://other.example/a.html',source,'https://hn.rednet.cn/'))
    def test_short_case_index_does_not_borrow_overall_numbers(self):
        body='全省避免伤亡6590人次。\n1.长沙宁乡山体崩塌成功避险案例\n2.益阳安化山体滑坡成功避险案例\n来源：湖南日报'
        article={'title':'湖南通报十大转移避险避灾案例','body':body,'url':'https://hn.rednet.cn/case.html','publishedAt':'2026-10-13','sourceId':'local','publisher':'红网','capturedAt':'t'}
        records=split_report(article,'湖南')
        self.assertEqual(len(records),2)
        self.assertTrue(all(r['resourceKind']=='index-entry' for r in records))
        self.assertTrue(all('6590' not in r['body'] for r in records))
        self.assertTrue(all(not e['quote'] and not e['confirmed'] for r in records for e in r['evidence']))
    def test_wechat_body_and_title_are_supported_without_claiming_account_history(self):
        text='巡查人员发现滑坡裂缝，立即组织群众转移避让。' * 8
        soup=BeautifulSoup(f'<h2 id="activity-name">公开公众号滑坡避险报道</h2><div id="js_content">{text}</div>','html.parser')
        article=article_data(soup,'https://mp.weixin.qq.com/s/example',{'id':'wechat','publisher':'待核验公众号'})
        self.assertEqual(article['title'],'公开公众号滑坡避险报道')
        self.assertIn('巡查人员',article['body'])
        self.assertEqual(article['publishedAt'],'')
    def test_rss_reads_original_report_on_another_publisher_host(self):
        rss='<rss><channel><item><title>发现滑坡裂缝，组织群众转移</title><link>https://county.example.org/report.html</link></item></channel></rss>'.encode()
        article=('<h1>发现滑坡裂缝，组织群众转移</h1><article>'+('2024年7月1日发现滑坡裂缝，立即组织群众转移，无人员伤亡。'*8)+'</article>').encode()
        source={'id':'rss','name':'RSS','type':'rss','url':'https://feeds.example.org/rss','publisher':'','province':'全国'}
        responses=[(None,source['url'],rss),(BeautifulSoup(article,'html.parser'),'https://county.example.org/report.html',article)]
        with tempfile.TemporaryDirectory() as directory,patch('crawl.fetch',side_effect=responses):
            records,run=crawl_rss(source,Path(directory))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['url'],'https://county.example.org/report.html')
        self.assertEqual(records[0]['publisher'],'county.example.org')
        self.assertEqual(run['pagesScanned'],2)
    def test_search_irrelevant_results_remain_visible_and_do_not_become_reports(self):
        raw=b'<rss><channel><item><title>Unrelated news</title><link>https://example.org/unrelated</link></item></channel></rss>'
        source={'id':'web-discovery','name':'Search','type':'search','url':'https://www.bing.com/search?q=test','query':'地质灾害 成功避险'}
        with tempfile.TemporaryDirectory() as directory,patch.dict('os.environ',{'TAVILY_API_KEY':''}),patch('crawl.fetch',return_value=(None,source['url'],raw)):
            records,run=crawl_search(source,Path(directory))
        self.assertEqual(records,[])
        self.assertEqual(run['status'],'partial')
        self.assertIn('不能据此声称',run['failures'][0]['message'])
    def test_unsafe_url_and_invalid_body(self):
        for url in ['javascript:alert(1)','https://user:pass@example.com/a','file:///etc/passwd']:
            with self.assertRaises(ValueError):canonical_url(url)
        with self.assertRaises(RuntimeError):article_data(BeautifulSoup('<title>验证页</title>','html.parser'),'https://example.org',{'publisher':'p','id':'s'})
    def test_news_without_success_is_not_a_case(self):
        article={'title':'召开地质灾害工作会议','body':'会议部署了滑坡防范工作。'*20,'url':'https://example.org/meeting','publishedAt':'','sourceId':'s','publisher':'p','capturedAt':'t'}
        self.assertEqual(split_report(article),[])

if __name__=='__main__':unittest.main()
