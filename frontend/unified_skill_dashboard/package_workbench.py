"""Package code, local assets and original Skill files; exclude runtime data and secrets."""
from pathlib import Path
from datetime import date
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1] if (ROOT.parents[1] / 'AGENTS.md').exists() else ROOT
OUTPUT = PROJECT / 'data/output'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    name = f'ai_ecommerce_workbench_{date.today().isoformat()}'
    destination = OUTPUT / (name + '.zip')
    index = 2
    while destination.exists():
        destination = OUTPUT / (name + f'_{index}.zip')
        index += 1
    excluded = {'__pycache__', '.pytest_cache', 'data', 'logs', '.git', '.venv', 'node_modules'}
    count = 0
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob('*')):
            rel = path.relative_to(ROOT)
            if not path.is_file() or any(part in excluded for part in rel.parts):
                continue
            if (path.name.startswith('.env') and path.name != '.env.example') or path.suffix in {'.pyc', '.sqlite3', '.log'}:
                continue
            archive.write(path, 'ai_ecommerce_workbench/' + rel.as_posix())
            count += 1
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
    print(json.dumps({'archive': str(destination), 'files': count, 'bytes': destination.stat().st_size,
                      'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
