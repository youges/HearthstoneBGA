from pathlib import Path
import os
import sys

if not getattr(sys,'frozen',False):
    sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))

def entry():
    if '--environment-test' in sys.argv:
        from bga.environment_qa import run_environment_qa
        raise SystemExit(run_environment_qa())
    if '--calibration-test' in sys.argv:
        from bga.calibration_qa import run_calibration_qa
        raise SystemExit(run_calibration_qa(sys.argv[sys.argv.index('--calibration-test')+1]))
    if '--replay-test' in sys.argv:
        from bga.replay import run_replay
        raise SystemExit(run_replay(sys.argv[sys.argv.index('--replay-test')+1]))
    if '--self-test' in sys.argv:
        from bga.selftest import run_selftest
        raise SystemExit(run_selftest())
    from bga.gui import main
    raise SystemExit(main())


if __name__=='__main__':
    try:
        entry()
    except Exception as error:
        import traceback
        root=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        destination=root/'data'/'startup-error.log'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(traceback.format_exc(),encoding='utf-8')
        if '--smoke-test' not in sys.argv and '--self-test' not in sys.argv and '--replay-test' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,f'启动失败：{error}\n\n诊断日志：{destination}','酒馆助手',0x10)
        raise SystemExit(1)
