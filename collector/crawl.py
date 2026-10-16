#!/usr/bin/env python3
"""Fetch public official reports; publish traceable candidates, never approved cases."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

HAZARDS = ['地面塌陷', '地面沉降', '地裂缝', '泥石流', '滑坡', '崩塌']
REGIONS = ['福建', '湖北', '广西', '重庆', '陕西', '湖南', '四川', '云南', '西藏', '甘肃', '贵州', '浙江', '广东', '江西', '河南', '河北', '山西', '山东', '江苏', '安徽', '北京', '上海', '天津', '辽宁', '吉林', '黑龙江', '内蒙古', '青海', '宁夏', '新疆', '海南']
BODY_SELECTORS = ['.TRS_Editor', '.TRS_UEDITOR', '#UCAP-CONTENT', '.pages_content', '#zoom', '.article-content', '.view-article', 'section.detail_article_content', 'article', '.news_content', '.detail-content', '.zw_txt']
EXCLUSIONS = re.compile(r'演练|会议|部署|宣传活动|科普直播|资质|审批|招标|采购|招聘')
DISCOVERY = re.compile(r'成功避险|成功避让|成功预警|转移避险|避险避灾|紧急转移|紧急撤离|连夜撤离|提前.{0,5}(撤离|转移)|地质灾害.{0,8}避险|滑坡.{0,8}避险|崩塌.{0,8}预警')
GEO_TOPIC = re.compile(r'地质灾害|地灾|滑坡|崩塌|泥石流|地面塌陷|地裂缝|地面沉降')
ACTION_TOPIC = re.compile(r'转移|撤离|疏散|避让|预警|封控|巡查|监测|搬迁|治理')


def discovery_title(title):
    return not EXCLUSIONS.search(title) and bool(DISCOVERY.search(title) or (GEO_TOPIC.search(title) and ACTION_TOPIC.search(title)))


def allowed_article_url(url, source, listing_url):
    hostname = (urlsplit(url).hostname or '').lower()
    allowed = source.get('allowedHosts') or [urlsplit(listing_url).hostname]
    return any(hostname == host or hostname.endswith('.' + host) for host in allowed if host)



def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ['http', 'https'] or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('来源URL必须为不含凭据的HTTP(S)地址')
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ''))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def fetch(url):
    url = canonical_url(url)
    with tempfile.TemporaryDirectory(prefix='geohazard-fetch-') as directory:
        output = Path(directory) / 'response'
        result = subprocess.run([
            'curl', '--compressed', '--location', '--proto', '=http,https', '--proto-redir', '=http,https',
            '--max-time', '25', '--connect-timeout', '10', '--max-redirs', '4', '--max-filesize', '6000000',
            '--silent', '--show-error', '--user-agent', 'GeoHazardCaseRadar/0.3 (+public-source-research)',
            '--write-out', '%{http_code}\n%{url_effective}', '--output', str(output), url,
        ], capture_output=True, text=True)
        lines = result.stdout.strip().splitlines()
        status = int(lines[0]) if lines and lines[0].isdigit() else 0
        effective = canonical_url(lines[1]) if len(lines) > 1 else url
        if result.returncode or status != 200:
            raise RuntimeError(f'HTTP {status}; {result.stderr.strip()[:200] or "请求未成功"}')
        raw = output.read_bytes()
        if not raw:
            raise RuntimeError('空响应')
        if raw.startswith(b'\x1f\x8b'):
            import gzip
            raw = gzip.decompress(raw)
        soup = BeautifulSoup(raw, 'html.parser')
        return soup, effective, raw


def metadata(soup, names):
    for meta in soup.find_all('meta'):
        if str(meta.get('name', meta.get('property', ''))).lower() in names and meta.get('content'):
            return meta['content'].strip()
    return ''


def article_data(soup, url, source):
    title = metadata(soup, ['articletitle', 'og:title'])
    if not title:
        heading = soup.find('h1')
        title = heading.get_text(' ', strip=True) if heading else soup.title.get_text(' ', strip=True) if soup.title else ''
    title = re.split(r'--中华人民共和国|_中国地质调查局', title)[0].strip()
    body = None
    for selector in [*source.get('bodySelectors', []), *BODY_SELECTORS]:
        candidate = soup.select_one(selector)
        if candidate and len(candidate.get_text(strip=True)) >= 100:
            body = candidate
            break
    if not body or not title:
        raise RuntimeError('未定位到可核验的标题与正文，可能为验证页或不支持的页面布局')
    for node in body.select('script,style,noscript,iframe,nav,footer'):
        node.decompose()
    text = body.get_text('\n', strip=True)
    if '\ufffd' in text[:500]:
        raise RuntimeError('正文编码异常，未作为有效材料')
    published = metadata(soup, ['pubdate', 'publishdate', 'date', 'article:published_time'])
    date_match = re.search(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})', published)
    if not date_match:
        # Some official templates put the publishing date in a visible metadata line.
        page_text = soup.get_text(' ', strip=True)
        date_match = re.search(r'(?:发布时间|发布日期|时间)[：:\s]*(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})', page_text)
    published = '-'.join([date_match[1], date_match[2].zfill(2), date_match[3].zfill(2)]) if date_match else ''
    credit = metadata(soup, ['source', 'content_source'])
    if not credit:
        match = re.search(r'(?:^|\n)来源[：:]\s*([^\n]{1,80})', text)
        credit = re.split(r'编辑|责任编辑', match[1])[0].strip() if match else ''
    return {'title': title, 'url': url, 'publishedAt': published, 'body': text, 'publisher': source['publisher'], 'sourceCredit': credit, 'sourceId': source['id'], 'capturedAt': timestamp()}


def split_report(article, province='全国'):
    body = article['body']
    headings = list(re.finditer(r'(?m)^\s*(\d{1,2})[.．、]\s*([^\n]{5,100}(?:避险|避让)[^\n]*)\s*$', body))
    sections = []
    if len(headings) >= 2:
        for i, heading in enumerate(headings):
            section_body = body[heading.end():headings[i+1].start() if i+1 < len(headings) else len(body)].strip()
            sections.append((heading[2].strip(), section_body, int(heading[1])))
    elif discovery_title(article['title']):
        # A notice merely listing many case names is an index, not a complete event.
        if not ('案例公布' in article['title'] and body.count('避险') > 7):
            sections.append((article['title'], body, 0))
    records = []
    for title, section, number in sections:
        index_entry = bool(number and len(section.strip()) < 100)
        if index_entry:
            section = title
        hazard = next((h for h in HAZARDS if h in title), next((h for h in HAZARDS if h in section), ''))
        if not hazard:
            continue
        if not number and not (ACTION_TOPIC.search(section) or DISCOVERY.search(section)):
            continue
        region = next((p for p in REGIONS if p in title[:15]), province)
        event_date = re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日', section[:250])
        event_date = '-'.join([event_date[1], event_date[2].zfill(2), event_date[3].zfill(2)]) if event_date else ''
        sentences = [s.strip() for s in re.split(r'(?<=[。；])\s*|\n+', section) if len(s.strip()) > 8]
        evidence = []
        for label, pattern in [('风险发现', r'发现|预警|裂缝|异常|险情'), ('提前行动', r'转移|撤离|疏散|避让|封控'), ('风险验证', r'发生.{0,15}(滑坡|崩塌|泥石流)|滑坡发生|灾害发生|监测|调查'), ('避险成效', r'无.{0,8}伤亡|避免.{0,20}伤亡|成功避险')]:
            quote = '' if index_entry else next((s for s in sentences if re.search(pattern, s)), '')
            evidence.append({'label': label, 'quote': quote[:600], 'confirmed': False})
        records.append({**article, 'id': 'live-' + digest(article['url'] + '::' + str(number))[:16], 'title': title, 'reportTitle': article['title'], 'body': section[:6000], 'summary': f'名录线索：{title}。原报道只列案例名称，缺少个案处置与结果细节，需继续补证。' if index_entry else '\n'.join(sentences[:2])[:500], 'resourceKind': 'index-entry' if index_entry else 'report', 'section': number, 'province': region, 'hazard': hazard, 'eventDate': event_date, 'evidence': evidence, 'fingerprint': digest(section), 'firstSeenAt': article['capturedAt'], 'version': 1})
    return records


def crawl_source(source, archive):
    started = timestamp()
    results, failures = [], []
    soup, effective, raw = fetch(source['url'])
    archive.mkdir(parents=True, exist_ok=True)
    (archive / (digest(source['url'])[:20] + '.html')).write_bytes(raw)
    if source['type'] == 'article':
        results.extend(split_report(article_data(soup, effective, source), source['province']))
        scanned = 1
    else:
        urls = []
        for anchor in soup.find_all('a', href=True):
            title = anchor.get('title') or anchor.get_text(' ', strip=True)
            if not discovery_title(title):
                continue
            try:
                candidate = canonical_url(urljoin(effective, anchor['href']))
            except ValueError:
                continue
            if not allowed_article_url(candidate, source, effective):
                continue
            if candidate not in urls:
                urls.append(candidate)
        urls = urls[:source.get('maxArticles', 6)]
        scanned = 1
        for url in urls:
            try:
                article_soup, article_url, article_raw = fetch(url)
                if not allowed_article_url(article_url, source, effective):
                    raise RuntimeError('文章重定向超出登记媒体域名范围')
                (archive / (digest(url)[:20] + '.html')).write_bytes(article_raw)
                results.extend(split_report(article_data(article_soup, article_url, source), source['province']))
                scanned += 1
            except Exception as exc:
                failures.append({'url': url, 'message': str(exc)})
    return results, {'sourceId': source['id'], 'name': source['name'], 'url': source['url'], 'startedAt': started, 'finishedAt': timestamp(), 'status': 'partial' if failures else 'success', 'httpStatus': 200, 'pagesScanned': scanned, 'recordsFound': len(results), 'failures': failures}


def merge_feed(previous, records):
    items = {item['id']: item for item in previous.get('items', [])}
    added, changed = 0, 0
    for record in records:
        old = items.get(record['id'])
        if old:
            record['firstSeenAt'] = old['firstSeenAt']
            record['version'] = old.get('version', 1)
            record['history'] = old.get('history', [])
            if old['fingerprint'] != record['fingerprint']:
                record['history'] = [*record['history'], {k: old[k] for k in ['version','fingerprint','body','capturedAt']}][-10:]
                record['version'] += 1
                changed += 1
        else:
            added += 1
        items[record['id']] = record
    return sorted(items.values(), key=lambda i: (i['publishedAt'], i['id']), reverse=True), added, changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', default='collector/sources.json')
    parser.add_argument('--output', default='public/data/live-feed.json')
    parser.add_argument('--archive', default='work/crawl/raw')
    args = parser.parse_args()
    config = json.loads(Path(args.sources).read_text())
    output = Path(args.output)
    previous = json.loads(output.read_text()) if output.exists() else {'items': [], 'runs': []}
    records, runs = [], []
    sources = config['sources']
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(crawl_source, source, Path(args.archive)): source for source in sources}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                found, run = future.result()
                records.extend(found)
            except Exception as exc:
                match = re.search(r'HTTP (\d+)', str(exc))
                run = {'sourceId': source['id'], 'name': source['name'], 'url': source['url'], 'startedAt': timestamp(), 'finishedAt': timestamp(), 'status': 'failure', 'httpStatus': int(match[1]) if match else 0, 'pagesScanned': 0, 'recordsFound': 0, 'failures': [{'url': source['url'], 'message': str(exc)}]}
            runs.append(run)
            print(json.dumps(run, ensure_ascii=False), flush=True)
    items, added, changed = merge_feed(previous, records)
    generated = timestamp()
    batch = {'id': 'crawl-' + generated, 'startedAt': min(r['startedAt'] for r in runs), 'finishedAt': generated, 'newRecords': added, 'changedRecords': changed, 'successfulSources': sum(r['status'] != 'failure' for r in runs), 'failedSources': sum(r['status'] == 'failure' for r in runs), 'results': sorted(runs, key=lambda r:r['sourceId'])}
    feed = {'schema': 1, 'generatedAt': generated, 'lastSuccessAt': generated if records else previous.get('lastSuccessAt',''), 'scope': '登记的部门发布、地方媒体与区县新闻；名录条目单列为待补证线索，未经过人工案例认定', 'sources': sources, 'items': items, 'runs': [batch, *previous.get('runs', [])][:30]}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n')
    temp.replace(output)
    print(f'Real collection complete: {len(records)} observed, {added} new, {changed} changed, {len(items)} retained; {batch["failedSources"]} sources failed.', flush=True)
    if not items:
        raise SystemExit('No real reports available; failure states saved, no synthetic fallback.')


if __name__ == '__main__':
    main()
