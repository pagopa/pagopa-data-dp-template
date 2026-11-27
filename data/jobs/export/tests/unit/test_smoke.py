import logging
from types import SimpleNamespace

import pytest

pytest.importorskip("pyarrow")
from export.entrypoints import run_export  # noqa: E402

ARGS = ["--database", "pagopa", "--account", "acc", "--container", "cont", "--credential", "sas", "--prefix", "dp-x"]


class _Row(dict):
    def asDict(self):
        return dict(self)

    def __missing__(self, column):
        return "x"


class FakeTable:
    """Una riga e una colonna: basta per il percorso dell'export, anche con una colonna per cui dividere."""

    bigint = SimpleNamespace(simpleString=lambda: "bigint")
    schema = SimpleNamespace(fields=[SimpleNamespace(name="id", dataType=bigint)])

    def collect(self):
        return [_Row(id=1)]

    def select(self, column):
        return self

    def distinct(self):
        return self

    def where(self, condition):
        return self

    def __getitem__(self, column):
        return SimpleNamespace(eqNullSafe=lambda value: None)


class FakeSpark:
    """Al posto della SparkSession: i test non avviano Spark, che vuole Java."""

    def __init__(self):
        self.read, self.missing = [], set()

    def table(self, name):
        self.read.append(name)
        if name in self.missing:
            raise ValueError(f"Table or view not found: {name}")
        return FakeTable()


@pytest.fixture
def spark(monkeypatch):
    fake = FakeSpark()
    builder = SimpleNamespace(appName=lambda name: builder, getOrCreate=lambda: fake)
    monkeypatch.setattr(run_export, "SparkSession", SimpleNamespace(builder=builder))
    return fake


@pytest.fixture
def uploads(monkeypatch):
    uploaded = []

    def upload_blob(account, container, blob, data, sas_token):
        uploaded.append((account, container, blob, sas_token))
        return 201

    monkeypatch.setattr(run_export, "read_sas_token", lambda credential: f"token di {credential}")
    monkeypatch.setattr(run_export, "upload_blob", upload_blob)
    return uploaded


def _exported(uploads):
    return {blob.split("/")[1].removesuffix(".parquet") for _, _, blob, _ in uploads}


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_main(monkeypatch, caplog, spark, uploads, env):
    monkeypatch.setenv("ENV", env)
    with caplog.at_level(logging.INFO):
        run_export.main(ARGS)
    assert spark.read == [f"pagopa.{table}" for table, _ in run_export.TABLES]
    assert ("Scrittura disattivata" in caplog.text) == (env == "dev")
    if env == "dev":
        assert uploads == [], "in dev i Parquet non si caricano"
    else:
        assert _exported(uploads) == {table for table, _ in run_export.TABLES}
        assert all(upload[:2] == ("acc", "cont") and upload[3] == "token di sas" for upload in uploads)


def test_senza_destinazione_non_carica(monkeypatch, spark, uploads):
    monkeypatch.setenv("ENV", "test")
    with pytest.raises(SystemExit):
        run_export.main(["--database", "pagopa"])
    assert spark.read == [] and uploads == []


def test_una_tabella_che_fallisce_non_ferma_le_altre(monkeypatch, spark, uploads):
    monkeypatch.setenv("ENV", "test")
    first, *others = [table for table, _ in run_export.TABLES]
    spark.missing.add(f"pagopa.{first}")
    with pytest.raises(SystemExit, match="1 export falliti"):
        run_export.main(ARGS)
    assert _exported(uploads) == set(others)
