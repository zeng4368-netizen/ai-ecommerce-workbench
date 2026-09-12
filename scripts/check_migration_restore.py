"""Smoke test the portable snapshot in a temporary root without live secrets or jobs."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    args=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='workbench-restore-test-') as tmp:
        root=Path(tmp)
        source=args.directory/'repository'
        shutil.copy2(source/'AGENTS.md',root/'AGENTS.md')
        shutil.copytree(source/'config',root/'config')
        appdir=root/'frontend/unified_skill_dashboard'
        shutil.copytree(source/'frontend/unified_skill_dashboard',appdir)
        prefixes=('data/raw/ai_workbench/','data/raw/content_studio/',
                  'data/output/ai_workbench/','data/output/content_studio/')
        dbname='data/processed/ai_workbench/workbench.sqlite3'
        with zipfile.ZipFile(args.directory/'workbench-data.zip') as z:
            for name in z.namelist():
                if name==dbname or name.startswith(prefixes):
                    target=(root/name).resolve()
                    if not target.is_relative_to(root.resolve()):
                        raise RuntimeError('Unsafe path')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(z.read(name))
        os.environ['WORKBENCH_DATA_DIR']=str(root/'data')
        os.environ.pop('WORKBENCH_LLM_API_KEY',None)
        sys.path.insert(0,str(appdir))
        import server
        from fastapi.testclient import TestClient
        # Deliberately no lifespan context: do not start the collection scheduler.
        client=TestClient(server.app)
        assert client.get('/api/health').status_code==200
        assert client.get('/api/hub/workspace').status_code==200
        assert client.get('/api/hub/ziniao/status').status_code==200
        con=sqlite3.connect(root/dbname)
        counts={name:con.execute('SELECT count(*) FROM '+name).fetchone()[0]
                for name in ('actions','hub_conversations','content_projects','hub_versions','ziniao_runs')}
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not json.loads(con.execute('SELECT value FROM ziniao_settings WHERE id=1').fetchone()[0])['enabled']
        con.close()
        client.close()
        # Logging owns a Windows file handle; close it before removing temp files.
        import logging
        logging.shutdown()
        print(json.dumps({'temporary_restore':'passed','health':'ok','workspace':'ok','collection_status':'ok',
                          'scheduler_started':False,'credential_restored':False,'counts':counts}))


if __name__=='__main__':
    main()
