import json
import uuid
import numpy as np
import pandas as pd
import pytest
from app.ml.pipeline import generate_synthetic_training_data, train_model, explain_prediction, validate_frame
from app.baseline import inspect_baseline
from app.simulation.engine import run_comparison
from conftest import login, command_headers


@pytest.fixture(scope='module')
def trained(tmp_path_factory):
    frame = generate_synthetic_training_data(8, 300)
    return train_model(frame, tmp_path_factory.mktemp('model'), 8)


def test_training_evaluation_and_explanation(trained):
    metrics = trained['metrics']
    assert metrics['train_rows'] == 240 and metrics['test_rows'] == 60
    assert metrics['label_source'] == 'SYNTHETIC'
    assert len(metrics['confusion_matrix']) == 5
    assert sum(map(sum, metrics['confusion_matrix'])) == 60
    assert set(metrics['comparators']) == {'majority','random_forest'}
    assert metrics['calibration']['bins']
    assert metrics['duration']['median_baseline_mae_minutes'] >= 0
    assert 'temporal' in metrics['split_strategy']
    prediction = explain_prediction(trained['artifact_path'], {'age_band':'adult','visit_type':'new','arrival_mode':'walk_in','hour':9,'recorded_measurement':0})
    assert prediction['requires_clinician_review']
    assert prediction['factors']
    assert sum(f['logit_contribution'] for f in prediction['factors']) + prediction['other_logit_contributions'] + prediction['intercept'] == pytest.approx(prediction['class_logit'])
    assert 'NOT VALIDATED' in prediction['warning']


def test_training_reproducible(trained, tmp_path):
    again = train_model(generate_synthetic_training_data(8,300),tmp_path,8)
    assert again['metrics'] == trained['metrics']
    assert again['version'] == trained['version']


@pytest.mark.parametrize('features', [{}, {'age_band':'unseen','visit_type':'new','arrival_mode':'walk_in','hour':9,'recorded_measurement':0}, {'age_band':'adult','visit_type':'new','arrival_mode':'walk_in','hour':100,'recorded_measurement':0}])
def test_missing_or_out_of_distribution_abstains(trained, features):
    prediction = explain_prediction(trained['artifact_path'],features)
    assert prediction['suggestion'] is None and prediction['abstained']


def test_import_rejects_identifiers_duplicates_bad_labels():
    for mutate in [lambda df:df.assign(full_name='Forbidden'),lambda df:pd.concat([df,df.iloc[:1]]),lambda df:df.assign(urgency='X')]:
        with pytest.raises(ValueError):
            validate_frame(mutate(generate_synthetic_training_data(8,100)))


BASELINE = b'journey_no,stage,arrived_at,queued_at,started_at,ended_at\n1,registration,2026-01-01T08:00:00Z,2026-01-01T08:00:00Z,2026-01-01T08:10:00Z,2026-01-01T08:15:00Z\n1,consultation,2026-01-01T08:00:00Z,2026-01-01T08:15:00Z,2026-01-01T08:25:00Z,2026-01-01T08:35:00Z\n'


def test_baseline_exact_formulas():
    _, report = inspect_baseline(BASELINE,{})
    assert report['waiting_minutes']['mean'] == 10
    assert report['service_minutes']['mean'] == 7.5
    assert report['arrival_to_provider_minutes']['mean'] == 25
    assert report['total_visit_minutes']['mean'] == 35
    with pytest.raises(ValueError):
        inspect_baseline(BASELINE.replace(b'08:25:00Z',b'08:05:00Z'),{})


def test_baseline_preview_and_registration(client):
    csrf = login(client,'research@test.local')
    data = {'name':'Baseline test','provenance':'Synthetic timestamps only','preview_only':'true'}
    result = client.post('/api/v1/research/baseline/import', files={'file':('baseline.csv',BASELINE,'text/csv')}, data=data, headers=command_headers(csrf,str(uuid.uuid4())))
    assert result.status_code == 201, result.text
    assert result.json()['preview_only']
    data['preview_only']='false'
    result = client.post('/api/v1/research/baseline/import',files={'file':('baseline.csv',BASELINE,'text/csv')},data=data,headers=command_headers(csrf,str(uuid.uuid4())))
    assert result.status_code == 201 and result.json()['id']


def test_no_forced_simulation_benefit():
    result = run_comparison(seed=2026,patient_count=60,replications=2,servers=2,arrival_rate_per_hour=12,mean_service_minutes=8,urgency_mix=[0,0,1,0,0])
    assert result['policies']['FCFS']['waiting_minutes'] == result['policies']['HYBRID']['waiting_minutes']
    assert result['comparison']['hybrid_improved_mean_wait'] is False
    assert result['comparison']['absolute_mean_difference_minutes'] == 0
    assert len(result['input_sequence_hashes']) == 2


def test_model_review_and_activation_authority(client, db_session, trained):
    from sqlalchemy import select
    from app.models import Dataset, ModelVersion
    dataset = db_session.scalar(select(Dataset))
    model = ModelVersion(facility_id=dataset.facility_id,model_name='Test synthetic classifier',version=trained['version'],
        artifact_path=trained['artifact_path'],feature_schema_hash=trained['feature_schema_hash'],dataset_id=dataset.id,metrics_json=trained['metrics'])
    db_session.add(model);db_session.commit()
    path = f'/api/v1/research/models/{model.id}/lifecycle'
    csrf = login(client,'admin@test.local')
    result = client.post(path,json={'action':'ACTIVATE','reason':'Demo activation'},headers=command_headers(csrf,str(uuid.uuid4())))
    assert result.status_code == 409
    csrf = login(client,'research@test.local')
    assert client.post(path,json={'action':'REVIEW','reason':'Forbidden research signoff'},headers=command_headers(csrf,str(uuid.uuid4()))).status_code == 403
    csrf = login(client,'clinician@test.local')
    assert client.post(path,json={'action':'REVIEW','reason':'Reviewed for software demo only'},headers=command_headers(csrf,str(uuid.uuid4()))).status_code == 200
    csrf = login(client,'admin@test.local')
    assert client.post(path,json={'action':'ACTIVATE','reason':'Enable synthetic advisory'},headers=command_headers(csrf,str(uuid.uuid4()))).status_code == 200


@pytest.mark.parametrize('decision', ['ACCEPT', 'REJECT', 'OVERRIDE'])
def test_real_advisory_requires_explicit_clinician_confirmation(client, db_session, trained, decision):
    import joblib
    from sqlalchemy import select
    from app.ml.pipeline import FEATURES
    from app.models import AuditEvent, Dataset, ModelVersion, TriageAssessment, User
    from test_workflow import create_registered_visit

    dataset=db_session.scalar(select(Dataset))
    clinician=db_session.scalar(select(User).where(User.email=='clinician@test.local'))
    db_session.add(ModelVersion(facility_id=dataset.facility_id,model_name='Synthetic API test',version=trained['version'],
        artifact_path=trained['artifact_path'],feature_schema_hash=trained['feature_schema_hash'],dataset_id=dataset.id,
        metrics_json=trained['metrics'],status='REVIEWED',active=True,reviewed_by=clinician.id))
    db_session.commit()
    # Select an actual in-range synthetic sample that the real model does not
    # abstain on. No mocked inference or clinically meaningful rule is introduced.
    frame=generate_synthetic_training_data(8,300)[FEATURES]
    probabilities=joblib.load(trained['artifact_path'])['pipeline'].predict_proba(frame)
    features=frame.iloc[int(np.argmax(probabilities.max(axis=1)))].to_dict()
    assert probabilities.max() >= .55
    csrf=login(client,'reception@test.local')
    visit=create_registered_visit(client,csrf)
    csrf=login(client,'clinician@test.local')
    response=client.post(f"/api/v1/visits/{visit['id']}/recommendation",json={'features':features},
        headers=command_headers(csrf,str(uuid.uuid4())))
    assert response.status_code==201, response.text
    advisory=response.json()
    assert advisory['suggestion'] and advisory['factors'] and not advisory['model_suggestion_applied_automatically']
    assert client.get(f"/api/v1/visits/{visit['id']}").json()['status']=='AWAITING_TRIAGE'
    assert db_session.scalar(select(TriageAssessment)) is None
    assert client.get(f"/api/v1/recommendations/{visit['id']}").json()[0]['id']==advisory['id']
    different='P1' if advisory['suggestion']!='P1' else 'P5'
    final=advisory['suggestion'] if decision=='ACCEPT' else different
    reviewed=client.post(f"/api/v1/recommendations/{advisory['id']}/decision",
        json={'decision':decision,'final_urgency':final,'justification':'Synthetic clinician research review'},
        headers=command_headers(csrf,str(uuid.uuid4())))
    assert reviewed.status_code==201 and reviewed.json()['authoritative_applied'] is False
    assert db_session.scalar(select(TriageAssessment)) is None
    payload={'configured_urgency':final,'reason':'Explicit clinician-confirmed synthetic assessment','observations':{},
        'escalation_required':False,'recommendation_decision':decision,'recommendation_id':advisory['id'],'version':visit['version']}
    if decision=='ACCEPT':
        mismatch=client.post(f"/api/v1/visits/{visit['id']}/triage",json={**payload,'configured_urgency':different},
            headers=command_headers(csrf,str(uuid.uuid4())))
        assert mismatch.status_code==422
    confirmed=client.post(f"/api/v1/visits/{visit['id']}/triage",json=payload,headers=command_headers(csrf,str(uuid.uuid4())))
    assert confirmed.status_code==201 and confirmed.json()['confirmed_urgency']==final
    audit=db_session.scalar(select(AuditEvent).where(AuditEvent.action=='triage.confirmed'))
    assert audit.actor_id==clinician.id and audit.metadata_json['recommendation_decision']==decision
