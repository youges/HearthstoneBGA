"""Replay saved game frames through the application's recognition pipeline.

No live window capture and no input backend is imported by this module.
"""
import json
from pathlib import Path
import sys
import cv2
import numpy as np
from .config import Profile, project_root
from .vision import Vision


def run_replay(manifest,root=None):
    root=Path(root or project_root()).resolve()
    def local(path):
        value=(root/path).resolve()
        if not value.is_relative_to(root):raise ValueError('回放文件必须在项目内')
        return value
    report={'scope':'只回放已保存的截图，不读取或操作正在运行的游戏',
            'frozen':bool(getattr(sys,'frozen',False)),'passed':False,'checks':[]}
    try:
        spec=json.loads(local(manifest).read_text(encoding='utf-8-sig'))
        vision=Vision(Profile.load(local(spec['profile_path'])),root)
        for case in spec['cases']:
            frame=cv2.imdecode(np.fromfile(local(case['image']),dtype=np.uint8),cv2.IMREAD_COLOR)
            if frame is None:raise ValueError('无法读取回放图像')
            obs=vision.analyze(frame)
            passed=(obs.state.value==case['state']
                    and all(obs.metrics.get(k)==v for k,v in case['metrics'].items())
                    and ('trusted' not in case or obs.trusted==case['trusted']))
            report['checks'].append(dict(match_id=case['match_id'],image=case['image'],
                state=obs.state.value,confidence=obs.confidence,trusted=obs.trusted,metrics=obs.metrics,targets=obs.targets,passed=passed))
        report['passed']=bool(report['checks']) and all(x['passed'] for x in report['checks'])
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
    destination=root/'data/vision-replay-result.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1
