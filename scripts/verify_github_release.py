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
import tempfile
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
if metadata.exists():release=json.loads(metadata.read_text(encoding='utf-8-sig'))
else:
    with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
assert not release['draft'] and release['tag_name']==TAG


def inspect(path,asset):
    if not path.is_file() or path.stat().st_size!=asset['size']:
        return None
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if 'sha256:'+digest!=asset['digest']:
        return None
    return dict(name=asset['name'],sha256=digest,bytes=asset['size'])


def download(asset,temporary):
    url=asset['browser_download_url']
    assert url.startswith(REPO+'/releases/download/'+TAG+'/')
    assert Path(asset['name']).name==asset['name']
    path=destination/asset['name']
    if result:=inspect(path,asset):
        print('Verified cached download: '+path.name,flush=True)
        return result
    partial=temporary/path.name
    with urllib.request.urlopen(url,timeout=30) as response,partial.open('wb') as output:
        while block:=response.read(1024*1024):output.write(block)
    result=inspect(partial,asset)
    assert result,f'Download size or SHA-256 mismatch: {path.name}'
    partial.replace(path)
    print('Downloaded and verified: '+path.name,flush=True)
    return result


assert destination.resolve().is_relative_to((ROOT/'release').resolve())
assert destination.resolve().is_relative_to(ROOT)
with tempfile.TemporaryDirectory(prefix='verify-',dir=destination) as scratch:
    temporary=Path(scratch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        files=list(pool.map(lambda asset:download(asset,temporary),release['assets']))
    sums=(destination/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
    for file in files:
        if file['name'].endswith('.zip'):assert file['sha256']+'  '+file['name'] in sums
    package=destination/f'HearthstoneBGA-{TAG[1:]}-windows-x64.zip'
    extracted=temporary/'extracted'
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert all((extracted/n).resolve().is_relative_to(extracted) for n in archive.namelist())
        archive.extractall(extracted)
    app=extracted/'HearthstoneBGA'
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
    executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest()
report=dict(time=datetime.now().astimezone().isoformat(),repository=REPO,
            release_url=release['html_url'],release_id=release['id'],passed=True,
            files=files,checks=checks,executable_sha256=executable_sha256,temporary_files_cleaned=True,
            scope='公开 Release 下载、校验、原生 GUI、OCR 及分辨率/路径检测；未新开完整对局')
(ROOT/'data'/f'github-release-{TAG}-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
