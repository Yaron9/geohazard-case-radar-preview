"""Suggest verifiable monitoring channels from newly discovered original reports."""
from urllib.parse import urlsplit, urljoin, urlunsplit
import re
import hashlib
import xml.etree.ElementTree as ET


def identity(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/') or '/', p.query, ''))


def suggest_sources(records, sources, fetch, relevant, limit=4, verify_article=None):
    known = {identity(s['url']) for s in sources}
    suggestions, seen = [], set()
    for report in records:
        p = urlsplit(report['url'])
        root = f'{p.scheme}://{p.netloc}/'
        if root in seen:
            continue
        seen.add(root)
        if len(suggestions) >= limit:
            break
        # A site's home page is a fallback candidate, never a proven channel by domain alone.
        sid = 'suggest-' + hashlib.sha256(root.encode()).hexdigest()[:12]
        proposal = {'id': sid, 'name': p.hostname, 'publisher': p.hostname, 'category': '官方网站' if (p.hostname or '').endswith('.gov.cn') else '地方媒体', 'type': 'article', 'url': report['url'], 'province': report.get('province', '全国'), 'enabled': False, 'pendingAdapter': True}
        status, reason = 'needs-adapter', '已发现相关原文，尚未验证可持续采集入口。'
        try:
            soup, effective, _ = fetch(root)
            site_name = soup.select_one('meta[property="og:site_name"]')
            name = site_name.get('content') if site_name else soup.title.get_text(' ', strip=True) if soup.title else p.hostname
            proposal.update(name=(name or p.hostname)[:80], publisher=(name or p.hostname)[:80])
            feeds = soup.select('link[rel~=alternate][type="application/rss+xml"], link[rel~=alternate][type="application/atom+xml"]')
            for node in feeds[:2]:
                feed_url = urljoin(effective, node.get('href', ''))
                if urlsplit(feed_url).hostname != urlsplit(effective).hostname:
                    continue
                try:
                    _, _, raw = fetch(feed_url)
                    tree = ET.fromstring(raw)
                    if tree.tag.split('}')[-1] not in ['rss', 'feed', 'RDF']:
                        continue
                    proposal.update(type='rss', url=feed_url, enabled=True, pendingAdapter=False)
                    status, reason = 'ready', '原网站声明的RSS/Atom入口已访问并验证，可持续订阅。'
                    break
                except Exception:
                    continue
            # Only advertise a working listing when it actually links to this fetched report.
            if status != 'ready' and p.hostname != 'mp.weixin.qq.com':
                linked = any(identity(urljoin(effective, a['href'])) == identity(report['url']) and relevant(a.get('title') or a.get_text(' ', strip=True)) for a in soup.find_all('a', href=True))
                if linked:
                    proposal.update(type='listing', url=effective, enabled=True, pendingAdapter=False, allowedHosts=[p.hostname])
                    status, reason = 'ready', '已验证此栏目包含本次取得正文的相关报道，可按网页适配持续扫描。'
        except Exception:
            pass
        key = identity(proposal['url'])
        # Historical stories may have left the home page. Verify their parent channel,
        # rather than requiring today's home page to still link to an old report.
        if status != 'ready' and verify_article and p.hostname != 'mp.weixin.qq.com':
            parts = p.path.strip('/').split('/')[:-1]
            while parts and re.fullmatch(r'(?:20\d{2}(?:\d{2})?|\d{2})', parts[-1]):
                parts.pop()
            channel = root + '/'.join(parts) + ('/' if parts else '')
            if channel != root:
                try:
                    listing, effective, _ = fetch(channel)
                    candidates = []
                    for anchor in listing.find_all('a', href=True):
                        candidate = urljoin(effective, anchor['href'])
                        cp = urlsplit(candidate)
                        if cp.hostname == p.hostname and candidate.startswith(effective.rstrip('/')+'/') and re.search(r'\.(?:s?html?|htm)$', cp.path) and candidate not in candidates:
                            candidates.append(candidate)
                    for candidate in candidates[:3]:
                        try:
                            article_soup, article_url, _ = fetch(candidate)
                            if verify_article(article_soup, article_url):
                                proposal.update(type='listing', url=effective, enabled=True, pendingAdapter=False, allowedHosts=[p.hostname])
                                status, reason = 'ready', '已访问报道所属栏目，并验证栏目链接可提取正文，可持续监测。'
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
        key = identity(proposal['url'])
        if key in known:
            continue
        # Never claim another channel on the same host is covered without an exact entrance match.
        if key in {identity(s['source']['url']) for s in suggestions}:
            continue
        sid = 'suggest-' + hashlib.sha256(key.encode()).hexdigest()[:12]
        proposal['id'] = sid
        suggestions.append({'id': sid, 'status': status, 'reason': reason, 'evidenceUrl': report['url'], 'evidenceTitle': report['title'], 'source': proposal})
    return suggestions
