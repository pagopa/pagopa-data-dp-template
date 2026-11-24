"""Risolve i segnaposto dei file deployabili e li scrive in dist/<env>/.

Uso: python dp-setup-utils/render.py <env>, dopo `make build`. Si ferma se un file deployabile contiene ancora un TODO.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\}")
DEPLOYABLE = ("*/ddl/**/*.sql", "data/jobs/*/cde_cfg/*.yaml", "*/dags/*.py")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def envs() -> list[str]:
    return sorted(path.stem for path in (ROOT / "envs").glob("*.yaml"))


def jobs() -> list[str]:
    return sorted(path.name for path in (ROOT / "data" / "jobs").glob("*") if path.is_dir())


def deployable_files() -> list[Path]:
    return sorted({path for pattern in DEPLOYABLE for path in ROOT.glob(pattern)})


def job_of(path: Path) -> str | None:
    parts = path.resolve().relative_to(ROOT).parts
    return parts[2] if parts[:2] == ("data", "jobs") and len(parts) > 3 else None


def context(env: str) -> dict:
    ctx = {"dp": _load(ROOT / "data-product.yaml"), "env": _load(ROOT / "envs" / f"{env}.yaml")}
    quality = ROOT / "quality" / "config" / f"{env}.yaml"
    if quality.exists():
        ctx["quality"] = _load(quality)
    return ctx


def render(text: str, ctx: dict) -> str:
    def _resolve(match: re.Match) -> str:
        value = ctx
        for key in match.group(1).split("."):
            if not isinstance(value, dict) or key not in value:
                raise KeyError(f"segnaposto non risolvibile: ${{{match.group(1)}}}")
            value = value[key]
        if value is None:
            raise ValueError(f"segnaposto senza valore: ${{{match.group(1)}}}")
        if isinstance(value, list | dict):
            return json.dumps(value)
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    return PLACEHOLDER.sub(_resolve, text)


def render_file(path: Path, env: str, wheels: dict[str, str]) -> str:
    ctx = context(env)
    job = job_of(path)
    if job is not None:
        ctx["build"] = {"wheel": wheels[job]}
        ctx["job"] = {"name": job}
    return render(path.read_text(encoding="utf-8"), ctx)


def todos(rendered: dict[Path, str]) -> list[str]:
    return [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
        for path, text in rendered.items()
        for number, line in enumerate(text.splitlines(), start=1)
        if "TODO" in line
    ]


def built_wheels() -> dict[str, str]:
    wheels = {}
    for job in jobs():
        found = sorted((ROOT / "dist" / "wheels" / job).glob("*.whl"))
        if len(found) != 1:
            sys.exit(f"serve un solo wheel in dist/wheels/{job}/, trovati {len(found)}: esegui make build")
        wheels[job] = found[0].name
    return wheels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env", choices=envs())
    env = parser.parse_args().env
    wheels = built_wheels()
    rendered = {path: render_file(path, env, wheels) for path in deployable_files()}
    pending = todos(rendered)
    if pending:
        sys.exit("file deployabili con dei TODO da completare:\n" + "\n".join(f"  {line}" for line in pending))
    out = ROOT / "dist" / env
    shutil.rmtree(out, ignore_errors=True)
    for path, text in rendered.items():
        target = out / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(target.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
