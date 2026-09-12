"""Decrypt a credential bundle into a NEW directory; never installs or overwrites."""
import argparse
import io
from pathlib import Path, PurePosixPath
import zipfile

from cryptography.fernet import Fernet, InvalidToken


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--key-file', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Output directory must not already exist; existing credentials are never overwritten.')
    try:
        plain = Fernet(args.key_file.read_bytes().strip()).decrypt(args.bundle.read_bytes())
    except (ValueError, InvalidToken):
        p.error('Wrong key or damaged bundle. Nothing was restored.')
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename:
                p.error('Unsafe archive path. Nothing was restored.')
        args.output.mkdir(parents=True, exist_ok=False)
        for item in archive.infolist():
            path = args.output.joinpath(*PurePosixPath(item.filename).parts)
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(archive.read(item))
    print('Decrypted locally. Copy the .env files after review. Ziniao still requires terminal binding checks and doctor. Do not commit decrypted files.')


if __name__ == '__main__':
    main()
