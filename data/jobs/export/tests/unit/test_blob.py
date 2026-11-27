from __future__ import annotations

import datetime as dt
import io
import urllib.error
from decimal import Decimal
from types import SimpleNamespace

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
blob = pytest.importorskip("export.blob")


class _Type:
    def __init__(self, name: str) -> None:
        self.name = name

    def simpleString(self) -> str:
        return self.name


class _Row(dict):
    def asDict(self) -> dict:
        return dict(self)


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name

    def eqNullSafe(self, value):
        return self.name, value


class _DataFrame:
    """Quel poco di DataFrame che lo script usa, senza avviare Spark."""

    def __init__(self, columns: dict[str, str], rows: list[dict]) -> None:
        self.columns, self.rows = columns, rows
        fields = [SimpleNamespace(name=name, dataType=_Type(kind)) for name, kind in columns.items()]
        self.schema = SimpleNamespace(fields=fields)

    def collect(self) -> list[_Row]:
        return [_Row(row) for row in self.rows]

    def select(self, column: str) -> _DataFrame:
        return _DataFrame({column: self.columns[column]}, [{column: row[column]} for row in self.rows])

    def distinct(self) -> _DataFrame:
        unique = {tuple(row.items()) for row in self.rows}
        return _DataFrame(self.columns, [dict(items) for items in unique])

    def __getitem__(self, column: str) -> _Column:
        return _Column(column)

    def where(self, condition: tuple) -> _DataFrame:
        column, value = condition
        return _DataFrame(self.columns, [row for row in self.rows if row[column] == value])


COLUMNS = {"id": "bigint", "dataset": "string", "amount": "decimal(12,2)", "day": "date", "ts": "timestamp"}
ROWS = [
    {"id": 1, "dataset": "a", "amount": Decimal("1.50"), "day": dt.date(2026, 1, 1), "ts": dt.datetime(2026, 1, 1, 8)},
    {"id": 2, "dataset": "b", "amount": Decimal("2.00"), "day": dt.date(2026, 1, 2), "ts": dt.datetime(2026, 1, 2, 9)},
    {"id": 3, "dataset": None, "amount": None, "day": None, "ts": None},
]


def test_tipi():
    assert blob.arrow_type("decimal(12,2)") == pa.decimal128(12, 2)
    assert blob.arrow_type("timestamp") == pa.timestamp("us")
    with pytest.raises(TypeError, match="array<string>"):
        blob.arrow_type("array<string>")


def test_parquet_con_lo_schema_della_tabella():
    rows, data = blob.to_parquet(_DataFrame(COLUMNS, ROWS))
    table = pq.read_table(io.BytesIO(data))
    assert rows == table.num_rows == 3
    assert table.schema.field("amount").type == pa.decimal128(12, 2)
    assert table.column("amount").to_pylist() == [Decimal("1.50"), Decimal("2.00"), None]
    with pytest.raises(TypeError, match="colonna tags"):
        blob.to_parquet(_DataFrame({"tags": "array<string>"}, []))


def test_path_dei_blob():
    assert blob.blob_name("dp-x", "pagopa.payments") == "dp-x/payments.parquet"
    assert blob.blob_name("dp-x", "payments", "dataset", "a b/c") == "dp-x/payments/dataset=a%20b%2Fc.parquet"
    null = blob.blob_name("dp-x", "payments", "dataset", None)
    assert null == "dp-x/payments/dataset=__HIVE_DEFAULT_PARTITION__.parquet"


def _uploads():
    uploaded: dict[str, bytes] = {}

    def upload(blob: str, data: bytes) -> int:
        uploaded[blob] = data
        return 201

    return uploaded, upload


def test_tutta_la_tabella_in_un_blob():
    uploaded, upload = _uploads()
    assert blob.export_table(_DataFrame(COLUMNS, ROWS), "db.payments", "dp-x", None, upload) == 0
    assert list(uploaded) == ["dp-x/payments.parquet"]
    assert pq.read_table(io.BytesIO(uploaded["dp-x/payments.parquet"])).num_rows == 3


def test_un_blob_per_valore():
    uploaded, upload = _uploads()
    assert blob.export_table(_DataFrame(COLUMNS, ROWS), "db.payments", "dp-x", "dataset", upload) == 0
    assert list(uploaded) == [
        "dp-x/payments/dataset=a.parquet",
        "dp-x/payments/dataset=b.parquet",
        "dp-x/payments/dataset=__HIVE_DEFAULT_PARTITION__.parquet",
    ]
    assert all(pq.read_table(io.BytesIO(data)).num_rows == 1 for data in uploaded.values())


def test_gli_errori_si_contano_senza_fermarsi():
    def upload(blob: str, data: bytes) -> int:
        raise urllib.error.HTTPError(blob, 403, "Forbidden", {}, io.BytesIO(b"AuthorizationFailure"))

    assert blob.export_table(_DataFrame(COLUMNS, ROWS), "db.payments", "dp-x", "dataset", upload) == 3


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args) -> None:
        return None


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("url", code, "", {}, io.BytesIO(b""))


def test_upload_riprova_solo_gli_errori_temporanei(monkeypatch):
    requests, replies = [], []

    def urlopen(request, timeout):
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply)

    monkeypatch.setattr(blob.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(blob.time, "sleep", lambda seconds: None)
    replies[:] = [_http_error(503), _http_error(429), 201]
    assert blob.upload_blob("acc", "cont", "dp-x/t.parquet", b"data", "?sv=1&sig=x") == 201
    assert len(requests) == 3
    assert requests[-1].full_url == "https://acc.blob.core.windows.net/cont/dp-x/t.parquet?sv=1&sig=x"
    assert requests[-1].get_method() == "PUT" and requests[-1].headers["X-ms-blob-type"] == "BlockBlob"
    replies[:] = [_http_error(403)]
    with pytest.raises(urllib.error.HTTPError):
        blob.upload_blob("acc", "cont", "dp-x/t.parquet", b"data", "sv=1")
    assert not replies, "un 403 non si riprova"
    replies[:] = [_http_error(503)] * 3
    with pytest.raises(urllib.error.HTTPError):
        blob.upload_blob("acc", "cont", "dp-x/t.parquet", b"data", "sv=1")
    assert not replies, "tre tentativi, poi l'errore"


def test_sas_token_dalla_workload_credential(tmp_path):
    (tmp_path / "dp-blob-sas").mkdir()
    (tmp_path / "dp-blob-sas" / "sas_token").write_text("?sv=1&sig=x\n", encoding="utf-8")
    assert blob.read_sas_token("dp-blob-sas", tmp_path) == "?sv=1&sig=x"
    with pytest.raises(SystemExit, match="monta la workload credential altra"):
        blob.read_sas_token("altra", tmp_path)
