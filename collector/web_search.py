"""Bounded public web search. No source whitelist; keep provider/query evidence."""
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs


def query_plan(query):
    # Keep all user constraints in every query. Do not silently replace region/date.
    return list(dict.fromkeys([query, f'{query} 提前撤离 转移', f'{query} 成功预警 避险']))


def result_links(soup, provider, base):
    selector = 'a.result__a' if provider == 'DuckDuckGo' else 'h3 a'
    links = []
    for anchor in soup.select(selector):
        title = anchor.get_text(' ', strip=True)
        url = urljoin(base, anchor.get('href', ''))
        if provider == 'DuckDuckGo':
            url = parse_qs(urlsplit(url).query).get('uddg', [url])[0]
        if urlsplit(url).scheme in ['http', 'https'] and title:
            links.append((url, title))
    return links


def discover(query, fetch, relevant, limit=24):
    links, traces = [], []
    for term in query_plan(query):
        for provider, base in [('DuckDuckGo', 'https://html.duckduckgo.com/html/'), ('搜狗', 'https://www.sogou.com/web')]:
            matched = False
            for page_number in [1, 2]:
                params = {'q': term, 's': (page_number - 1) * 30} if provider == 'DuckDuckGo' else {'query': term, 'page': page_number}
                url = base + '?' + urlencode(params)
                trace = {'provider': provider, 'query': term, 'page': page_number, 'url': url, 'status': 'success', 'returned': 0, 'relevant': 0}
                try:
                    soup, _, _ = fetch(url)
                    candidates = result_links(soup, provider, base)
                    trace['returned'] = len(candidates)
                    for candidate, title in candidates:
                        if not relevant(title):
                            continue
                        if provider == '搜狗':
                            try:
                                _, effective, _ = fetch(candidate)
                                if (urlsplit(effective).hostname or '').endswith('sogou.com'):
                                    continue
                                candidate = effective
                            except Exception:
                                continue
                        trace['relevant'] += 1
                        if candidate not in [u for u, _ in links]:
                            links.append((candidate, title))
                    if not trace['relevant']:
                        trace.update(status='partial', error='未取得可用相关结果，可能为验证页或未匹配')
                except Exception as exc:
                    trace.update(status='failure', error=str(exc)[:200])
                traces.append(trace)
                matched = matched or bool(trace['relevant'])
                if not trace['relevant'] or len(links) >= limit:
                    break
            if matched or len(links) >= limit:
                break
        if len(links) >= limit:
            break
    return links[:limit], traces
