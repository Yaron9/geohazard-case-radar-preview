"""Platform-owned WeChat/video discovery and extraction, shared by radar and agent."""
import hashlib
import html
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, urljoin, urlencode, parse_qs, quote
from bs4 import BeautifulSoup

VIDEO_HOSTS=('douyin.com','bilibili.com','b23.tv','youtube.com','youtu.be')
CHANNELS=('web','wechat','video')


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def platform_of(url):
    p=urlsplit(url)
    if p.scheme not in ('http','https') or p.username or p.password:
        raise ValueError('媒体须为不含凭据的公开HTTP(S)链接')
    host=(p.hostname or '').lower()
    if host=='mp.weixin.qq.com':return 'wechat'
    for domain,platform in [('douyin.com','douyin'),('bilibili.com','bilibili'),('b23.tv','bilibili'),('youtube.com','youtube'),('youtu.be','youtube')]:
        if host==domain or host.endswith('.'+domain):return platform
    raise ValueError('首版支持微信公众号、抖音、B站、YouTube链接，其他平台尚未适配')


def canonical_media_url(url):
    p=urlsplit(url)
    if p.hostname=='mp.weixin.qq.com':
        values=parse_qs(p.query)
        if all(k in values for k in ['__biz','mid','idx']):
            return urlunsplit(('https',p.netloc,p.path,urlencode({k:values[k][0] for k in ['__biz','mid','idx','sn'] if k in values}),''))
        if re.match(r'^/s/[\w-]+$',p.path):return urlunsplit(('https',p.netloc,p.path,'',''))
    return urlunsplit((p.scheme,p.netloc,p.path,p.query,''))


def browser_status():
    try:
        result=subprocess.run(['node','collector/platform-browser.mjs'],input='{"operation":"status"}',capture_output=True,text=True,timeout=12,check=True)
        status=json.loads(result.stdout)
        return {'available':status.get('available',False),'library':status.get('library',False)}
    except Exception:
        return {'available':False,'library':False}


def capabilities():
    browser=browser_status()
    return {'wechat':{'search':True,'reader':True,'browser':browser['available'],'scope':'公开文章与关键词检索，不是账号全量历史'},'video':{'metadata':importlib.util.find_spec('yt_dlp') is not None,'captions':importlib.util.find_spec('yt_dlp') is not None,'platforms':['douyin','bilibili','youtube'],'transcription':False,'transcriptionReason':'平台尚未配置音频转写；无字幕视频保存为待补证线索'},'monitoring':'可保存关键词检索规则，账号时间线不作全量承诺'}


def read_wechat(url):
    from crawl import fetch, article_data
    if platform_of(url)!='wechat':raise ValueError('不是公众号文章链接')
    failures=[]
    try:
        soup,effective,_=fetch(url)
        node=soup.select_one('#js_content')
        if not node or len(node.get_text(strip=True))<50:raise ValueError('未取得公众号正文，可能为验证页')
        account=soup.select_one('#js_name')
        name=account.get_text(' ',strip=True) if account else ''
        article=article_data(soup,effective,{'id':'wechat-discovery','publisher':name or '公众号主体待核验','bodySelectors':['#js_content']})
        published=soup.select_one('#publish_time')
        published_text=published.get_text(' ',strip=True) if published else ''
        match=re.search(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})',published_text)
        if match and not article['publishedAt']:article['publishedAt']='-'.join([match[1],match[2].zfill(2),match[3].zfill(2)])
        return {**article,'url':canonical_media_url(effective),'media':{'platform':'wechat','accountName':name,'publishedText':published_text,'textStatus':'full','reader':'public-html'}}
    except Exception as error:
        failures.append(str(error))
    request={'operation':'wechat','url':url}
    result=subprocess.run(['node','collector/platform-browser.mjs'],input=json.dumps(request),capture_output=True,text=True,timeout=45)
    if result.returncode:
        message=result.stderr.splitlines()
        detail=next((line for line in message if 'Error:' in line),'平台浏览器不可用或文章访问受限')
        raise RuntimeError('公众号读取受限：'+detail[:200]+'；公开页：'+failures[0][:120])
    data=json.loads(result.stdout)
    soup=BeautifulSoup(data['html'],'html.parser')
    article=article_data(soup,data['url'],{'id':'wechat-discovery','publisher':data.get('account') or '公众号主体待核验','bodySelectors':['#js_content']})
    published=data.get('publishedAt','')
    match=re.search(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})',published)
    if match and not article['publishedAt']:article['publishedAt']='-'.join([match[1],match[2].zfill(2),match[3].zfill(2)])
    return {**article,'url':canonical_media_url(data['url']),'media':{'platform':'wechat','accountName':data.get('account',''),'publishedText':published,'textStatus':'full','reader':'platform-browser'}}


def resolve_wechat_link(url,fetch):
    if urlsplit(url).hostname=='mp.weixin.qq.com':return canonical_media_url(url)
    if urlsplit(url).hostname not in ['weixin.sogou.com','www.sogou.com']:raise ValueError('不是已声明的微信搜索跳转')
    _,effective,raw=fetch(url)
    if urlsplit(effective).hostname=='mp.weixin.qq.com':return canonical_media_url(effective)
    text=raw.decode('utf-8',errors='replace')
    parts=re.findall(r"url\s*\+=\s*'([^']*)'",text)
    candidates=[''.join(parts).replace('@',''),*re.findall(r'https?://mp\.weixin\.qq\.com/[^\s\"<>]+',text)]
    for candidate in candidates:
        candidate=html.unescape(candidate).replace('\\x26','&').replace('\\/','/')
        if urlsplit(candidate).hostname=='mp.weixin.qq.com':return canonical_media_url(candidate)
    raise RuntimeError('微信搜索跳转未解析为公众号原文，可能需要验证')


def search_wechat(query,limit=3):
    from crawl import fetch
    url='https://weixin.sogou.com/weixin?'+urlencode({'type':'2','query':query,'page':1})
    trace={'provider':'搜狗微信','query':query,'url':url,'status':'success','returned':0,'relevant':0}
    candidates=[]
    try:
        soup,_,_=fetch(url)
        entries=soup.select('li[id^="sogou_vr_11002601_box_"]') or soup.select('ul.news-list li')
        trace['returned']=len(entries)
        if not entries:
            trace.update(status='partial',error='未返回可解析公众号条目，可能为验证页或无匹配，不能据此认定已覆盖公众号')
        for entry in entries[:max(1,min(limit,5))]:
            anchor=entry.select_one('h3 a')
            if not anchor:continue
            try:
                original=resolve_wechat_link(urljoin(url,quote(anchor.get('href',''),safe='/:?&=%+')),fetch)
                snippet=entry.select_one('.txt-info');account=entry.select_one('.all-time-y2') or entry.select_one('.account')
                candidates.append({'url':original,'title':anchor.get_text(' ',strip=True),'snippet':snippet.get_text(' ',strip=True) if snippet else '', 'accountName':account.get_text(' ',strip=True) if account else ''})
            except Exception as error:
                trace.update(status='partial',error=str(error)[:180])
                trace.setdefault('unresolved',[]).append({'title':anchor.get_text(' ',strip=True),'accountName':(entry.select_one('.all-time-y2').get_text(' ',strip=True) if entry.select_one('.all-time-y2') else ''),'reason':str(error)[:160]})
        trace['relevant']=len(candidates)
    except Exception as error:trace.update(status='failure',error=str(error)[:200])
    return candidates,[trace]


def seconds(value):
    parts=value.replace(',','.').split(':')
    return sum(float(part)*60**i for i,part in enumerate(reversed(parts)))


def parse_captions(raw,extension):
    if extension=='json3':
        data=json.loads(raw)
        return [{'start':event.get('tStartMs',0)/1000,'end':(event.get('tStartMs',0)+event.get('dDurationMs',0))/1000,'text':''.join(s.get('utf8','') for s in event.get('segs',[])).strip()} for event in data.get('events',[]) if any(s.get('utf8','').strip() for s in event.get('segs',[]))][:300]
    text=raw.decode('utf-8',errors='replace') if isinstance(raw,bytes) else raw
    segments=[]
    for block in re.split(r'\n\s*\n',text.replace('\r','')):
        match=re.search(r'((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n([\s\S]*)',block)
        if match:
            body=BeautifulSoup(match[3],'html.parser').get_text(' ',strip=True)
            if body and (not segments or segments[-1]['text']!=body):segments.append({'start':seconds(match[1]),'end':seconds(match[2]),'text':body})
    return segments[:300]


def caption_text(segments):
    lines=[]
    for segment in segments:
        n=int(segment['start']);label=f'{n//3600:02}:{n//60%60:02}:{n%60:02}'
        lines.append(f'[{label}] {segment["text"]}')
    return '\n'.join(lines)[:6000]


def read_video(url):
    from crawl import fetch
    platform=platform_of(url)
    if platform=='wechat':raise ValueError('应使用公众号读取器')
    try:import yt_dlp
    except ImportError:raise RuntimeError('平台缺少视频解析器，请安装collector/requirements-platform.txt')
    class QuietLogger:
        def debug(self,message):pass
        def warning(self,message):pass
        def error(self,message):pass
    options={'quiet':True,'no_warnings':True,'skip_download':True,'writesubtitles':True,'writeautomaticsub':True,'ignore_no_formats_error':True,'noplaylist':True,'socket_timeout':12,'retries':0,'extractor_retries':0,'logger':QuietLogger()}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info=downloader.extract_info(url,download=False)
    except Exception as error:
        soup,effective,_=fetch(url)
        title_node=soup.select_one('meta[property="og:title"]');description_node=soup.select_one('meta[property="og:description"]') or soup.select_one('meta[name="description"]')
        title=(title_node.get('content') or '').strip() if title_node else ''
        if not title or title in ['抖音','抖音-记录美好生活','哔哩哔哩 (゜-゜)つロ 干杯~-bilibili']:raise RuntimeError('视频解析受限，可能需要平台授权或更新适配：'+str(error)[:180])
        platform_of(effective)
        info={'title':title,'description':description_node.get('content','') if description_node else '', 'webpage_url':effective,'id':urlsplit(effective).path.rstrip('/').split('/')[-1],'readerWarning':str(error)[:180]}
    if not info or info.get('_type')=='playlist':raise RuntimeError('首版解析单个视频，不自动遍历创作者全部视频')
    if not info.get('title'):raise RuntimeError('未取得可核验视频标题，未保存为有效材料')
    original=info.get('webpage_url') or url
    platform_of(original)
    segments=[];caption_status='missing';caption_errors=[];language=''
    for field in ['subtitles','automatic_captions']:
        captions=info.get(field) or {}
        for lang in sorted(captions,key=lambda key:(not key.startswith('zh'),not key.startswith('en'),key)):
            formats=sorted(captions[lang],key=lambda f:{'json3':0,'vtt':1,'srt':2}.get(f.get('ext'),99))
            for item in formats[:2]:
                if item.get('ext') not in ['json3','vtt','srt']:continue
                try:
                    if item.get('data') is not None:raw=item['data']
                    else:_,_,raw=fetch(item['url'])
                    segments=parse_captions(raw,item['ext'])
                    if segments:caption_status='platform-caption' if field=='subtitles' else 'automatic-caption';language=lang;break
                except Exception as error:caption_errors.append(str(error)[:160])
            if segments:break
        if segments:break
    uploaded=info.get('upload_date') or ''
    published=f'{uploaded[:4]}-{uploaded[4:6]}-{uploaded[6:]}' if re.fullmatch(r'\d{8}',uploaded) else ''
    media={'platform':platform,'videoId':str(info.get('id','')),'accountName':info.get('uploader') or info.get('channel') or '', 'accountId':info.get('channel_id') or info.get('uploader_id') or '', 'duration':info.get('duration'),'textStatus':caption_status,'language':language,'segments':segments,'captionErrors':caption_errors,'reader':'public-metadata' if info.get('readerWarning') else 'yt-dlp','readerWarning':info.get('readerWarning',''),'originalShareUrl':url}
    return {'title':info.get('title') or '', 'url':original,'publishedAt':published,'publisher':media['accountName'] or platform+'发布主体待核验','capturedAt':timestamp(),'body':caption_text(segments),'description':(info.get('description') or '')[:1200],'media':media}


def search_videos(query,platform='all',limit=3):
    from crawl import fetch
    from web_search import result_links
    candidates=[];traces=[]
    if platform in ['all','bilibili']:
        url='https://api.bilibili.com/x/web-interface/search/type?'+urlencode({'search_type':'video','keyword':query,'page':1})
        trace={'provider':'B站搜索','query':query,'url':url,'status':'success','returned':0,'relevant':0}
        try:
            _,_,raw=fetch(url);data=json.loads(raw)
            if data.get('code')!=0:raise RuntimeError(f'站内搜索受限：{data.get("code")}')
            results=(data.get('data') or {}).get('result') or [];trace['returned']=len(results)
            for item in results[:limit]:
                if re.fullmatch(r'BV[\w]+',item.get('bvid','')):candidates.append({'url':'https://www.bilibili.com/video/'+item['bvid'],'title':BeautifulSoup(item.get('title',''),'html.parser').get_text(' ',strip=True),'snippet':item.get('description',''),'accountName':item.get('author','')})
            trace['relevant']=len(candidates)
        except Exception as error:trace.update(status='failure',error=str(error)[:180])
        traces.append(trace)
    target={'douyin':'site:douyin.com/video','youtube':'site:youtube.com/watch','all':'site:douyin.com/video OR site:bilibili.com/video'}.get(platform)
    if target and len(candidates)<limit:
        term=query+' '+target
        for provider,base in [('DuckDuckGo','https://html.duckduckgo.com/html/'),('搜狗','https://www.sogou.com/web')]:
            url=base+'?'+urlencode({'q':term} if provider=='DuckDuckGo' else {'query':term})
            trace={'provider':provider+'视频发现','query':term,'url':url,'status':'success','returned':0,'relevant':0}
            try:
                soup,_,_=fetch(url);links=result_links(soup,provider,base);trace['returned']=len(links)
                for link,title in links:
                    if len(candidates)>=limit:break
                    try:
                        if provider=='搜狗':_,link,_=fetch(link)
                        found=platform_of(link)
                        if found=='wechat' or (platform!='all' and found!=platform):continue
                        if link not in [c['url'] for c in candidates]:candidates.append({'url':link,'title':title,'snippet':'','accountName':''});trace['relevant']+=1
                    except Exception:continue
                if not trace['relevant']:trace.update(status='partial',error='未发现可解析视频链接，可能被验证页限制')
            except Exception as error:trace.update(status='failure',error=str(error)[:180])
            traces.append(trace)
            if trace['relevant']:break
    return candidates[:limit],traces


def article_records(article,source,lead=False):
    from crawl import split_report,digest,HAZARDS,REGIONS,GEO_TOPIC,ACTION_TOPIC
    text=article.get('body','');title=article.get('title','')
    if not (GEO_TOPIC.search(title+' '+text+' '+article.get('description','')) or re.search(r'避险|避灾',title)):return []
    prepared={**article,'sourceId':source['id'],'reportTitle':title}
    if not lead:
        records=split_report(prepared,source.get('province','全国'))
        if records:return [{**r,'media':article.get('media'),'fingerprint':digest(r['body']+'\n'+json.dumps(article.get('media') or {},ensure_ascii=False,sort_keys=True))} for r in records]
    hazard=next((h for h in HAZARDS if h in title+' '+text),'')
    body=text or f'媒体检索线索：{title}。尚未取得可核验正文或字幕，不据此确认人数、伤亡或处置成效。'
    resource='article-lead' if article.get('media',{}).get('platform')=='wechat' else 'video-lead'
    return [{**prepared,'id':'live-'+digest(article['url']+'::0')[:16],'body':body[:6000],'summary':('待补证线索：'+title+'；未取得正文或字幕。') if lead else body[:400],'resourceKind':resource if lead else 'report','section':0,'province':source.get('province','全国'),'hazard':hazard,'eventDate':'','fingerprint':digest(body+'\n'+json.dumps(article.get('media') or {},ensure_ascii=False,sort_keys=True)),'firstSeenAt':article['capturedAt'],'version':1,'evidence':[{'label':label,'quote':'','confirmed':False} for label in ['风险发现','提前行动','风险验证','避险成效']]}]


def source_suggestion(article):
    media=article.get('media',{});platform=media.get('platform');query=media.get('accountName') or article['title']
    kind='wechat-search' if platform=='wechat' else 'video-search'
    url=('https://weixin.sogou.com/weixin?' if platform=='wechat' else 'https://www.sogou.com/web?')+urlencode({'query':query,**({'type':'2'} if platform=='wechat' else {'platform':platform or 'all'})})
    sid='media-rule-'+hashlib.sha256((kind+url).encode()).hexdigest()[:12]
    return {'id':sid,'status':'ready','reason':'添加为关键词检索规则，持续发现公开材料；不代表账号全量订阅。','evidenceUrl':article['url'],'evidenceTitle':article['title'],'source':{'id':sid,'name':('公众号' if platform=='wechat' else '视频')+'检索·'+query[:40],'publisher':media.get('accountName') or '待核验','category':'微信公众号' if platform=='wechat' else '短视频','type':kind,'url':url,'query':query,'videoPlatform':platform if platform in ['douyin','bilibili','youtube'] else 'all','province':'全国','enabled':True,'pendingAdapter':False}}


def collect_platform(source):
    started=timestamp();kind=source['type'];limit=min(5,max(1,int(source.get('maxArticles',3))));query=(source.get('query') or ' '.join(source.get('keywords') or [])).strip()
    traces=[];failures=[];records=[];suggestions=[];successful_reads=0
    if kind in ['wechat-search','video-search']:
        if not query or len(query)>200:raise ValueError('公众号/视频检索规则需要1–200字关键词')
        candidates,traces=search_wechat(query,limit) if kind=='wechat-search' else search_videos(query,source.get('videoPlatform','all'),limit)
    else:candidates=[{'url':source['url'],'title':source['name'],'snippet':'','accountName':source.get('publisher','')}]
    for candidate in candidates:
        try:
            article=read_wechat(candidate['url']) if kind in ['wechat','wechat-search'] else read_video(candidate['url'])
            successful_reads+=1
            lead=article['media'].get('textStatus')=='missing'
            if lead:failures.append({'url':article['url'],'message':'已取得视频信息，但无可用字幕；平台尚未配置音频转写，保留待补证线索'})
            found=article_records(article,source,lead);records.extend(found)
            if found:suggestions.append(source_suggestion(article))
        except Exception as error:
            failures.append({'url':candidate['url'],'message':str(error)[:300]})
            if kind in ['wechat-search','video-search']:
                article={**candidate,'publisher':candidate.get('accountName') or '发布主体待核验','capturedAt':timestamp(),'publishedAt':'','body':'','media':{'platform':'wechat' if kind=='wechat-search' else source.get('videoPlatform','video'),'textStatus':'missing','accountName':candidate.get('accountName','')}}
                records.extend(article_records(article,source,True))
    for trace in traces:
        if trace['status']!='success':failures.append({'url':trace['url'],'message':trace.get('error','渠道受限')})
    run={'sourceId':source['id'],'name':source['name'],'url':source['url'],'startedAt':started,'finishedAt':timestamp(),'status':('failure' if not traces and not successful_reads else 'partial') if failures else ('success' if traces or successful_reads else 'partial'),'httpStatus':200 if successful_reads or any(t['status']=='success' for t in traces) else 0,'pagesScanned':len(traces)+len(candidates),'recordsFound':len(records),'failures':failures,'queries':traces,'engine':'公众号适配' if kind.startswith('wechat') else 'yt-dlp/视频发现','discoveredLinks':len(candidates),'sourceSuggestions':suggestions}
    return records,run
