"""Package a clean CI build without any personal runtime files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bga import __version__

app=ROOT/'dist/HearthstoneBGA'
exe=app/'HearthstoneBGA.exe'
for flag,artifact in [('--smoke-test','gui-preview.png'),('--self-test','runtime-selftest.json')]:
    result=subprocess.run([str(exe),flag],cwd=app,timeout=90)
    assert result.returncode==0,f'Packaged check failed: {flag}'
    path=app/'data'/artifact
    assert path.is_file()
    if path.suffix=='.json':assert json.loads(path.read_text(encoding='utf-8'))['passed']
    path.unlink()
assert sorted(p.name for p in (app/'data').iterdir())==['settings.json']
settings=json.loads((app/'data/settings.json').read_text(encoding='utf-8'))
assert settings['observe_only'] and settings['auto_adapt_resolution'] and not settings['battle_net_path']
output=ROOT/'release'/f'v{__version__}';output.mkdir(parents=True,exist_ok=True)
windows=output/f'HearthstoneBGA-{__version__}-windows-x64.zip'
with zipfile.ZipFile(windows,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in sorted(app.rglob('*')):
        if path.is_file():archive.write(path,path.relative_to(app.parent).as_posix())
source=output/f'HearthstoneBGA-{__version__}-source.zip'
files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for name in files:
        if name:archive.write(ROOT/name,'HearthstoneBGA-source/'+name)
lines=[]
for path in [windows,source]:
    with zipfile.ZipFile(path) as archive:assert archive.testzip() is None
    lines.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n')
(output/'SHA256SUMS.txt').write_text(''.join(lines),encoding='utf-8')
print(json.dumps({'version':__version__,'checks_passed':True,'files':[windows.name,source.name]},indent=2))
