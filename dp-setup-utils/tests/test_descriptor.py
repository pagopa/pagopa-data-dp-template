from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
KEYS = {
    "name",
    "domain",
    "version",
    "description",
    "owner",
    "status",
    "modules",
    "inputPorts",
    "outputPorts",
    "observabilityPorts",
}
OBSERVABILITY_KEYS = {"superset": {"name", "type", "url"}, "sodacloud": {"name", "type", "datasets"}}


def _descriptor() -> dict:
    return yaml.safe_load((ROOT / "data-product.yaml").read_text(encoding="utf-8"))


def test_solo_campi_descrittivi():
    keys = set(_descriptor())
    assert keys == KEYS, f"campi inattesi: {sorted(keys - KEYS)}, campi mancanti: {sorted(KEYS - keys)}"


def test_identita():
    dp = _descriptor()
    assert IDENTIFIER.match(dp["domain"]), f"domain finisce nei nomi delle tabelle di quality: {dp['domain']}"
    prefix = re.escape(f"dp-{dp['domain'].replace('_', '-')}-")
    assert re.fullmatch(rf"{prefix}[a-z0-9]+(-[a-z0-9]+)*", dp["name"]), f"atteso dp-<dominio>-<use-case>: {dp['name']}"
    assert SEMVER.match(str(dp["version"])), dp["version"]
    assert dp["status"] in ("draft", "active", "deprecated"), dp["status"]
    assert dp["owner"].startswith("@"), f"owner deve essere un handle GitHub: {dp['owner']}"


def test_codeowners_allineato():
    lines = (ROOT / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
    owners = {owner for line in lines if not line.lstrip().startswith("#") for owner in line.split()[1:]}
    assert _descriptor()["owner"] in owners, f"CODEOWNERS non contiene l'owner di data-product.yaml: {owners}"


def test_porte():
    dp = _descriptor()
    assert dp["outputPorts"], "il data product deve esporre almeno una output port"
    for kind in ("inputPorts", "outputPorts"):
        names = [port["name"] for port in dp[kind]]
        assert len(names) == len(set(names)), f"{kind}: nomi duplicati {names}"
        for port in dp[kind]:
            assert set(port) == {"name", "dataContractPath"}, f"{kind}: {port}"
            assert IDENTIFIER.match(port["name"]), f"{kind}: {port['name']}"
            assert port["dataContractPath"].endswith((".yaml", ".yml")), f"{kind}: {port['dataContractPath']}"
    assert isinstance(dp["observabilityPorts"], list), "observabilityPorts è una lista, anche vuota"
    names = [port["name"] for port in dp["observabilityPorts"]]
    assert len(names) == len(set(names)), f"observabilityPorts: nomi duplicati {names}"
    for port in dp["observabilityPorts"]:
        assert IDENTIFIER.match(port["name"]), f"observabilityPorts: {port['name']}"
        assert port.get("type") in OBSERVABILITY_KEYS, f"observabilityPorts: tipo superset o sodacloud, {port}"
        assert set(port) == OBSERVABILITY_KEYS[port["type"]], f"observabilityPorts: {port}"
        links = [port["url"]] if port["type"] == "superset" else [dataset["url"] for dataset in port["datasets"]]
        if port["type"] == "sodacloud":
            assert port["datasets"], f"observabilityPorts: {port['name']} senza dataset"
            assert all(set(dataset) == {"name", "url"} for dataset in port["datasets"]), port["datasets"]
            datasets = [dataset["name"] for dataset in port["datasets"]]
            assert len(datasets) == len(set(datasets)), f"observabilityPorts: dataset duplicati {datasets}"
        for link in links:
            assert link.startswith(("https://", "http://")), f"observabilityPorts: {link}"


def test_moduli_dichiarati_presenti():
    modules = _descriptor()["modules"]
    for module in ("data", "quality"):
        assert (ROOT / module).is_dir() == modules[module], f"modules.{module} non corrisponde alla cartella {module}/"
