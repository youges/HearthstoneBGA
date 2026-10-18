"""Find installed Battle.net launchers; never run a registry command string."""
import os
from pathlib import Path


def registry_locations():
    import winreg
    keys=[r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Battle.net',
          r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Battle.net.exe',
          r'SOFTWARE\Blizzard Entertainment\Battle.net']
    for hive in [winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE]:
        for view in [winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY]:
            for key in keys:
                try:
                    with winreg.OpenKey(hive,key,0,winreg.KEY_READ|view) as handle:
                        for name in ['InstallLocation','InstallPath','Path','DisplayIcon','']:
                            try:
                                value,_=winreg.QueryValueEx(handle,name)
                                if isinstance(value,str) and value.strip():
                                    yield os.path.expandvars(value.strip().strip('"').split('",')[0]).removesuffix(',0').strip('"')
                            except OSError:pass
                except OSError:pass


def detect_battle_net(preferred='',running=None,locations=None,common=None):
    candidates=[(preferred,'已保存的路径')]
    if running is None:
        from .windows import find_windows
        try:running=[w.exe for w in find_windows() if w.kind=='launcher']
        except OSError:running=[]
    candidates.extend((p,'正在运行的客户端') for p in running)
    if locations is None:locations=registry_locations()
    candidates.extend((p,'Windows 注册表') for p in locations)
    if common is None:
        common=[str(Path(os.environ[k])/'Battle.net') for k in ['ProgramFiles(x86)','ProgramFiles','LOCALAPPDATA'] if os.environ.get(k)]
        common.extend([r'C:\Battle.net',r'D:\Battle.net',r'D:\battlenet\Battle.net'])
    candidates.extend((p,'常见安装目录') for p in common)
    seen=set()
    for value,source in candidates:
        if not value:continue
        path=Path(value).expanduser()
        paths=[path] if path.suffix.lower()=='.exe' else [path/'Battle.net Launcher.exe',path/'Battle.net.exe']
        for item in paths:
            key=str(item).casefold()
            if key in seen:continue
            seen.add(key)
            if item.name.lower() in ['battle.net.exe','battle.net launcher.exe'] and item.is_file():
                return str(item.resolve()),source
    return '', '未检测到战网，请手动选择启动程序'
