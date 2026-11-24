from __future__ import annotations

import argparse
import logging

from pyspark.sql import SparkSession

from ingestion.common.config import load_config
from ingestion.common.logging import setup_logging

logger = logging.getLogger(__name__)

# Le input port di data-product.yaml, che hanno il nome della loro tabella.
INPUT_TABLES = (
    "raw_payments",
    "raw_transfers",
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", help="database in cui il job scrive")
    parser.add_argument("--input-database", help="database delle tabelle delle input port")
    parser.add_argument("--from", dest="date_from", help="inizio dell'intervallo da elaborare, ISO 8601")
    parser.add_argument("--to", dest="date_to", help="fine dell'intervallo da elaborare, ISO 8601")
    args = parser.parse_args(argv)
    config = load_config()
    setup_logging(config.log_level)
    logger.info("Avvio in %s con %s", config.env, vars(args))
    spark = SparkSession.builder.appName("ingestion").getOrCreate()
    if args.input_database and INPUT_TABLES:
        for table in INPUT_TABLES:
            spark.table(f"{args.input_database}.{table}").show(truncate=False)
    else:
        spark.sql("SHOW DATABASES").show(truncate=False)
    # TODO: al posto dell'esempio, leggere i dati dell'intervallo da args.input_database e trasformarli.
    if not config.write_enabled:
        logger.info("Scrittura disattivata in %s: nessuna tabella modificata", config.env)
        return
    # TODO: scrivere in args.database, in modo che rieseguire lo stesso intervallo non duplichi i dati.


if __name__ == "__main__":
    main()
