from pathlib import Path
import importlib.util
import pytest

spec=importlib.util.spec_from_file_location('compact_build_backup',Path(__file__).resolve().parents[1]/'scripts/compact_build_backup.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def prepare(root,name='20261018-190000-000'):
    backup=root/'data/release-backups'/name
    app=root/'dist/HearthstoneBGA'
    for base in (backup,app):
        (base/'data/screenshots').mkdir(parents=True,exist_ok=True)
        (base/'data/screenshots/frame.png').write_bytes(b'large-picture')
        (base/'data/settings.json').write_text('{}')
    (backup/'profiles').mkdir();(backup/'profiles/user.json').write_text('{"calibrated":true}')
    return backup,app

def test_verified_restore_keeps_picture_in_app_and_compacts_backup(tmp_path):
    backup,app=prepare(tmp_path)
    compact=module.finalize_backup(tmp_path,backup)
    assert not backup.exists()
    assert (app/'data/screenshots/frame.png').read_bytes()==b'large-picture'
    assert (app/'profiles/user.json').read_text()=='{"calibrated":true}'
    assert (compact/'data/settings.json').exists()
    assert not (compact/'data/screenshots').exists()

def test_incomplete_restore_preserves_full_backup(tmp_path):
    backup,app=prepare(tmp_path)
    (app/'data/screenshots/frame.png').unlink()
    with pytest.raises(ValueError,match='Restore verification failed'):module.finalize_backup(tmp_path,backup)
    assert (backup/'data/screenshots/frame.png').exists()

def test_backup_outside_named_directory_is_rejected(tmp_path):
    other=tmp_path/'other';other.mkdir()
    with pytest.raises(ValueError,match='Unexpected build backup'):module.finalize_backup(tmp_path,other)
    assert other.exists()

def test_only_three_successful_compact_backups_are_kept(tmp_path):
    for i in range(5):
        backup,app=prepare(tmp_path,f'20261018-19000{i}-000')
        module.finalize_backup(tmp_path,backup)
    assert len(list((tmp_path/'data/build-settings-backups').iterdir()))==3
    assert (app/'data/screenshots/frame.png').exists()
