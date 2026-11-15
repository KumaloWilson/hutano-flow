"""Verify a logical backup in a new disposable database; never replace the demo.

Run from the repository root with Docker Compose running. Only the uniquely
named database created by this invocation is removed. No credentials are logged.
"""
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


def docker(command, data=None):
    return subprocess.run(['docker','compose','exec','-T','db','sh','-c',command],
        input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout


SNAPSHOT = """
SELECT json_build_object(
  'patients',(SELECT count(*) FROM patients),
  'visits',(SELECT count(*) FROM visits),
  'completed_visits',(SELECT count(*) FROM visits WHERE status='COMPLETED'),
  'episodes',(SELECT count(*) FROM service_episodes),
  'audit_events',(SELECT count(*) FROM audit_events),
  'models',(SELECT count(*) FROM model_versions),
  'operational_models',(SELECT count(*) FROM operational_models),
  'observations',(SELECT count(*) FROM observations),
  'encounter_notes',(SELECT count(*) FROM encounter_notes),
  'handovers',(SELECT count(*) FROM handovers),
  'rooms',(SELECT count(*) FROM rooms),
  'staff_shifts',(SELECT count(*) FROM staff_shifts),
  'resource_blocks',(SELECT count(*) FROM resource_blocks),
  'resource_assignments',(SELECT count(*) FROM resource_assignments),
  'scenario_versions',(SELECT count(*) FROM experiment_scenario_versions),
  'experiment_runs',(SELECT count(*) FROM experiment_runs),
  'research_protocols',(SELECT count(*) FROM research_protocols),
  'research_cases',(SELECT count(*) FROM research_cases),
  'research_case_reviews',(SELECT count(*) FROM research_case_reviews),
  'research_case_adjudications',(SELECT count(*) FROM research_case_adjudications),
  'research_trials',(SELECT count(*) FROM research_trials),
  'research_study_runs',(SELECT count(*) FROM research_study_runs),
  'research_protocol_digest',(SELECT md5(coalesce(string_agg(id::text || config_hash,'' ORDER BY id),'')) FROM research_protocols),
  'research_trial_digest',(SELECT md5(coalesce(string_agg(id::text || status || inference_json::text || response_json::text,'' ORDER BY id),'')) FROM research_trials),
  'research_study_digest',(SELECT md5(coalesce(string_agg(id::text || status || results_json::text,'' ORDER BY id),'')) FROM research_study_runs),
  'experiment_digest',(SELECT md5(coalesce(string_agg(id::text || status || results_json::text,'' ORDER BY id),'')) FROM experiment_runs),
  'workspace_digest',(SELECT md5(coalesce(string_agg(id::text || text,'' ORDER BY id),'')) FROM encounter_notes),
  'audit_digest',(SELECT md5(coalesce(string_agg(id::text || action || coalesce(new_hash,''),'' ORDER BY id),'')) FROM audit_events),
  'timing_digest',(SELECT md5(coalesce(string_agg(id::text || status || coalesce(started_at::text,'') || coalesce(ended_at::text,''),'' ORDER BY id),'')) FROM service_episodes)
);
"""


def main():
    target='hutano_restore_verify_'+uuid.uuid4().hex
    assert target.startswith('hutano_restore_verify_') and target.replace('_','').isalnum()
    owner_psql='psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    before=json.loads(docker(owner_psql,SNAPSHOT.encode()))
    archive=docker('pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"')
    docker(owner_psql,f'CREATE DATABASE {target};'.encode())
    try:
        docker(f'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d {target}',archive)
        restored=json.loads(docker(f'psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d {target}',SNAPSHOT.encode()))
        assert before == restored, 'Restored data differs from the source snapshot'
    finally:
        docker(owner_psql,f'DROP DATABASE {target};'.encode())
    evidence={'verified_at':datetime.now(timezone.utc).isoformat(),'status':'PASS',
        'method':'pg_dump -Fc; pg_restore into a unique empty database; compare counts and audit/timing digests',
        'archive_bytes':len(archive),'snapshot':before,'source_database_unchanged':True,
        'temporary_database_removed':True,'scope':'Logical database restore; encrypted storage and disaster recovery not certified'}
    output=Path('docs/evidence/backup-restore.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(evidence,indent=2)+'\n')
    print(f'PASS: restored counts and integrity digests match; disposable database removed. Evidence: {output}')


if __name__=='__main__':
    main()
