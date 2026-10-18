"""Pinned upstream TrendRadar integration (RSS fetching + keyword matching)."""
from functools import lru_cache
import sys
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec
from pathlib import Path

REVISION = '657094ed6a527441b917e16d9497fc8435ed091d'
ROOT = Path(__file__).resolve().parent.parent / 'work' / 'trendradar'


@lru_cache(maxsize=1)
def modules():
    if not (ROOT / 'trendradar').exists():
        raise RuntimeError('TrendRadar未安装；先运行 python collector/setup_trendradar.py')
    import subprocess
    revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    if revision != REVISION:
        raise RuntimeError('TrendRadar版本与固定基线不一致，请重新安装')
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    # Upstream's package __init__ eagerly imports its optional AI application.
    # Load only the unmodified collection modules through namespace packages;
    # this adapter does not require or initialize a model client.
    for package in ['trendradar','trendradar.crawler','trendradar.crawler.rss','trendradar.storage','trendradar.utils','trendradar.core']:
        if package not in sys.modules:
            spec = ModuleSpec(package, loader=None, is_package=True)
            spec.submodule_search_locations = [str(ROOT.joinpath(*package.split('.'))) ]
            sys.modules[package] = module_from_spec(spec)
    from trendradar.crawler.rss.fetcher import RSSFetcher, RSSFeedConfig
    from trendradar.core.frequency import matches_word_groups
    return RSSFetcher, RSSFeedConfig, matches_word_groups


def fetch_rss(source):
    Fetcher, Config, _ = modules()
    config = Config(id=source['id'], name=source['name'], url=source['url'], max_items=0)
    fetcher = Fetcher([config], timeout=20, freshness_enabled=False)
    try:
        items, error = fetcher.fetch_feed(config)
    finally:
        fetcher.session.close()
    if error:
        raise RuntimeError('TrendRadar RSS: ' + error)
    return [(item.url, item.title) for item in items]


def matches(title, keywords):
    _, _, matcher = modules()
    return matcher(title, [{'required': [], 'normal': keywords}] if keywords else [], [])
