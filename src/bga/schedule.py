"""Local daily windows and an interactive Windows scheduled launch."""
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def window(config, now=None):
    now = now or datetime.now()
    start = datetime.strptime(config.schedule_start, '%H:%M').time()
    end = datetime.strptime(config.schedule_end, '%H:%M').time()
    begin = datetime.combine(now.date(), start)
    finish = datetime.combine(now.date(), end)
    if end < start:
        finish += timedelta(days=1)
        if now < datetime.combine(now.date(), end):
            begin -= timedelta(days=1)
            finish -= timedelta(days=1)
    if now >= finish:
        begin += timedelta(days=1)
        finish += timedelta(days=1)
    return begin, finish


def task_name(root):
    return 'HearthstoneBGA-' + hashlib.sha256(str(Path(root).resolve()).lower().encode()).hexdigest()[:12]


def sync_task(config, root):
    """Use the logged-in user's desktop, without storing a password."""
    root = Path(root).resolve()
    name = task_name(root)
    hidden = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    query = subprocess.run(['schtasks.exe', '/Query', '/TN', name], capture_output=True, creationflags=hidden)
    if not config.schedule_enabled:
        if query.returncode == 0:
            result = subprocess.run(['schtasks.exe', '/Delete', '/TN', name, '/F'], capture_output=True, creationflags=hidden)
            if result.returncode: raise OSError('无法移除定时启动任务')
        return
    who = subprocess.check_output(['whoami.exe'], text=True, creationflags=hidden).strip()
    begin, _ = window(config)
    ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
    ET.register_namespace('', ns)
    def node(parent, name, value=None, **attrs):
        item = ET.SubElement(parent, '{'+ns+'}'+name, attrs)
        if value is not None: item.text = str(value)
        return item
    task = ET.Element('{'+ns+'}Task', version='1.2')
    triggers = node(task, 'Triggers'); trigger = node(triggers, 'CalendarTrigger')
    node(trigger, 'StartBoundary', begin.isoformat()); node(trigger, 'Enabled', 'true')
    node(node(trigger, 'ScheduleByDay'), 'DaysInterval', '1')
    principal = node(node(task, 'Principals'), 'Principal', id='User')
    node(principal, 'UserId', who); node(principal, 'LogonType', 'InteractiveToken')
    node(principal, 'RunLevel', 'LeastPrivilege')
    settings = node(task, 'Settings')
    for key,value in [('MultipleInstancesPolicy','IgnoreNew'), ('DisallowStartIfOnBatteries','false'),
                      ('StopIfGoingOnBatteries','false'), ('ExecutionTimeLimit','PT0S')]:
        node(settings, key, value)
    action = node(node(task, 'Actions', Context='User'), 'Exec')
    node(action, 'Command', sys.executable)
    node(action, 'Arguments', '--scheduled-run' if getattr(sys,'frozen',False)
         else subprocess.list2cmdline([str(root/'run.py'), '--scheduled-run']))
    node(action, 'WorkingDirectory', root)
    path = root/'data'/'daily-schedule.xml'; path.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(task).write(path, encoding='utf-16', xml_declaration=True)
    result = subprocess.run(['schtasks.exe','/Create','/TN',name,'/XML',str(path),'/F'],capture_output=True,creationflags=hidden)
    if result.returncode:
        raise OSError('无法保存 Windows 定时启动任务：'+(result.stderr or result.stdout).decode('mbcs',errors='replace'))
