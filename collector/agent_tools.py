"""Bounded tools used by the local conversational agent. JSON in/out only."""
import json
import sys
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup
from crawl import fetch, discovery_title, crawl_search, article_data
from trendradar_bridge import fetch_rss
from source_suggestions import suggest_sources

request=json.load(sys.stdin)
if request.get('operation')=='web_search':
    query=str(request.get('query','')).strip()
    if not query or len(query)>200:raise ValueError('检索词须为1–200字')
    source={'id':'web-discovery','name':'助手主动检索','publisher':'发布主体待核验','type':'search','province':'全国','url':'https://html.duckduckgo.com/html/','query':query,'maxArticles':8}
    with tempfile.TemporaryDirectory(prefix='radar-agent-search-') as directory:
        records,run=crawl_search(source,Path(directory))
        sources=request.get('sources',[])
        suggestions=suggest_sources(records,sources,fetch,discovery_title,limit=3,verify_article=lambda soup,url:bool(article_data(soup,url,{'publisher':'待核验','id':'probe'})))
    # Full original text remains bounded and carries explicit provenance.
    print(json.dumps({'records':records,'run':run,'sourceSuggestions':suggestions},ensure_ascii=False))
elif request.get('operation')=='probe_source':
    source=request['source']
    if source['type']=='rss':
        # TrendRadar logs are redirected so stdout remains one JSON object.
        import contextlib,io
        with contextlib.redirect_stdout(io.StringIO()):items=fetch_rss(source)
        print(json.dumps({'ready':True,'articles':len(items),'method':'TrendRadar RSSFetcher'},ensure_ascii=False))
    else:
        soup,effective,_=fetch(source['url'])
        if source['type'] in ['article','wechat']:
            article_data(soup,effective,source)
        elif not soup.find('a',href=True):
            raise ValueError('未发现可扫描的栏目链接')
        print(json.dumps({'ready':True,'url':effective,'method':'单篇原文' if source['type']!='listing' else '网页栏目'},ensure_ascii=False))
else:
    raise ValueError('不支持的操作')
