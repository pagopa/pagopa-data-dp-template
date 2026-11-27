"""Parquet e upload su Azure Blob Storage con un SAS token, come l'export del dq-framework."""

from __future__ import annotations

import io
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

SECRETS = Path("/etc/dex/secrets")
NULL_VALUE = "__HIVE_DEFAULT_PARTITION__"
DECIMAL = re.compile(r"^decimal\((\d+),(\d+)\)$")
SPARK_TO_ARROW = {
    "string": pa.string(),
    "tinyint": pa.int8(),
    "smallint": pa.int16(),
    "int": pa.int32(),
    "bigint": pa.int64(),
    "float": pa.float32(),
    "double": pa.float64(),
    "boolean": pa.bool_(),
    "binary": pa.binary(),
    "date": pa.date32(),
    "timestamp": pa.timestamp("us"),
    "timestamp_ntz": pa.timestamp("us"),
}
BLOB_API_VERSION = "2018-11-09"
RETRY_WAITS_SECONDS = (5, 15)

Upload = Callable[[str, bytes], int]


def arrow_type(spark_type: str) -> pa.DataType:
    if spark_type in SPARK_TO_ARROW:
        return SPARK_TO_ARROW[spark_type]
    if match := DECIMAL.match(spark_type):
        return pa.decimal128(int(match[1]), int(match[2]))
    raise TypeError(f"tipo Spark non supportato: {spark_type}")


def read_sas_token(credential: str, secrets: Path = SECRETS) -> str:
    secret_file = secrets / credential / "sas_token"
    if not secret_file.exists():
        sys.exit(f"SAS token non trovato in {secret_file}: monta la workload credential {credential} sul job")
    return secret_file.read_text(encoding="utf-8").strip()


def to_parquet(df) -> tuple[int, bytes]:
    fields = []
    for field in df.schema.fields:
        try:
            fields.append((field.name, arrow_type(field.dataType.simpleString())))
        except TypeError as error:
            raise TypeError(f"colonna {field.name}: {error}") from None
    table = pa.Table.from_pylist([row.asDict() for row in df.collect()], schema=pa.schema(fields))
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    return table.num_rows, buffer.getvalue()


def blob_name(prefix: str, table: str, split_by: str | None = None, value: object = None) -> str:
    name = table.rsplit(".", 1)[-1]
    if split_by is None:
        return f"{prefix}/{name}.parquet"
    part = NULL_VALUE if value is None else urllib.parse.quote(str(value), safe="")
    return f"{prefix}/{name}/{split_by}={part}.parquet"


def upload_blob(account: str, container: str, blob: str, data: bytes, sas_token: str) -> int:
    url = f"https://{account}.blob.core.windows.net/{container}/{blob}?{sas_token.lstrip('?')}"
    headers = {
        "x-ms-version": BLOB_API_VERSION,
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": "application/octet-stream",
    }
    request = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    for wait in (*RETRY_WAITS_SECONDS, None):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status
        except urllib.error.HTTPError as error:
            if wait is None or not (error.code >= 500 or error.code == 429):
                raise
        except (urllib.error.URLError, TimeoutError):
            if wait is None:
                raise
        time.sleep(wait)
    raise AssertionError("non raggiungibile: l'ultimo tentativo restituisce o rilancia")


def export_table(df, table: str, prefix: str, split_by: str | None, upload: Upload) -> int:
    """Carica la tabella, o un Parquet per valore di split_by, e restituisce quanti upload sono falliti."""
    logger.info("%s: %s", table, [(field.name, field.dataType.simpleString()) for field in df.schema.fields])
    if split_by is None:
        parts = [(blob_name(prefix, table), df)]
    else:
        values = sorted((row[split_by] for row in df.select(split_by).distinct().collect()), key=_null_last)
        parts = [
            (blob_name(prefix, table, split_by, value), df.where(df[split_by].eqNullSafe(value))) for value in values
        ]
    errors = 0
    for blob, part in parts:
        try:
            rows, data = to_parquet(part)
            status = upload(blob, data)
            logger.info("%s: %d righe, %d B -> %s (HTTP %s)", table, rows, len(data), blob, status)
        except urllib.error.HTTPError as error:
            errors += 1
            detail = error.read().decode(errors="replace")[:300]
            logger.error("%s -> %s: HTTP %s %s", table, blob, error.code, detail)
        except Exception as error:
            errors += 1
            logger.error("%s -> %s: %s", table, blob, error)
    return errors


def _null_last(value: object) -> tuple[bool, str]:
    return value is None, str(value)
