"""Aggiunge una porta al data product: nel descrittore e, per una output port con il Modulo Dati, la DDL scheletro.

Uso: python dp-setup-utils/new_port.py <nome> [--contract <path>] [--input]
     python dp-setup-utils/new_port.py [<nome>] --observability [--type superset --url <url>]
     python dp-setup-utils/new_port.py [<nome>] --observability [--type sodacloud --datasets <dataset>=<url>,...]
Un'observability port è dove si monitora il data product: una dashboard Superset o i dataset su Soda Cloud.
Chiede tipo, URL e dataset che non riceve.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import setup
import yaml

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = re.compile(r"^V(\d+)__")
OBSERVABILITY_TYPES = ("superset", "sodacloud")
DATASET = re.compile(r"^[A-Za-z_][\w.]*$")


def url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc or any(char.isspace() for char in raw):
        raise ValueError(f"{raw or 'URL vuoto'}: l'URL comincia con https://")
    return raw


def observability_type(raw: str) -> str:
    if raw not in OBSERVABILITY_TYPES:
        raise ValueError(f"{raw or 'tipo vuoto'}: il tipo è {' o '.join(OBSERVABILITY_TYPES)}")
    return raw


def _dataset(raw: str, taken: list[tuple[str, str]]) -> str:
    if not DATASET.match(raw):
        raise ValueError(f"{raw or 'nome vuoto'}: il dataset è il nome della tabella su Soda Cloud")
    if raw in {name for name, _ in taken}:
        raise ValueError(f"{raw}: dataset ripetuto")
    return raw


def _datasets(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name, address in pairs:
        found.append((_dataset(name, found), url(address)))
    if not found:
        raise ValueError("serve almeno un dataset, come DATASETS=<dataset>=<url>,...")
    return found


def datasets(raw: str) -> list[tuple[str, str]]:
    items = [item.partition("=") for item in filter(None, (part.strip() for part in raw.split(",")))]
    return _datasets([(name.strip(), address.strip()) for name, _, address in items])


def _check_name(name: str, ports: list[dict], label: str) -> None:
    if not setup.IDENTIFIER.match(name):
        raise ValueError(f"{name or 'nome vuoto'}: il nome della porta è un identificatore SQL, con PORT=<nome>")
    if name in {port["name"] for port in ports}:
        raise ValueError(f"{name}: in data-product.yaml c'è già una {label} con questo nome")


def new_observability_port(
    name: str, kind: str, root: Path, address: str | None = None, sets: list[tuple[str, str]] | None = None
) -> list[tuple[str, str, str]]:
    descriptor = root / "data-product.yaml"
    dp = yaml.safe_load(descriptor.read_text(encoding="utf-8"))
    name = name or observability_type(kind)
    _check_name(name, dp["observabilityPorts"], "observability port")
    if observability_type(kind) == "superset":
        port, detail = {"name": name, "type": kind, "url": url(address or "")}, f"con la dashboard {address}"
    else:
        sets = _datasets(sets or [])
        port = {"name": name, "type": kind, "datasets": [{"name": dataset, "url": link} for dataset, link in sets]}
        detail = f"con i dataset {', '.join(dataset for dataset, _ in sets)}"
    dp["observabilityPorts"].append(port)
    descriptor.write_text(setup.descriptor_text(dp), encoding="utf-8", newline="\n")
    label = name if name == kind else f"{name} ({kind})"
    return [("modificato", "data-product.yaml", f"observability port {label}, {detail}")]


def _ask_datasets(outputs: list[str]) -> list[tuple[str, str]]:
    print(f"Dataset su Soda Cloud, uno alla volta, invio a vuoto per finire (output port: {', '.join(outputs)})")
    found: list[tuple[str, str]] = []
    while True:
        name = setup._ask("Dataset", "", lambda raw: raw if not raw and found else _dataset(raw, found))
        if not name:
            return found
        found.append((name, setup._ask(f"URL di {name} su Soda Cloud", "", url)))


def _observability(args: argparse.Namespace) -> None:
    kind = args.type or setup._ask("Tipo (superset o sodacloud)", "superset", observability_type)
    address = sets = None
    if observability_type(kind) == "superset":
        address = args.url if args.url is not None else setup._ask("URL della dashboard", "", url)
    elif args.datasets is not None:
        sets = datasets(args.datasets)
    else:
        dp = yaml.safe_load((ROOT / "data-product.yaml").read_text(encoding="utf-8"))
        sets = _ask_datasets([port["name"] for port in dp["outputPorts"]])
    changes = new_observability_port(args.name, kind, ROOT, address, sets)
    print(setup.report(changes, f"Aggiunta l'observability port {args.name or kind}:"))


def new_port(
    name: str, root: Path, contract: str | None = None, input_port: bool = False
) -> list[tuple[str, str, str]]:
    if contract is not None and not setup.CONTRACT.match(contract):
        raise ValueError(f"{contract}: il path del contratto è un file .yaml del repo dei contratti")
    descriptor = root / "data-product.yaml"
    dp = yaml.safe_load(descriptor.read_text(encoding="utf-8"))
    kind, label = ("inputPorts", "input port") if input_port else ("outputPorts", "output port")
    _check_name(name, dp[kind], label)
    contract = contract or setup.default_contract(dp["domain"], name)
    dp[kind].append({"name": name, "dataContractPath": contract})
    descriptor.write_text(setup.descriptor_text(dp), encoding="utf-8", newline="\n")
    changes = [("modificato", "data-product.yaml", f"{label} {name}, con il contratto {contract}")]
    if not input_port and (root / "data").is_dir():
        tables = root / "data" / "ddl" / "tables"
        tables.mkdir(parents=True, exist_ok=True)
        numbers = [int(match.group(1)) for path in tables.glob("*.sql") if (match := MIGRATION.match(path.name))]
        migration = f"V{max(numbers, default=0) + 1:03d}__create_{name}.sql"
        (tables / migration).write_text(setup.ddl(name), encoding="utf-8", newline="\n")
        changes.append(("creato", f"data/ddl/tables/{migration}", f"scheletro della tabella della output port {name}"))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="nome della porta, un identificatore SQL; per --observability di default il tipo")
    parser.add_argument("--contract", help="path del contratto, di default quello della convenzione")
    parser.add_argument("--input", action="store_true", help="una tabella da leggere, con il suo nome come PORT")
    parser.add_argument("--observability", action="store_true", help="dove si monitora il data product")
    parser.add_argument("--type", help="per --observability: superset o sodacloud, se manca lo chiede")
    parser.add_argument("--url", help="per superset: URL della dashboard, se manca lo chiede")
    parser.add_argument("--datasets", help="per sodacloud: <dataset>=<url>,..., se manca li chiede")
    args = parser.parse_args()
    if args.observability:
        try:
            _observability(args)
        except ValueError as error:
            sys.exit(str(error))
        return
    try:
        changes = new_port(args.name, ROOT, args.contract, args.input)
    except ValueError as error:
        sys.exit(str(error))
    print(setup.report(changes, f"Aggiunta la {'input' if args.input else 'output'} port {args.name}:"))
    if args.input:
        todo = ["la lettura nel job che la usa, dal database di --input-database"]
    elif (ROOT / "data").is_dir():
        todo = ["nome e colonne della tabella nella DDL, come nel contratto", "la scrittura nel job che la alimenta"]
    else:
        todo = ["niente nei job: la quality la misura dal prossimo deploy"]
    if not args.input and (ROOT / "quality").is_dir():
        todo.append("se servono, primaryKeys e xrefDatasets in quality/config/<env>.yaml")
    print("Ora:\n" + "\n".join(f"  - {item}" for item in todo))


if __name__ == "__main__":
    main()
