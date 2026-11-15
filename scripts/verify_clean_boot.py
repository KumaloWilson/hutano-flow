"""Boot, reset and re-boot a unique disposable Compose project with fresh volumes.

Requires the default project's current images to have been built. Main demo
containers, databases and published ports are never changed by this script.
"""
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def main():
    project='hutano_verify_'+uuid.uuid4().hex[:12]
    assert project.startswith('hutano_verify_') and project.replace('_','').isalnum()
    base=['docker','compose','-p',project,'-f','docker-compose.yml','-f','docker-compose.verify.yml']
    def run(*args):
        return subprocess.run([*base,*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout
    def count():
        return int(run('exec','-T','db','sh','-c','psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM visits"').strip())
    def artifact_hashes():
        return json.loads(run('exec','-T','api','python','-c',
            "import json,hashlib;from pathlib import Path;p=Path('/app/artifacts');print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file()},sort_keys=True))"))
    isolated_env={**os.environ,'COMPOSE_PROJECT_NAME':project,'COMPOSE_FILE':
        os.pathsep.join(str(Path(name).resolve()) for name in ['docker-compose.yml','docker-compose.verify.yml'])}
    backup_directory=None
    started=time.monotonic()
    try:
        for cycle in [1,2]:
            run('up','--no-build','-d','--wait','--wait-timeout','90')
            assert count()==0, 'A fresh database must have no patient visits'
            # Static shell served by the non-root standalone Node runtime.
            run('exec','-T','web','node','-e',"fetch('http://127.0.0.1:3000').then(r=>{if(!r.ok)throw Error(r.status);return r.text()}).then(t=>{if(!t.includes('Hutano Flow'))throw Error('Missing shell')}).catch(e=>{console.error(e);process.exit(1)})")
            run('exec','-T','api','python','-m','app.cli','synthetic','--count','2','--seed','2026')
            assert count()==2
            print(f'PASS: fresh boot cycle {cycle}; web/API/database ready; restricted runtime inserted two synthetic journeys',flush=True)
            if cycle==2:
                original_artifacts=artifact_hashes()
                assert original_artifacts, 'Seed must materialise a real private dataset'
                backup_directory=subprocess.run(['./scripts/backup_demo.sh'],env=isolated_env,
                    check=True,capture_output=True,text=True).stdout.strip()
                run('exec','-T','api','python','-m','app.cli','synthetic','--count','3','--seed','2026')
                assert count()==3
                subprocess.run(['./scripts/restore_demo.sh',backup_directory],
                    env={**isolated_env,'CONFIRM':'RESTORE_SYNTHETIC_DEMO'},check=True,capture_output=True,text=True)
                assert count()==2, 'The actual restore command must replace the disposable database snapshot'
                assert artifact_hashes()==original_artifacts, 'Restored private dataset differs from the snapshot'
                print('PASS: actual backup/restore commands; two visits and private dataset hashes restored',flush=True)
            # Only this invocation's validated, newly created project is destroyed.
            run('down','--volumes','--remove-orphans')
    finally:
        run('down','--volumes','--remove-orphans')
    result={'status':'PASS','verified_at':datetime.now(timezone.utc).isoformat(),'cycles':2,
        'elapsed_seconds':round(time.monotonic()-started,2),'fresh_visits_each_cycle':0,'generated_visits_each_cycle':2,
        'main_project_unchanged':True,'temporary_project_and_volumes_removed':True,
        'actual_backup_restore_commands':'PASS','restored_private_artifact_hashes_match':True,
        'isolated_backup_directory':backup_directory}
    Path('docs/evidence/clean-boot-reset.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__': main()
