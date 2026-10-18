"""Bounded, platform-owned tools shared by conversational agent and radar."""
import concurrent.futures
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from crawl import fetch, discovery_title, crawl_search, article_data
from trendradar_bridge import fetch_rss
from source_suggestions import suggest_sources
from platform_media import capabilities,collect_platform,platform_of,timestamp


def search(request):
    query=str(request.get('query','')).strip()
    if not query or len(query)>200:raise ValueError('检索词须为1–200字')
    channels=request.get('channels', ['web'])
    if not isinstance(channels,list) or not channels or any(c not in ['web','wechat','video'] for c in channels):raise ValueError('检索渠道无效')
    channels=list(dict.fromkeys(channels));sources=[]
    if 'web' in channels:sources.append({'id':'web-discovery','name':'助手网页检索','publisher':'发布主体待核验','type':'search','province':'全国','url':'https://html.duckduckgo.com/html/','query':query,'maxArticles':4})
    if 'wechat' in channels:sources.append({'id':'wechat-discovery','name':'助手公众号检索','publisher':'账号待核验','category':'微信公众号','type':'wechat-search','province':'全国','url':'https://weixin.sogou.com/weixin?'+urlencode({'type':'2','query':query}),'query':query,'maxArticles':2})
    if 'video' in channels:sources.append({'id':'video-discovery','name':'助手视频检索','publisher':'作者待核验','category':'短视频','type':'video-search','province':'全国','url':'https://www.sogou.com/web?'+urlencode({'query':query+' 视频'}),'query':query,'videoPlatform':request.get('platform','all'),'maxArticles':2})
    records=[];runs=[];suggestions=[];started=timestamp()
    def collect(source):
        if source['type']!='search':return collect_platform(source)
        with tempfile.TemporaryDirectory(prefix='radar-agent-search-') as directory:
            found,run=crawl_search(source,Path(directory))
            run['sourceSuggestions']=suggest_sources(found,request.get('sources',[]),fetch,discovery_title,limit=1,verify_article=lambda soup,url:bool(article_data(soup,url,{'publisher':'待核验','id':'probe'})))
            return found,run
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(collect,source):source for source in sources}
        for future in concurrent.futures.as_completed(futures):
            source=futures[future]
            try:found,run=future.result();records.extend(found)
            except Exception as error:run={'sourceId':source['id'],'name':source['name'],'url':source['url'],'startedAt':started,'finishedAt':timestamp(),'status':'failure','httpStatus':0,'recordsFound':0,'pagesScanned':0,'failures':[{'url':source['url'],'message':str(error)[:260]}]}
            runs.append(run);suggestions.extend(run.get('sourceSuggestions',[]))
    run={'sourceId':'agent-discovery','name':'平台主动检索','url':'','startedAt':started,'finishedAt':timestamp(),'status':'success' if all(r['status']=='success' for r in runs) else 'partial' if records or any(r['status']!='failure' for r in runs) else 'failure','httpStatus':200 if any(r['httpStatus']==200 for r in runs) else 0,'pagesScanned':sum(r['pagesScanned'] for r in runs),'recordsFound':len(records),'failures':[f for r in runs for f in r['failures']],'results':sorted(runs,key=lambda r:r['sourceId']),'channels':channels}
    return {'records':records,'run':run,'sourceSuggestions':list({s['id']:s for s in suggestions}.values())}


def main(request):
    operation=request.get('operation')
    if operation=='capabilities':return capabilities()
    if operation in ['web_search','search_wechat','search_videos']:
        if operation=='search_wechat':request={**request,'channels':['wechat']}
        if operation=='search_videos':request={**request,'channels':['video']}
        return search(request)
    if operation=='read_media':
        url=request['url'];platform=platform_of(url);source={'id':'wechat-discovery' if platform=='wechat' else 'video-discovery','name':'助手媒体链接读取','publisher':'主体待核验','type':'wechat' if platform=='wechat' else 'video','province':'全国','url':url}
        records,run=collect_platform(source)
        return {'records':records,'run':run,'sourceSuggestions':run.get('sourceSuggestions',[])}
    if operation=='probe_source':
        source=request['source']
        if source['type'] in ['wechat-search','video-search']:
            query=str(source.get('query','')).strip()
            if not query or len(query)>200:raise ValueError('关键词规则需要1–200字查询词')
            return {'ready':True,'method':'公众号关键词检索' if source['type']=='wechat-search' else '视频关键词检索','note':'规则已登记，访问状态以每次扫描结果为准；不是账号全量订阅'}
        if source['type'] in ['wechat','video']:
            records,run=collect_platform(source)
            if run['status']=='failure':raise ValueError(run['failures'][0]['message'])
            return {'ready':True,'method':run['engine'],'recordsFound':len(records),'note':'未取得正文或字幕时只保存待补证线索'}
        if source['type']=='rss':
            with contextlib.redirect_stdout(io.StringIO()):items=fetch_rss(source)
            return {'ready':True,'articles':len(items),'method':'TrendRadar RSSFetcher'}
        soup,effective,_=fetch(source['url'])
        if source['type']=='article':article_data(soup,effective,source)
        elif not soup.find('a',href=True):raise ValueError('未发现可扫描的栏目链接')
        return {'ready':True,'url':effective,'method':'单篇原文' if source['type']=='article' else '网页栏目'}
    raise ValueError('不支持的操作')


if __name__=='__main__':
    print(json.dumps(main(json.load(sys.stdin)),ensure_ascii=False))
