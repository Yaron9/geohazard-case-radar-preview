"""Install the platform-owned reader, not a developer's global skill/MCP setup."""
import json
import subprocess
from pathlib import Path


def status():
    result=subprocess.run(['node','collector/platform-browser.mjs'],input=json.dumps({'operation':'status'}),capture_output=True,text=True,check=True)
    return json.loads(result.stdout)

current=status()
if not current['library']:
    root=Path('work/platform-browser');root.mkdir(parents=True,exist_ok=True)
    (root/'package.json').write_text('{"private":true,"name":"radar-platform-browser"}\n')
    subprocess.run(['npm','install','--prefix',str(root),'--no-save','--package-lock=false','--ignore-scripts','playwright@1.64.1'],check=True)
    current=status()
if not current['available']:
    subprocess.run(['node',current['cli'],'install','--with-deps','chromium'],check=True)
print('Platform browser ready:',status()['available'])
