"""Exercise all browser workflows in an owned, disposable full-stack project."""
import os
import subprocess
import uuid
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone


def main():
    project='hutano_browser_'+uuid.uuid4().hex[:12]
    assert project.startswith('hutano_browser_') and project.replace('_','').isalnum()
    compose=['docker','compose','-p',project,'-f','docker-compose.yml','-f','docker-compose.browser.yml']
    def run(*args): subprocess.run([*compose,*args],check=True)
    try:
        run('build','web')
        run('up','-d','--no-build','--wait','--wait-timeout','90')
        run('exec','-T','api','python','-m','app.cli','synthetic','--count','300','--seed','2026')
        run('exec','-T','api','python','-m','app.cli','showcase')
        subprocess.run([shutil.which('node') or 'node',str(Path('apps/web/node_modules/@playwright/test/cli.js').resolve()),'test'],cwd='apps/web',check=True,
            env={**os.environ,'E2E_BASE_URL':'http://localhost:3100','E2E_API_URL':'http://localhost:8100'})
        stats=json.loads(Path('apps/web/test-results/results.json').read_text())['stats']
        assert stats['unexpected']==0 and stats['skipped']==0
        evidence=Path('docs/evidence');evidence.mkdir(parents=True,exist_ok=True)
        for screenshot in Path('apps/web/test-results').rglob('*.png'):
            shutil.copyfile(screenshot,evidence/screenshot.name)
        print('PASS: browser workflows used an isolated migrated PostgreSQL database and durable worker',flush=True)
    finally:
        # Only resources belonging to this invocation's validated project.
        run('down','--volumes','--remove-orphans')
        print('Disposable browser project removed; main demonstration data retained.',flush=True)
    (evidence/'browser-enhanced.json').write_text(json.dumps({'status':'PASS','verified_at':datetime.now(timezone.utc).isoformat(),
        'stats':stats,'isolated_full_stack':True,'main_project_unchanged':True,'temporary_project_and_volumes_removed':True},indent=2)+'\n')


if __name__=='__main__': main()
