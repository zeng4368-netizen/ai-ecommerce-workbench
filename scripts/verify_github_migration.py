"""Verify migration hashes and scan plaintext artifacts without printing secrets."""
import argparse
import binascii
import hashlib
import io
import json
from pathlib import Path
import zipfile
import zlib

from dotenv import dotenv_values

from prepare_github_migration import ROOT, SECRET_PATTERN, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    args = p.parse_args()
    manifest = json.loads((args.directory/'migration-manifest.json').read_text(encoding='utf-8'))
    known = []
    warnings = []
    for path in (ROOT/'.env', ROOT/'frontend/unified_skill_dashboard/.env'):
        known += [v.encode() for k,v in dotenv_values(path).items() if v and len(v)>=12 and
                  any(word in k.upper() for word in ('KEY','TOKEN','PASSWORD','SECRET'))]

    def scan(data, label, depth=0):
        if SECRET_PATTERN.search(data) or any(secret in data for secret in known):
            raise RuntimeError(f'Credential-like content found; not safe to upload: {label}')
        if data.startswith(b'PK\x03\x04'):
            if depth>=5:
                raise RuntimeError(f'Archive nesting requires manual review: {label}')
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for entry in z.infolist():
                    if not entry.is_dir():
                        # Scan readable original bytes even when a legacy XLSX has
                        # a bad metadata CRC. Do not repair or rewrite the input.
                        try:
                            with z.open(entry) as stream:
                                stream._expected_crc = None
                                content = stream.read()
                        except (zipfile.BadZipFile, zlib.error, EOFError):
                            warnings.append({'file':label+'!'+entry.filename,
                                             'issue':'original archive entry unreadable; raw bytes preserved, content scan incomplete'})
                            continue
                        if binascii.crc32(content) & 0xffffffff != entry.CRC:
                            warnings.append({'file': label+'!'+entry.filename,
                                             'issue': 'original archive entry CRC mismatch; preserved unchanged'})
                        scan(content, label+'!'+entry.filename, depth+1)

    for artifact in manifest['artifacts']:
        path = args.directory/artifact['name']
        if sha(path)!=artifact['sha256']:
            raise RuntimeError('Artifact hash mismatch: '+path.name)
    with zipfile.ZipFile(args.directory/'workbench-data.zip') as z:
        for item in manifest['files']:
            if item['part']=='data':
                data=z.read(item['path'])
            else:
                data=(args.directory/'repository'/item['path']).read_bytes()
                if sha(ROOT/item['path'])!=item['sha256']:
                    raise RuntimeError('Source changed since snapshot: '+item['path'])
            if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
                raise RuntimeError('File hash mismatch: '+item['path'])
            scan(data,item['path'])
    result = {'verified_files':len(manifest['files']), 'credential_scan':'no matches in readable content; see original file warnings',
              'artifact_hashes':'passed', 'source_unchanged':'passed', 'original_file_warnings':warnings}
    (args.directory/'verification-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({**result,'original_file_warnings_count':len(warnings),'original_file_warnings':warnings[:3]},ensure_ascii=False))


if __name__=='__main__':
    main()
