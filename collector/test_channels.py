import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import crawl

class ChannelSelectionTests(unittest.TestCase):
    def run_scan(self, channels, mode):
        sources=[{'id':'web','name':'web','type':'listing','url':'https://example.org/'},{'id':'wechat','name':'wechat','type':'wechat-search','url':'https://weixin.sogou.com/','query':'custom wechat words'},{'id':'video','name':'video','type':'video-search','url':'https://www.sogou.com/','query':'custom video words'}]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'sources.json';out=root/'feed.json';config.write_text(json.dumps({'sources':sources}))
            with patch('sys.argv',['crawl','--sources',str(config),'--output',str(out),'--channels',channels,'--mode',mode]),patch.object(crawl,'crawl_source',side_effect=RuntimeError('network disabled in test')) as fetch,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit,'No real reports'):crawl.main()
            return [call.args[0] for call in fetch.call_args_list],json.loads(out.read_text())
    def test_unselected_registered_media_are_never_called(self):
        calls,_=self.run_scan('web','all')
        self.assertEqual({s['id'] for s in calls},{'web','web-discovery'})
    def test_selected_media_uses_saved_keyword_rule_without_generic_duplicate(self):
        for mode in ['all','sources']:
            calls,_=self.run_scan('wechat',mode)
            self.assertEqual([s['id'] for s in calls],['wechat'])
            self.assertEqual(calls[0]['query'],'custom wechat words')
