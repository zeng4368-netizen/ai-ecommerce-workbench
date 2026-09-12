"""Bind a prepared data snapshot to the final committed source, without publishing."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from prepare_github_migration import ROOT, is_secret_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT).strip():
        raise RuntimeError('Commit tracked source changes before finalizing')
    manifest_path=args.directory/'migration-manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
    records=[]
    for name in filter(None,names):
        if is_secret_file(Path(name)):
            raise RuntimeError('Forbidden source path: '+name)
        data=(ROOT/name).read_bytes()
        staged=args.directory/'repository'/name
        staged.parent.mkdir(parents=True,exist_ok=True)
        staged.write_bytes(data)
        records.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'part':'source'})
    manifest['files']=records+[v for v in manifest['files'] if v['part']=='data']
    manifest['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    manifest['state']='final_source_bound_to_data_snapshot'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'source_commit':manifest['source_commit'],'source_files':len(records),'data_snapshot_unchanged':True}))


if __name__=='__main__':
    main()
