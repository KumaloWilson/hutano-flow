"""Durable PostgreSQL job worker; restart-safe with bounded stale-job retries."""
import time
import uuid
import logging
from datetime import timedelta
from pathlib import Path
import pandas as pd
from sqlalchemy import select
from app.config import settings
from app.database import SessionLocal
from app.models import Dataset, Job, ModelVersion, SimulationRun, OperationalModel, ExperimentRun, ResearchStudyRun, ResearchProtocol, utcnow
from app.ml.pipeline import train_model
from app.simulation.engine import run_comparison
from app.services.audit import enqueue_event, record_audit


def execute_job(db, job):
    if job.type == 'RESEARCH_OPERATIONS':
        from app.ml.operations_study import run_operations_study
        run = db.get(ResearchStudyRun, uuid.UUID(job.result_ref))
        if not run or run.facility_id != job.facility_id:
            raise ValueError('Supporting research run is not in this facility')
        protocol = db.get(ResearchProtocol, run.protocol_id)
        if not protocol or protocol.facility_id != job.facility_id or protocol.config_hash != job.config_json.get('protocol_hash') or protocol.config_json['operations_config'] != job.config_json.get('operations_config'):
            raise ValueError('Frozen protocol and job configuration do not match')
        if run.status != 'COMPLETED':
            run.results_json = {**run_operations_study(job.config_json['operations_config']), 'protocol_hash': protocol.config_hash}
            run.status = 'COMPLETED'
            run.error_summary = None
        ref = str(run.id); topic = 'simulation.completed'
    elif job.type == 'EXPERIMENT':
        from app.simulation.experiments import run_experiment
        run=db.get(ExperimentRun,uuid.UUID(job.result_ref))
        if not run or run.facility_id!=job.facility_id: raise ValueError('Experiment is not in this facility')
        run.results_json=run_experiment(job.config_json);run.status='COMPLETED'
        ref=str(run.id);topic='simulation.completed'
    elif job.type == 'OPERATIONAL_TRAIN':
        from app.operational_prediction import fit_duration, duration_rows
        outcome=fit_duration(duration_rows(db,job.facility_id),settings.model_artifact_dir/str(job.facility_id))
        model=db.scalar(select(OperationalModel).where(OperationalModel.facility_id==job.facility_id,OperationalModel.version==outcome['version']))
        if not model:
            model=OperationalModel(facility_id=job.facility_id,version=outcome['version'],dataset_hash=outcome['dataset_hash'],artifact_path=outcome['artifact_path'],metrics_json=outcome['metrics'])
            db.add(model);db.flush()
        else: model.artifact_path=outcome['artifact_path']
        ref=str(model.id);topic='model.training_completed'
    elif job.type == "SIMULATION":
        run = db.get(SimulationRun, uuid.UUID(job.result_ref))
        result = run_comparison(**job.config_json)
        run.results_json = result
        run.status = "COMPLETED"
        run.finished_at = utcnow()
        topic = "simulation.completed"
        ref = str(run.id)
    elif job.type == "MODEL_TRAIN":
        dataset = db.scalar(select(Dataset).where(Dataset.id == uuid.UUID(job.config_json["dataset_id"]), Dataset.facility_id == job.facility_id))
        if not dataset or not dataset.synthetic_flag or not dataset.file_path:
            raise ValueError("A registered synthetic dataset file is required")
        outcome = train_model(pd.read_csv(dataset.file_path), settings.model_artifact_dir / str(job.facility_id), job.config_json["seed"])
        model = db.scalar(select(ModelVersion).where(ModelVersion.facility_id == job.facility_id, ModelVersion.version == outcome["version"]))
        if not model:
            model = ModelVersion(facility_id=job.facility_id, model_name="Synthetic urgency demonstration", version=outcome["version"],
                artifact_path=outcome["artifact_path"], feature_schema_hash=outcome["feature_schema_hash"],
                dataset_id=dataset.id, metrics_json={**outcome["metrics"], "source_dataset_hash": dataset.dataset_hash}, status="EXPERIMENTAL", active=False)
            db.add(model)
            db.flush()
        else:
            # Reproducing an identical version may re-materialise its private file
            # after moving the demo artifact root; it does not activate the model.
            model.artifact_path = outcome["artifact_path"]
        if job.config_json.get("demo_enable_advisory"):
            from app.demo_clinic import apply_demo_review
            apply_demo_review(db, job, model)
        ref = str(model.id)
        topic = "model.training_completed"
    else:
        raise ValueError("Unknown research job type")
    job.status = "COMPLETED"
    job.result_ref = ref
    job.error_summary = None
    enqueue_event(db, facility_id=job.facility_id, topic=topic, aggregate_id=ref, payload={"job_id": str(job.id), "status": "COMPLETED"})
    record_audit(db, facility_id=job.facility_id, actor_id=None, action=topic, object_type="Job", object_id=job.id,
                 correlation_id=str(job.id), new={"result_ref": ref, "synthetic": True})


def work_once(session_factory=SessionLocal):
    with session_factory() as db:
        # Row locks prevent two workers claiming the same command. Lease recovery covers crashes.
        stale = db.scalars(select(Job).where(Job.status == "RUNNING", Job.updated_at < utcnow() - timedelta(minutes=15)).with_for_update(skip_locked=True)).all()
        for job in stale:
            job.status = "PENDING" if job.attempt_count < 3 else "FAILED"
            job.error_summary = "Worker interrupted; automatic retry limit reached" if job.status == "FAILED" else None
            if job.status == "FAILED" and job.type == "SIMULATION":
                run = db.get(SimulationRun, uuid.UUID(job.result_ref))
                if run:
                    run.status = "FAILED"
            if job.status == 'FAILED' and job.type == 'EXPERIMENT':
                run=db.get(ExperimentRun,uuid.UUID(job.result_ref))
                if run: run.status='FAILED'
            if job.status == 'FAILED' and job.type == 'RESEARCH_OPERATIONS':
                run=db.get(ResearchStudyRun,uuid.UUID(job.result_ref))
                if run and run.status != 'COMPLETED':
                    run.status='FAILED'; run.error_summary=job.error_summary
        db.flush()
        job = db.scalar(select(Job).where(Job.status == "PENDING").order_by(Job.created_at).with_for_update(skip_locked=True).limit(1))
        if not job:
            db.commit()
            return False
        job.status = "RUNNING"
        if job.type=='EXPERIMENT':
            run=db.get(ExperimentRun,uuid.UUID(job.result_ref))
            if run: run.status='RUNNING'
        if job.type == 'RESEARCH_OPERATIONS':
            run=db.get(ResearchStudyRun,uuid.UUID(job.result_ref))
            if run and run.status != 'COMPLETED': run.status='RUNNING'
        job.attempt_count += 1
        job_id = job.id
        db.commit()
    with session_factory() as db:
        job = db.get(Job, job_id)
        try:
            execute_job(db, job)
            db.commit()
        except Exception as error:
            logging.error("Research job %s failed (%s)", job_id, type(error).__name__)
            db.rollback()
            job = db.get(Job, job_id)
            job.status = "FAILED"
            job.error_summary = str(error)[:240] if isinstance(error, ValueError) else "Job failed; inspect local worker diagnostics"
            if job.type == "SIMULATION":
                run = db.get(SimulationRun, uuid.UUID(job.result_ref))
                run.status = "FAILED"
            if job.type == 'EXPERIMENT':
                run=db.get(ExperimentRun,uuid.UUID(job.result_ref))
                if run: run.status='FAILED'
            if job.type == 'RESEARCH_OPERATIONS':
                run=db.get(ResearchStudyRun,uuid.UUID(job.result_ref))
                if run and run.status != 'COMPLETED':
                    run.status='FAILED'; run.error_summary=job.error_summary
            db.commit()
    return True


if __name__ == "__main__":
    while True:
        try:
            if not work_once():
                time.sleep(1)
        except Exception as error:
            logging.error("Worker polling failed (%s); retrying", type(error).__name__)
            time.sleep(3)
