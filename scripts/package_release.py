"""Create distributable archives from an already verified portable build.

An allowlist excludes local matches, screenshots, logs and private development notes.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bga.config import Config
from bga.config import Profile
from bga.vision import Vision
from bga import __version__


def archive(directory,destination):
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for path in sorted(directory.rglob('*')):
            if path.is_file():output.write(path,path.relative_to(directory.parent).as_posix())


def prepare_assets(destination):
    shutil.copytree(ROOT/'assets',destination)
    # Only the central board ROI is used by this detector. The original full
    # game frame contains player UI that is not needed in a public package.
    path=destination/'templates/live/empty-board-frame.png'
    frame=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)
    canonical=cv2.resize(frame,(1536,864))
    minimal=np.zeros_like(canonical)
    minimal[415:550,340:1190]=canonical[415:550,340:1190]
    cv2.imencode('.png',minimal)[1].tofile(path)
    assert np.array_equal(minimal[415:550,340:1190],canonical[415:550,340:1190])


def docs(destination):
    destination.mkdir(parents=True)
    for name in ['使用说明.md','功能文档.md','版本说明-0.2.0.md']:
        shutil.copy2(ROOT/'docs'/name,destination/name)
    version_notes=ROOT/'docs'/f'版本说明-{__version__}.md'
    if version_notes.exists() and not (destination/version_notes.name).exists():
        shutil.copy2(version_notes,destination/version_notes.name)
    shutil.copy2(ROOT/'docs/功能文档.md',destination/'开发文档.md')


def main():
    release=ROOT/'release'/f'v{__version__}'
    release.mkdir(parents=True,exist_ok=True)
    staging=release/('staging-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    app=staging/'HearthstoneBGA';app.mkdir(parents=True)
    build=ROOT/'dist/HearthstoneBGA'
    shutil.copy2(build/'HearthstoneBGA.exe',app)
    shutil.copytree(build/'_internal',app/'_internal')
    prepare_assets(app/'assets')
    (app/'profiles').mkdir()
    for name in ['default.json','pc-integration.json']:shutil.copy2(ROOT/'profiles'/name,app/'profiles'/name)
    profile_path=app/'profiles/pc-integration.json'
    profile=json.loads(profile_path.read_text(encoding='utf-8'))
    profile['name']='内置 PC 16:9 参考布局'
    profile_path.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    class NoOCR:
        def tokens(self,_):return []
        def recognize_line(self,_):return []
    # Confirm the minimized public board reference preserves detector behavior.
    for relative in ['data/calibration/targeting-success-20261017/settled.png',
                     'data/calibration/20261017-board-four-golden.png']:
        fixture=ROOT/relative
        if not fixture.exists():continue
        image=cv2.imdecode(np.fromfile(fixture,np.uint8),cv2.IMREAD_COLOR)
        old=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(image)
        new=Vision(Profile.load(profile_path),app,NoOCR()).analyze(image)
        assert old.state==new.state and old.trusted==new.trusted and old.board_count==new.board_count
    Config(profile_path='profiles/pc-integration.json',max_matches=1,
           focus_on_start=True,recover_focus=True,inspect_hand_cards=True,
           min_gold_after_upgrade=2).save(app/'data/settings.json')
    docs(app/'docs')
    shutil.copy2(ROOT/'README.md',app/'README.md')
    shutil.copytree(ROOT/'THIRD_PARTY_NOTICES',app/'THIRD_PARTY_NOTICES')
    checks=[]
    for flag,artifact in [('--smoke-test','gui-preview.png'),('--self-test','runtime-selftest.json'),
                          ('--environment-test','environment-selftest.json')]:
        completed=subprocess.run([str(app/'HearthstoneBGA.exe'),flag],cwd=app,timeout=45)
        assert completed.returncode==0,f'{flag} failed'
        path=app/'data'/artifact
        assert path.exists(),f'{artifact} missing'
        if path.suffix=='.json':
            result=json.loads(path.read_text(encoding='utf-8'))
            assert result['passed'] and result['frozen']
        checks.append(dict(name=flag,passed=True))
        shutil.copy2(path,ROOT/'data'/('public-package-'+artifact))
        path.unlink()
    assert sorted(p.name for p in (app/'data').iterdir())==['settings.json']
    source=staging/'HearthstoneBGA-source';source.mkdir()
    shutil.copytree(ROOT/'src',source/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'tests',source/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(app/'assets',source/'assets')
    shutil.copytree(app/'profiles',source/'profiles')
    shutil.copytree(app/'docs',source/'docs')
    shutil.copytree(ROOT/'THIRD_PARTY_NOTICES',source/'THIRD_PARTY_NOTICES')
    for name in ['run.py','pyproject.toml','requirements-lock.txt','README.md','启动助手.cmd','.gitignore']:
        shutil.copy2(ROOT/name,source/name)
    (source/'scripts').mkdir()
    (source/'research').mkdir()
    shutil.copy2(ROOT/'research/ocr_model_manifest.json',source/'research/ocr_model_manifest.json')
    for name in ['build.ps1','package_release.py','publish_github.ps1']:
        shutil.copy2(ROOT/'scripts'/name,source/'scripts'/name)
    names=[(app,f'HearthstoneBGA-{__version__}-windows-x64.zip'),
           (source,f'HearthstoneBGA-{__version__}-source.zip')]
    records=[]
    for folder,name in names:
        path=release/name;archive(folder,path)
        with zipfile.ZipFile(path) as check:assert check.testzip() is None
        records.append(dict(file=name,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (release/'SHA256SUMS.txt').write_text(''.join(f'{r["sha256"]}  {r["file"]}\n' for r in records),encoding='utf-8')
    shutil.copy2(ROOT/'docs'/f'版本说明-{__version__}.md',release/'RELEASE_NOTES.md')
    report=dict(version=__version__,passed=True,checks=checks,archives=records,
                staging=str(staging),github_published=False)
    (release/'package-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
