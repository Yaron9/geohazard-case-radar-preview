"""Install the pinned upstream checkout; never modify an existing different checkout."""
import subprocess
from trendradar_bridge import ROOT, REVISION

if not ROOT.exists():
    ROOT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'clone', '--no-checkout', '--filter=blob:none', 'https://github.com/sansan0/TrendRadar.git', str(ROOT)], check=True)
    subprocess.run(['git', '-C', str(ROOT), 'checkout', '--detach', REVISION], check=True)
else:
    actual = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    if actual != REVISION:
        raise SystemExit('Existing TrendRadar checkout differs; preserve it and use a separate clean workspace.')
print('TrendRadar pinned at', REVISION)
