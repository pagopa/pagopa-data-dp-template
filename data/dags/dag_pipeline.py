from __future__ import annotations

import json
from datetime import datetime, timedelta

from airflow import DAG
from cloudera.airflow.providers.operators.cde import CdeRunJobOperator

ENV = "${env.name}"
DP_NAME = "${dp.name}"
DOMAIN = "${dp.domain}"
PAUSED = json.loads("${env.dags.schedulePaused}")


def job(name: str) -> CdeRunJobOperator:
    return CdeRunJobOperator(task_id=name, job_name=f"{DP_NAME}-{name}-{ENV}")


with DAG(
    dag_id=f"{DP_NAME}-pipeline-{ENV}",
    schedule=None,  # TODO: cron della pipeline
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=PAUSED,
    default_args={"owner": "${dp.owner}", "retries": 1, "retry_delay": timedelta(minutes=10)},
    tags=["data-product", DP_NAME, DOMAIN],
) as dag:
    job("ingestion") >> job("deduplication") >> job("export")
