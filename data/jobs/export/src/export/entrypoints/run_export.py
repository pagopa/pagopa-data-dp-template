"""Esporta tabelle del data product su Azure Blob Storage, come il dq-framework esporta le sue tabelle di risultati.

Per ogni tabella di TABLES carica un Parquet con tutto il suo contenuto, o uno per ogni valore di una colonna:

    <container>/<prefix>/<tabella>.parquet
    <container>/<prefix>/<tabella>/<colonna>=<valore>.parquet

Ogni run riscrive i blob, quindi rieseguirlo non duplica nulla e --from e --to non servono. Una tabella che fallisce
non ferma le altre, ma alla fine il job esce con errore.
"""

from __future__ import annotations

import argparse
import logging

from pyspark.sql import SparkSession

from export.blob import export_table, read_sas_token, upload_blob
from export.common.config import load_config
from export.common.logging import setup_logging

logger = logging.getLogger(__name__)

# Le tabelle da esportare, in --database: il nome e la colonna per cui dividerla in più Parquet, o None.
TABLES = (
    ("silver_demo_payments", None),
    ("silver_demo_transfers", None),
)
TARGET = ("database", "account", "container", "credential", "prefix")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", help="database delle tabelle da esportare")
    parser.add_argument("--input-database", help="database delle tabelle delle input port: l'export non lo usa")
    parser.add_argument("--from", dest="date_from", help="non usato: l'export è sempre completo")
    parser.add_argument("--to", dest="date_to", help="non usato: l'export è sempre completo")
    parser.add_argument("--account", help="storage account di Azure")
    parser.add_argument("--container", help="container dei blob")
    parser.add_argument("--credential", help="workload credential con il file sas_token")
    parser.add_argument("--prefix", help="cartella nel container: il nome del data product")
    args = parser.parse_args(argv)
    config = load_config()
    setup_logging(config.log_level)
    logger.info("Avvio in %s con %s", config.env, vars(args))
    if config.write_enabled:
        missing = [f"--{name}" for name in TARGET if not getattr(args, name)]
        if missing:
            parser.error(f"per caricare su Azure mancano {', '.join(missing)}")
        sas_token = read_sas_token(args.credential)

        def upload(blob: str, data: bytes) -> int:
            return upload_blob(args.account, args.container, blob, data, sas_token)
    else:
        logger.info("Scrittura disattivata in %s: i Parquet si preparano ma non si caricano", config.env)

        def upload(blob: str, data: bytes) -> str:
            return "non caricato"

    spark = SparkSession.builder.appName("export").getOrCreate()
    errors = 0
    for table, split_by in TABLES:
        name = f"{args.database}.{table}" if args.database else table
        try:
            df = spark.table(name)
        except Exception as error:
            errors += 1
            logger.error("%s: %s", name, error)
            continue
        errors += export_table(df, name, args.prefix or config.env, split_by, upload)
    if errors:
        raise SystemExit(f"{errors} export falliti")


if __name__ == "__main__":
    main()
