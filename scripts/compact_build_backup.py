"""Retire a full build backup only after portable data was restored and verified."""
from pathlib import Path
import hashlib,re,shutil,sys

def finalize_backup(root,backup):
    root=Path(root).resolve();backup=Path(backup).resolve()
    allowed=root/'data/release-backups'
    if backup.parent!=allowed or not backup.is_dir():raise ValueError('Unexpected build backup path')
    for path in [backup,*backup.rglob('*')]:
        if path.is_symlink() or path.is_junction():raise ValueError('Backup contains links')
    target=root/'dist/HearthstoneBGA'
    for name in ('profiles','assets'):
        if (backup/name).exists():shutil.copytree(backup/name,target/name,dirs_exist_ok=True)
    def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    for path in backup.rglob('*'):
        if path.is_file():
            restored=target/path.relative_to(backup)
            if not restored.is_file() or digest(path)!=digest(restored):
                raise ValueError('Restore verification failed; full backup preserved: '+str(path))
    compact_parent=root/'data/build-settings-backups';compact=compact_parent/backup.name
    if compact.exists():raise ValueError('Compact backup already exists')
    compact.mkdir(parents=True)
    for name in ('profiles','assets'):
        if (backup/name).exists():shutil.copytree(backup/name,compact/name)
    for path in (backup/'data').glob('*'):
        if path.is_file() and (path.name=='settings.json' or path.suffix in ('.sqlite3','.csv')):
            (compact/'data').mkdir(exist_ok=True)
            shutil.copy2(path,compact/'data'/path.name)
    for path in compact.rglob('*'):
        if path.is_file() and digest(path)!=digest(backup/path.relative_to(compact)):
            raise ValueError('Compact backup verification failed')
    shutil.rmtree(backup)
    # Only compact successful-build settings backups are subject to this limit.
    for old in sorted((p for p in compact_parent.iterdir() if p.is_dir() and re.fullmatch(r'\d{8}-\d{6}-\d{3}',p.name)),key=lambda p:p.name,reverse=True)[3:]:
        if old.resolve().parent!=compact_parent.resolve() or old.is_symlink() or old.is_junction():
            raise ValueError('Unexpected compact backup path')
        shutil.rmtree(old)
    return compact

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    print('Verified restored portable data; compact backup: '+str(finalize_backup(root,Path(sys.argv[1]))))
