from __future__ import annotations

import json
from datetime import datetime, timedelta

from airflow import DAG
from cloudera.airflow.providers.operators.cde import CdeRunJobOperator

ENV = "${env.name}"
DP_NAME = "${dp.name}"
DOMAIN = "${dp.domain}"
OUTPUT_PORTS = json.loads("""${dp.outputPorts}""")
DQ_JOB = "${quality.dqJob}"
DL_LAYER = "${quality.dlLayer}"
REPOSITORY = "${quality.contracts.repository}"
REF = "${quality.contracts.ref}"
WATERMARK_COLUMN = "${quality.watermarkColumn}"
SODA_CLOUD_ENABLED = "${quality.sodaCloudEnabled}"
PRIMARY_KEYS = json.loads("""${quality.primaryKeys}""")
XREF_DATASETS = json.loads("""${quality.xrefDatasets}""")
PAUSED = json.loads("${env.dags.schedulePaused}")
DAG_ID = f"{DP_NAME}-quality-{ENV}"


def _args(port: dict) -> list[str]:
    args = [
        f"--domain={DOMAIN}",
        f"--dl-layer={DL_LAYER}",
        f"--contract-path={port['dataContractPath']}",
        f"--repository={REPOSITORY}",
        f"--ref={REF}",
        f"--dag-id={DAG_ID}",
        "--airflow-run-id={{ run_id }}",
        f"--soda-cloud-enabled={SODA_CLOUD_ENABLED}",
        f"--watermark-column={WATERMARK_COLUMN}",
        "--watermark-bootstrap-from={{ ds }}",
    ]
    if port["name"] in PRIMARY_KEYS:
        args.append("--primary-keys=" + ",".join(PRIMARY_KEYS[port["name"]]))
    if port["name"] in XREF_DATASETS:
        args.append("--xref-datasets=" + ",".join(XREF_DATASETS[port["name"]]))
    return args


with DAG(
    dag_id=DAG_ID,
    schedule="${quality.schedule}",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    is_paused_upon_creation=PAUSED,
    default_args={"owner": "${dp.owner}", "retries": 1, "retry_delay": timedelta(minutes=15)},
    tags=["data-quality", DP_NAME, DOMAIN],
) as dag:
    for port in OUTPUT_PORTS:
        CdeRunJobOperator(
            task_id=f"dq_{port['name']}",
            job_name=DQ_JOB,
            overrides={"spark": {"args": _args(port)}},
            pool="${quality.pool}",
        )
