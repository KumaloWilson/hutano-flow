"""Create and retain a synthetic busy-clinic demonstration through the real API.

Requires the running local stack and generated completed synthetic journeys.
No existing patient record, clinical category or staffing configuration is edited.
"""
import json
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
import httpx


def main():
    with httpx.Client(base_url='http://localhost:8000',timeout=30) as client:
        login=client.post('/api/v1/auth/login',json={'email':'research@demo.hutano.test','password':'DemoResearch1!'})
        login.raise_for_status();csrf=login.json()['csrf_token']
        def command(path,body=None):
            r=client.post('/api/v1'+path,json=body,headers={'X-CSRF-Token':csrf,'Idempotency-Key':str(uuid.uuid4())});r.raise_for_status();return r.json()
        def read(path):
            r=client.get('/api/v1'+path);r.raise_for_status();return r.json()
        def wait(job):
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                state=read('/research/jobs/'+job)
                if state['status']=='COMPLETED': return
                if state['status']=='FAILED': raise RuntimeError(state['error'])
                time.sleep(.5)
            raise RuntimeError('Durable job exceeded verification deadline; inspect Recent research jobs')
        scenario=command('/experiments/scenarios',{'name':'Verified busy clinic · 50 arrivals','rationale':'Synthetic reproducibility verification; not observed patient outcomes.','config':{}})
        results=[];ids=[]
        for _ in range(2):
            run=command(f"/experiments/scenarios/{scenario['id']}/run");wait(run['job_id'])
            result=read('/experiments/runs/'+run['id']);assert result['status']=='COMPLETED'
            results.append(result['results']);ids.append(run['id'])
        assert results[0]==results[1], 'Repeated worker runs must reproduce all metrics and traces'
        result=results[0];assert result['config']['patients']==50 and result['config']['rooms']==3
        training=command('/operations/prediction/train');wait(training['job_id'])
        prediction=read('/operations/prediction');assert prediction['model'] is not None
        destination=Path('docs/evidence');destination.mkdir(parents=True,exist_ok=True)
        for fmt in ['json','csv','svg']:
            response=client.get(f'/api/v1/experiments/runs/{ids[0]}/export',params={'format':fmt});response.raise_for_status()
            (destination/f'busy-clinic.{fmt}').write_bytes(response.content)
        (destination/'operational-prediction.json').write_text(json.dumps(prediction,indent=2)+'\n')
        base=next(s for s in result['sensitivities'] if s['demand_multiplier']==1)
        report={'verified_at':datetime.now(timezone.utc).isoformat(),'status':'PASS','scenario_id':scenario['id'],'run_ids':ids,
            'config_hash':result['config_hash'],'identical_repeated_worker_results':True,'patients':50,'rooms':3,
            'replications':result['config']['replications'],'paired_input_hashes':result['input_hashes'],
            'base_demand':base,'operational_model':prediction['model']['version'],'clinical_priority_mutations':0}
        (destination/'enhancement-demo.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':'PASS','repeated_results_identical':True,'base_demand':base['policies'],
            'paired_capacity_minus_fixed':base['paired_capacity_minus_fixed_minutes'],'paired_95_ci':base['paired_95_ci'],
            'operational_model':prediction['model']['metrics']},indent=2))


if __name__=='__main__': main()
