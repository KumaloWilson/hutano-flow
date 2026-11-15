"""Finite-day, paired resource-assignment research with full synthetic event traces."""
import hashlib
import json
from dataclasses import asdict
import numpy as np
import simpy
from scipy.stats import t
from app.simulation.engine import generate_patients, summary, URGENCY_ORDER

POLICIES=['FIXED_ROOM','NEXT_AVAILABLE','CAPACITY_AWARE']
VERSION='staffed-room-experiment-v1'


def inputs(config,seed,demand=1.):
    rng=np.random.default_rng(seed+100000)
    patients=generate_patients(seed,config['patients'],config['arrivals_per_hour']*demand,config['mean_service_minutes'],service_tail=config['service_tail'])
    return [{**asdict(p),'lab':bool(rng.random()<config['laboratory_probability']),
        'no_show':bool(rng.random()<config['no_show_probability']), 'returns':bool(rng.random()<.7),
        'lab_minutes':float(rng.lognormal(np.log(12)-.125,.5))} for p in patients]


def once(patients,config,policy):
    env=simpy.Environment();horizon=config['horizon_minutes'];count=config['rooms']
    points={'registration':simpy.Resource(env,2),'triage':simpy.Resource(env,1),'laboratory':simpy.Resource(env,1),'pharmacy':simpy.Resource(env,1)}
    waits=[];by_urgency={p:[] for p in URGENCY_ORDER};completed=0;no_shows=0;returned=0;arrived=0
    queue=[];signal=simpy.Store(env);busy=[False]*count;room_busy=[0.]*count;room_assignments=[0]*count
    traces={str(p['patient_no']):[] for p in patients};timeline=[];assignments=[]
    speeds=config['room_speed_factors'];shifts=config['room_shifts'];blocks=config['blocks']
    def available(room):
        start,end=shifts[room]
        return start<=env.now<end and not any(b['room']==room and b['start']<=env.now<b['start']+b['duration'] for b in blocks)
    def changed():
        timeline.append({'minute':round(float(env.now),3),'waiting':len(queue),'busy_rooms':sum(busy),'available_rooms':sum(available(r) and not busy[r] for r in range(count))})
    def wake(at):
        yield env.timeout(at);changed();yield signal.put(True)
    def urgency(item):
        p,queued,_,_=item
        return URGENCY_ORDER[p['urgency']],queued,p['patient_no']
    def work(room,item):
        p,queued,done,return_visit=item;started=float(env.now)
        absent=p['no_show'] and not return_visit
        duration=3. if absent else p['service']*speeds[room]*(.5 if return_visit else 1.)
        record={'stage':'consultation_return' if return_visit else 'consultation','room':room+1,'queued':queued,'started':started,'ended':None,'status':'IN_SERVICE','wait':started-queued}
        traces[str(p['patient_no'])].append(record)
        room_assignments[room]+=1
        room_busy[room]+=max(0,min(duration,horizon-env.now))
        assignments.append({'patient_no':p['patient_no'],'room':room+1,'minute':started,'policy':policy,'reason':
            'Fixed round-robin room' if policy=='FIXED_ROOM' else 'First free compatible room' if policy=='NEXT_AVAILABLE' else 'Available room with earliest expected completion using population service mean; patient ordering remains urgency then arrival'})
        yield env.timeout(duration)
        record['ended']=float(env.now);record['status']='NO_SHOW' if absent else 'COMPLETED'
        busy[room]=False;changed();done.succeed((started-queued,absent));yield signal.put(True)
    def dispatcher():
        while True:
            free=[r for r in range(count) if available(r) and not busy[r]]
            dispatched=False
            while free and queue:
                if policy=='FIXED_ROOM':
                    pairs=[(r,min([q for q in queue if (q[0]['patient_no']-1)%count==r],key=urgency)) for r in free if any((q[0]['patient_no']-1)%count==r for q in queue)]
                    if not pairs: break
                    room,item=min(pairs,key=lambda pair:urgency(pair[1]))
                else:
                    item=min(queue,key=urgency)
                    room=min(free,key=lambda r:(config['mean_service_minutes']*speeds[r],room_assignments[r],r)) if policy=='CAPACITY_AWARE' else min(free)
                queue.remove(item);free.remove(room);busy[room]=True;changed();env.process(work(room,item));dispatched=True
            if not dispatched: yield signal.get()
    def consultation(p,is_return=False):
        done=env.event();queue.append((p,float(env.now),done,is_return));changed();yield signal.put(True)
        outcome=yield done
        return outcome
    def stage(p,name,duration):
        queued=float(env.now)
        record={'stage':name,'queued':queued,'started':None,'ended':None,'status':'WAITING','wait':None}
        traces[str(p['patient_no'])].append(record)
        with points[name].request() as request:
            yield request;record.update(started=float(env.now),status='IN_SERVICE',wait=float(env.now)-queued)
            yield env.timeout(duration);record.update(ended=float(env.now),status='COMPLETED')
        return record['wait']
    def journey(p):
        nonlocal completed,no_shows,returned,arrived
        yield env.timeout(p['arrival']);arrived+=1;own=[]
        own.append((yield env.process(stage(p,'registration',p['registration']))))
        own.append((yield env.process(stage(p,'triage',p['triage']))))
        wait,absent=yield env.process(consultation(p));own.append(wait)
        if absent:
            no_shows+=1
            if not p['returns']: return
            yield env.timeout(config['return_delay_minutes']);returned+=1
            wait,_=yield env.process(consultation(p,True));own.append(wait)
        if p['lab']:
            own.append((yield env.process(stage(p,'laboratory',p['lab_minutes']))))
            wait,_=yield env.process(consultation(p,True));own.append(wait)
        if p['needs_pharmacy']: own.append((yield env.process(stage(p,'pharmacy',p['pharmacy']))))
        completed+=1;waits.append(sum(own));by_urgency[p['urgency']].append(sum(own))
    env.process(dispatcher())
    for room,(start,end) in enumerate(shifts):
        for at in [start,end]:
            if 0<at<horizon: env.process(wake(at))
    for b in blocks:
        for at in [b['start'],b['start']+b['duration']]:
            if 0<=at<horizon: env.process(wake(at))
    for p in patients: env.process(journey(p))
    env.run(until=horizon);changed()
    # Retain not-started consultation episodes as well as completed traces.
    for p,queued,_,is_return in queue:
        traces[str(p['patient_no'])].append({'stage':'consultation_return' if is_return else 'consultation','queued':queued,'started':None,'ended':None,'status':'WAITING','wait':None})
    capacity=[]
    for room in range(count):
        cuts=sorted({0.,float(horizon),*[max(0,min(horizon,v)) for v in shifts[room]],
            *[max(0,min(horizon,v)) for b in blocks if b['room']==room for v in [b['start'],b['start']+b['duration']]]})
        minutes=sum(b-a for a,b in zip(cuts,cuts[1:]) if shifts[room][0]<=(a+b)/2<shifts[room][1] and not any(x['room']==room and x['start']<=(a+b)/2<x['start']+x['duration'] for x in blocks))
        capacity.append({'room':room+1,'scheduled_available_minutes':minutes,'occupied_minutes':room_busy[room],
            'utilisation':room_busy[room]/minutes if minutes else None,'assignments':room_assignments[room]})
    return {'completed':completed,'arrived':arrived,'unserved':arrived-completed,'not_arrived':len(patients)-arrived,'no_shows':no_shows,'returned':returned,
        'waiting_minutes':summary(waits),'by_urgency':{u:summary(v) for u,v in by_urgency.items()},'low_urgency_long_waits':sum(x>=60 for u in ['P4','P5'] for x in by_urgency[u]),
        'rooms':capacity,'queue_timeline':timeline,'traces':traces,'assignments':assignments}


def run_experiment(config):
    sensitivities=[];base_replay={};hashes=[]
    for demand in config['demand_multipliers']:
        runs={policy:[] for policy in POLICIES};shared=[]
        for rep in range(config['replications']):
            cohort=inputs(config,config['seed']+rep,demand)
            shared.append(hashlib.sha256(json.dumps(cohort,sort_keys=True).encode()).hexdigest())
            for policy in POLICIES:
                outcome=once(cohort,config,policy);runs[policy].append(outcome)
                if demand==1. and rep==0: base_replay[policy]=outcome
        metrics={}
        for policy,results in runs.items():
            means=[r['waiting_minutes']['mean'] for r in results if r['waiting_minutes']['mean'] is not None]
            p90s=[r['waiting_minutes']['p90'] for r in results if r['waiting_minutes']['p90'] is not None]
            metrics[policy]={'mean_wait_minutes':float(np.mean(means)) if means else None,'mean_replication_p90_minutes':float(np.mean(p90s)) if p90s else None,
                'completed_mean':float(np.mean([r['completed'] for r in results])),'unserved_mean':float(np.mean([r['unserved'] for r in results])),
                'low_urgency_long_waits':sum(r['low_urgency_long_waits'] for r in results),
                'mean_wait_by_urgency':{u:(float(np.mean([r['by_urgency'][u]['mean'] for r in results if r['by_urgency'][u]['mean'] is not None])) if any(r['by_urgency'][u]['mean'] is not None for r in results) else None) for u in URGENCY_ORDER}}
        differences=[a['waiting_minutes']['mean']-b['waiting_minutes']['mean'] for a,b in zip(runs['CAPACITY_AWARE'],runs['FIXED_ROOM']) if a['waiting_minutes']['mean'] is not None and b['waiting_minutes']['mean'] is not None]
        delta=float(np.mean(differences)) if differences else None;ci=None
        if len(differences)>1:
            margin=float(t.ppf(.975,len(differences)-1)*np.std(differences,ddof=1)/np.sqrt(len(differences)));ci=[delta-margin,delta+margin]
        sensitivities.append({'demand_multiplier':demand,'policies':metrics,'paired_capacity_minus_fixed_minutes':delta,'paired_95_ci':ci,'input_hashes':shared})
        if demand==1.: hashes=shared
    return {'research_label':'SYNTHETIC RESOURCE-ASSIGNMENT EXPERIMENT — NOT CLINICAL EVIDENCE','engine_version':VERSION,'config':config,
        'config_hash':hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),'input_hashes':hashes,'sensitivities':sensitivities,'replay':base_replay,
        'ablations':[{'removed':'Resource-aware room selection','comparator':'NEXT_AVAILABLE'},{'removed':'Pooling across compatible rooms','comparator':'FIXED_ROOM'}],
        'definitions':{'primary':'Sum of queue waits across each completed outpatient journey; no-show absence and service excluded',
            'p90':'Mean of replication-specific P90s, not pooled P90','horizon':'Finite observation day; unfinished and not-yet-arrived patients reported separately',
            'room_speeds':'Synthetic resource heterogeneity, not patient-priority weights','outages':'Non-preemptive; started work completes and may overrun scheduled availability'},
        'limitations':['Synthetic assumptions, not fieldwork','Completed-only means can have selection bias; inspect unserved counts',
            'All urgency labels are synthetic inputs; no autonomous clinical decision','Staffed-room experiment extends rather than replaces the existing FCFS/urgency/hybrid baseline',
            'Population service means guide room choice; individual predicted duration never changes patient order']}
