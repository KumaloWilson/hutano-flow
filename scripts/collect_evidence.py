"""Collect aggregate evidence from the running synthetic API and durable worker."""
import hashlib
import json
import time
import uuid
from pathlib import Path
import httpx

OUT=Path('docs/evidence')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with httpx.Client(base_url='http://localhost:8000',timeout=30) as client:
        result=client.post('/api/v1/auth/login',json={'email':'research@demo.hutano.test','password':'DemoResearch1!'})
        result.raise_for_status()
        csrf=result.json()['csrf_token']
        def save(name,data):
            (OUT/name).write_text(json.dumps(data,indent=2)+'\n')
        def get(path):
            response=client.get(path);response.raise_for_status();return response
        def simulation(config):
            submitted=client.post('/api/v1/simulations',json=config,headers={'X-CSRF-Token':csrf,'Idempotency-Key':str(uuid.uuid4())})
            submitted.raise_for_status();job=submitted.json()
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                state=get('/api/v1/research/jobs/'+job['job_id']).json()
                if state['status']=='FAILED': raise RuntimeError(state['error'])
                if state['status']=='COMPLETED': break
                time.sleep(1)
            else: raise TimeoutError('Worker did not finish within 120 seconds')
            return job['id'],get('/api/v1/simulations/'+job['id']+'/export').json()
        config={'name':'Paired synthetic evidence','patient_count':300,'replications':10,'seed':2026}
        run_id,normal=simulation(config)
        _,repeated=simulation(config)
        assert normal==repeated, 'Identical simulation parameters did not reproduce results'
        save('simulation-standard.json',normal)
        for fmt in ['csv','svg']:
            (OUT/f'simulation-standard.{fmt}').write_text(get(f'/api/v1/simulations/{run_id}/export?format={fmt}').text)
        _,no_gain=simulation({**config,'name':'Same-category no-benefit control','urgency_mix':[0,0,1,0,0]})
        assert no_gain['comparison']['absolute_mean_difference_minutes']==0
        assert not no_gain['comparison']['hybrid_improved_mean_wait']
        save('simulation-no-improvement.json',no_gain)
        _,no_capacity=simulation({**config,'name':'Zero consultation capacity','consultation_servers':0})
        assert all(p['completed_mean']==0 and p['unserved_mean']==300 for p in no_capacity['policies'].values())
        save('simulation-zero-capacity.json',no_capacity)
        save('simulation-reproducibility.json',{'status':'PASS','replications':10,'patients_per_replication':300,
            'repeated_results_identical':True,'result_sha256':hashlib.sha256(json.dumps(normal,sort_keys=True).encode()).hexdigest(),
            'same_category_hybrid_difference_minutes':0,'zero_capacity_unserved_per_replication':300})
        analytics=get('/api/v1/analytics/overview').json()
        assert analytics['completed_visits']>=300
        save('analytics-synthetic.json',analytics)
        for fmt in ['csv','svg']:
            (OUT/f'analytics-synthetic.{fmt}').write_text(get('/api/v1/analytics/export?format='+fmt).text)
        models=get('/api/v1/research/models').json()
        assert models, 'Train a synthetic research model through the UI first'
        save('model-evaluation.json',{'research_only':True,'version':models[0]['version'],
            'status':models[0]['status'],'active':models[0]['active'],'metrics':models[0]['metrics']})
        print('PASS: >=300 completed journeys; paired reproducibility, no-benefit and zero-capacity controls; model evaluation exported.')


if __name__=='__main__': main()
