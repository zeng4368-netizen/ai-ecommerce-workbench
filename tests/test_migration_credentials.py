import io
from pathlib import Path
import subprocess
import sys
import zipfile

from cryptography.fernet import Fernet
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/decrypt_workbench_credentials.py'


def bundle(tmp_path, name='.env', payload=b'DEMO_VALUE=placeholder'):
    key = Fernet.generate_key()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr(name, payload)
    (tmp_path / 'key').write_bytes(key)
    (tmp_path / 'bundle').write_bytes(Fernet(key).encrypt(stream.getvalue()))


def run(tmp_path):
    return subprocess.run([sys.executable, str(SCRIPT), '--bundle', str(tmp_path/'bundle'),
                           '--key-file', str(tmp_path/'key'), '--output', str(tmp_path/'restored')],
                          capture_output=True, text=True)


def test_decrypt_and_refuse_overwrite(tmp_path):
    bundle(tmp_path)
    assert run(tmp_path).returncode == 0
    assert (tmp_path/'restored/.env').read_bytes() == b'DEMO_VALUE=placeholder'
    assert run(tmp_path).returncode != 0
    assert (tmp_path/'restored/.env').read_bytes() == b'DEMO_VALUE=placeholder'


def test_wrong_key_does_not_restore(tmp_path):
    bundle(tmp_path)
    (tmp_path/'key').write_bytes(Fernet.generate_key())
    assert run(tmp_path).returncode != 0
    assert not (tmp_path/'restored').exists()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/escape', '..\\escape'])
def test_path_traversal_rejected(tmp_path, name):
    bundle(tmp_path, name)
    assert run(tmp_path).returncode != 0
    assert not (tmp_path/'restored').exists()
