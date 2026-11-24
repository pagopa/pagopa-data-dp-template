import logging
from types import SimpleNamespace

import pytest
from deduplication.entrypoints import run_deduplication


class FakeSpark:
    """Al posto della SparkSession: i test non avviano Spark, che vuole Java."""

    def __init__(self):
        self.read = []

    def table(self, name):
        self.read.append(name)
        return self

    def sql(self, query):
        self.read.append(query)
        return self

    def show(self, **kwargs):
        pass


@pytest.fixture
def spark(monkeypatch):
    fake = FakeSpark()
    builder = SimpleNamespace(appName=lambda name: builder, getOrCreate=lambda: fake)
    monkeypatch.setattr(run_deduplication, "SparkSession", SimpleNamespace(builder=builder))
    return fake


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_main(monkeypatch, caplog, spark, env):
    monkeypatch.setenv("ENV", env)
    with caplog.at_level(logging.INFO):
        run_deduplication.main([])
    assert spark.read == ["SHOW DATABASES"]
    assert ("Scrittura disattivata" in caplog.text) == (env == "dev")


def test_legge_le_input_port(spark):
    run_deduplication.main(["--input-database", "pagopa"])
    tables = [f"pagopa.{table}" for table in run_deduplication.INPUT_TABLES]
    assert spark.read == (tables or ["SHOW DATABASES"])
