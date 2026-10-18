"""Download and test the exact public GitHub release on this machine."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bga import __version__
REPO='https://github.com/youges/HearthstoneBGA'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tag',default='v'+__version__)
TAG=parser.parse_args().tag
import re
assert re.fullmatch(r'v\d+\.\d+\.\d+',TAG),'Invalid release tag'
destination=ROOT/'release'/('github-'+TAG);destination.mkdir(parents=True,exist_ok=True)
request=urllib.request.Request('https://api.github.com/repos/youges/HearthstoneBGA/releases/tags/'+TAG,
                               headers={'User-Agent':'HearthstoneBGA-release-verification'})
metadata=ROOT/'data'/f'github-release-{TAG}-metadata.json'
if metadata.exists():release=json.loads(metadata.read_text(encoding='utf-8'))
else:
    with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
assert not release['draft'] and release['tag_name']==TAG


def download(asset):
    url=asset['browser_download_url']
    assert url.startswith(REPO+'/releases/download/'+TAG+'/')
    path=destination/asset['name']
    digest=hashlib.sha256()
    with urllib.request.urlopen(url,timeout=30) as response,path.open('wb') as output:
        while block:=response.read(1024*1024):digest.update(block);output.write(block)
    assert path.stat().st_size==asset['size']
    assert 'sha256:'+digest.hexdigest()==asset['digest']
    print('Downloaded and verified: '+path.name,flush=True)
    return dict(name=path.name,sha256=digest.hexdigest(),bytes=path.stat().st_size)


with ThreadPoolExecutor(max_workers=3) as pool:files=list(pool.map(download,release['assets']))
sums=(destination/'SHA256SUMS.txt').read_text(encoding='utf-8')
for file in files:
    if file['name'].endswith('.zip'):assert file['sha256']+'  '+file['name'] in sums
package=destination/f'HearthstoneBGA-{TAG[1:]}-windows-x64.zip'
assert not (destination/'extracted').exists(),'Verification extraction already exists; preserve it and use a new verification directory'
with zipfile.ZipFile(package) as archive:
    assert archive.testzip() is None
    assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in archive.namelist())
    archive.extractall(destination/'extracted')
app=destination/'extracted'/'HearthstoneBGA'
exe=app/'HearthstoneBGA.exe'
checks=[];env=os.environ.copy();env['QT_QPA_PLATFORM']='windows'
for flag,artifact in [('--self-test','runtime-selftest.json'),('--smoke-test','gui-preview.png'),
                      ('--environment-test','environment-selftest.json')]:
    result=subprocess.run([str(exe),flag],cwd=ROOT/'data',env=env,timeout=60)
    assert result.returncode==0,f'Public release failed: {flag}'
    path=app/'data'/artifact
    assert path.exists()
    if path.suffix=='.json':
        data=json.loads(path.read_text(encoding='utf-8'))
        assert data['passed'] and data['frozen']
    checks.append(dict(name=flag,passed=True))
report=dict(time=datetime.now().astimezone().isoformat(),repository=REPO,
            release_url=release['html_url'],release_id=release['id'],passed=True,
            files=files,checks=checks,executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
            scope='公开 Release 下载、校验、原生 GUI、OCR 及分辨率/路径检测；未新开完整对局')
(ROOT/'data'/f'github-release-{TAG}-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
