"""Create a reviewable source tree, consistent data archive and encrypted credentials.

Does not publish, change source data, restore credentials or read browser profiles.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile

from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
             '.mypy_cache', '.ruff_cache', 'browser_profiles'}
SKIP_TOP = {'data', 'logs', 'external', '.claude', 'dashi-taskboard'}
SECRET_PATTERN = re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def walk(root):
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(current) / d).is_symlink())
        for name in sorted(files):
            path = Path(current) / name
            if path.is_file() and not path.is_symlink():
                yield path


def is_secret_file(path):
    name = path.name.lower()
    return ((name.startswith('.env') and name != '.env.example') or
            name in {'credentials', 'id_rsa', 'id_ed25519', 'cookies', 'cookies.json',
                     'cookies.txt', 'storage_state.json', 'auth.json'} or
            path.suffix.lower() in {'.key', '.pem', '.pfx', '.p12', '.log', '.pyc'})


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ziniao-config-dir', type=Path, required=True,
                        help='Explicit CLI config directory; only config.json and credentials are backed up')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest = ROOT / 'data/output/github_migration' / stamp
    dest.mkdir(parents=True, exist_ok=False)
    repository = dest / 'repository'
    repository.mkdir()
    manifest = {'created_at': stamp, 'source_root': str(ROOT), 'files': [], 'excluded': [],
                'state': 'prepared_not_uploaded', 'snapshot_policy': 'SQLite online backup; source unchanged'}
    secret_paths = [ROOT / '.env', ROOT / 'frontend/unified_skill_dashboard/.env',
                    args.ziniao_config_dir / 'config.json', args.ziniao_config_dir / 'credentials']
    known = []
    for path in secret_paths[:2]:
        if path.exists():
            known += [v.encode() for k, v in dotenv_values(path).items()
                      if v and len(v) >= 12 and any(x in k.upper() for x in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET'))]

    def checked(path):
        data = path.read_bytes()
        if SECRET_PATTERN.search(data) or any(value in data for value in known):
            raise RuntimeError(f'Credential-like content requires review: {path.relative_to(ROOT)}')
        return data

    source_paths = []
    for child in sorted(ROOT.iterdir()):
        if child.name in SKIP_TOP or child.name in SKIP_DIRS or child.is_symlink():
            manifest['excluded'].append(child.relative_to(ROOT).as_posix())
            continue
        source_paths.extend(walk(child) if child.is_dir() else [child])
    for path in source_paths:
        rel = path.relative_to(ROOT)
        if is_secret_file(path) or path.suffix.lower() in {'.sqlite', '.sqlite3', '.db'}:
            manifest['excluded'].append(rel.as_posix())
            continue
        data = checked(path)
        target = repository / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest['files'].append({'path': rel.as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'part': 'source'})

    # Hold the main database snapshot before collecting immutable raw files.
    # Refuse an active collector or automatic schedule; never modify source state.
    db = ROOT / 'data/processed/ai_workbench/workbench.sqlite3'
    with tempfile.TemporaryDirectory(prefix='workbench-migration-') as tmp:
        backup = Path(tmp) / 'workbench.sqlite3'
        con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
        try:
            settings = json.loads(con.execute('SELECT value FROM ziniao_settings WHERE id=1').fetchone()[0])
            if settings.get('enabled') or con.execute("SELECT count(*) FROM ziniao_runs WHERE state IN ('running','queued')").fetchone()[0]:
                raise RuntimeError('Pause collection before taking a portable snapshot')
            target = sqlite3.connect(backup)
            try:
                con.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database integrity check failed')
            finally:
                target.close()
        finally:
            con.close()

        archive_path = dest / 'workbench-data.zip'
        with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            for path in walk(ROOT / 'data'):
                rel = path.relative_to(ROOT)
                parts = rel.parts
                if parts[1] in {'tmp', 'recovery'} or parts[1:3] == ('output', 'github_migration'):
                    continue
                if is_secret_file(path) or path.name.endswith(('-wal', '-shm', '-journal')):
                    manifest['excluded'].append(rel.as_posix())
                    continue
                actual = backup if path == db else path
                other_sqlite = path != db and path.suffix in {'.sqlite3', '.sqlite', '.db'}
                if other_sqlite:
                    actual = Path(tmp) / (hashlib.sha256(rel.as_posix().encode()).hexdigest() + '.sqlite3')
                    source_db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                    target_db = sqlite3.connect(actual)
                    try:
                        source_db.backup(target_db)
                        if target_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise RuntimeError(f'Database integrity check failed: {rel}')
                    finally:
                        target_db.close()
                        source_db.close()
                before = actual.stat()
                file_hash = sha(actual)
                archive.write(actual, rel.as_posix())
                after = actual.stat()
                if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
                    raise RuntimeError(f'File changed during backup: {rel}')
                manifest['files'].append({'path': rel.as_posix(), 'bytes': after.st_size, 'sha256': file_hash,
                                          'part': 'data', 'sqlite_snapshot': path == db or other_sqlite})
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Data ZIP failed integrity check')

    # Credentials are read directly into memory, never staged as plaintext files.
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in secret_paths:
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else 'ziniao-cli/' + path.name
            archive.writestr(rel, path.read_bytes())
        archive.writestr('RESTORE-NOTES.txt', 'The ziniao-cli files are an original backup, not proof of cross-device authorization. Install the official CLI, verify terminal binding and run doctor. Do not restore browser profiles. Never upload the recovery key.')
    key = Fernet.generate_key()
    encrypted = Fernet(key).encrypt(bundle.getvalue())
    assert Fernet(key).decrypt(encrypted) == bundle.getvalue()
    encrypted_path = dest / 'workbench-credentials.fernet'
    encrypted_path.write_bytes(encrypted)
    recovery = ROOT / 'data/recovery' / ('github-migration-' + stamp + '.key')
    recovery.parent.mkdir(parents=True, exist_ok=True)
    with recovery.open('xb') as stream:
        stream.write(key)
    manifest['credential_policy'] = 'Fernet authenticated encryption; key retained locally outside all upload artifacts'
    manifest['excluded'].extend(['data/processed/browser_profiles/', 'data/recovery/', 'data/tmp/'])
    manifest['artifacts'] = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in (archive_path, encrypted_path)]
    dump(dest / 'migration-manifest.json', manifest)
    print(json.dumps({'directory': str(dest), 'repository': str(repository), 'recovery_key_file': str(recovery),
                      'source_files': sum(f['part']=='source' for f in manifest['files']),
                      'data_files': sum(f['part']=='data' for f in manifest['files']),
                      'artifacts': manifest['artifacts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
