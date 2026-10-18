import unittest
from unittest.mock import Mock
from bs4 import BeautifulSoup
from web_search import discover, query_plan, result_links
from source_suggestions import suggest_sources


def page(html):
    return BeautifulSoup(html, 'html.parser')


class DiscoveryTests(unittest.TestCase):
    def test_query_expansion_preserves_user_constraints(self):
        query = '云南 2020-2025 泥石流'
        self.assertTrue(all(query in q for q in query_plan(query)))

    def test_web_search_finds_unregistered_domain_and_keeps_query_trace(self):
        fetch = Mock(return_value=(page('<a class="result__a" href="https://unknown.example/news/1">滑坡提前撤离</a>'), '', b''))
        links, traces = discover('云南 滑坡', fetch, lambda title: '撤离' in title)
        self.assertEqual(links, [('https://unknown.example/news/1', '滑坡提前撤离')])
        self.assertEqual(len(traces), 6)
        self.assertTrue(all(t['provider'] == 'DuckDuckGo' for t in traces))

    def test_provider_failure_is_visible_with_fallback(self):
        def fetch(url):
            if 'duckduckgo' in url:
                raise RuntimeError('HTTP 403')
            return page('<html>验证页</html>'), url, b''
        links, traces = discover('滑坡', fetch, lambda _: True)
        self.assertFalse(links)
        self.assertTrue(any(t['status'] == 'failure' for t in traces))
        self.assertTrue(any(t['provider'] == '搜狗' for t in traces))

    def test_decode_engine_redirect_to_original(self):
        soup = page('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.example%2Freport">报道</a>')
        self.assertEqual(result_links(soup, 'DuckDuckGo', 'https://html.duckduckgo.com/')[0][0], 'https://x.example/report')

    def test_source_without_monitoring_entrance_is_pending(self):
        fetch = Mock(side_effect=RuntimeError('HTTP 403'))
        report = {'url': 'https://county.example/story/1', 'title': '滑坡成功避险'}
        suggestion = suggest_sources([report], [], fetch, lambda _: True)[0]
        self.assertEqual(suggestion['status'], 'needs-adapter')
        self.assertFalse(suggestion['source']['enabled'])
        self.assertTrue(suggestion['source']['pendingAdapter'])

    def test_verified_rss_suggestion_and_exact_entrance_dedup(self):
        def fetch(url):
            raw = b'<rss version="2.0"><channel/></rss>' if url.endswith('feed.xml') else b'<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
            return page(raw), url, raw
        report = {'url': 'https://county.example/story/1', 'title': '滑坡成功避险'}
        result = suggest_sources([report], [{'url': 'https://county.example/another-channel/'}], fetch, lambda _: True)
        self.assertEqual(result[0]['source']['url'], 'https://county.example/feed.xml')
        self.assertTrue(result[0]['source']['enabled'])
        self.assertEqual(suggest_sources([report], [{'url': 'https://county.example/feed.xml'}], fetch, lambda _: True), [])

    def test_home_page_only_becomes_listing_when_it_links_to_fetched_report(self):
        report = {'url': 'https://county.example/story/1', 'title': '滑坡成功避险'}
        fetch = Mock(return_value=(page('<a href="/story/1">滑坡成功避险</a>'), 'https://county.example/', b''))
        result = suggest_sources([report], [], fetch, lambda title: '避险' in title)
        self.assertEqual(result[0]['status'], 'ready')
        self.assertEqual(result[0]['source']['type'], 'listing')


    def test_unverified_channels_on_same_host_are_not_merged(self):
        reports = [{'url': f'https://county.example/{channel}/report.html', 'title': '滑坡成功避险'} for channel in ['a', 'b']]
        result = suggest_sources(reports, [], Mock(side_effect=RuntimeError('unavailable')), lambda _: True)
        self.assertEqual(len(result), 2)
        self.assertNotEqual(result[0]['source']['id'], result[1]['source']['id'])

    def test_listing_does_not_add_implicit_keyword_requirements(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from crawl import crawl_source
        title='发现山体裂缝，村民连夜撤离'
        article=page('<h1>'+title+'</h1><article>'+('发现滑坡裂缝后组织群众转移，无人员伤亡。'*10)+'</article>')
        listing=page('<a href="/report.html">'+title+'</a>')
        source={'id':'s','name':'s','publisher':'s','type':'listing','url':'https://county.example/','province':'全国'}
        matcher=lambda title,keywords: not keywords or any(k in title for k in keywords)
        with tempfile.TemporaryDirectory() as directory, patch('crawl.fetch', side_effect=[(listing,source['url'],b'listing'),(article,'https://county.example/report.html',b'article')]), patch('trendradar_bridge.matches',side_effect=matcher):
            records, _=crawl_source(source,Path(directory))
        self.assertEqual(len(records),1)

    def test_rss_applies_record_limit_after_keyword_filter(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from crawl import crawl_trendradar_rss
        links=[(f'https://county.example/{i}', '普通新闻') for i in range(24)]+[('https://county.example/25','滑坡提前撤离')]
        with tempfile.TemporaryDirectory() as directory, patch('trendradar_bridge.fetch_rss',return_value=links), patch('trendradar_bridge.matches',return_value=True), patch('crawl.linked_reports',return_value=([],{})) as reports:
            crawl_trendradar_rss({'id':'s','maxArticles':1},Path(directory))
        self.assertEqual(reports.call_args.args[1],[('https://county.example/25','滑坡提前撤离')])


if __name__ == '__main__':
    unittest.main()
