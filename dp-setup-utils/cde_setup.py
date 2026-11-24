"""Guida all'accesso a CDE per il deploy da locale: tre passi, poi le verifiche.

Uso: python dp-setup-utils/cde_setup.py [<env>], con `make cde-setup`, che carica il .env. Per ogni passo dice cosa
fare nelle UI di CDE e di CDP, anche se è già fatto; per quelli che mancano aspetta la risposta e la salva subito nel
.env. Poi si collega al vcluster e controlla i prerequisiti su CDE di ogni ambiente, o solo di <env>.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import apply
import render
import yaml

ROOT = render.ROOT
ENV_FILE = ROOT / ".env"
CLI = Path("/usr/local/bin/cde")
CREDENTIALS = (
    ROOT / "credentials",
    Path.home() / ".cde" / "credentials",
    Path("/etc/cde/credentials"),
    Path.home() / ".cdp" / "credentials",
)
ACCESS_KEY = ("CDE_ACCESS_KEY_ID", "CDE_ACCESS_KEY_SECRET")
ENDPOINT = re.compile(r"^https://[\w.-]+(:\d+)?/dex/api/v1$")
VALUE = re.compile(r"^[^\s$#\\'\"<>]+$")
OK, MISSING, CHECK = "ok", "manca", "da verificare"
INDENT = " " * 6

INTRO = (
    "Accesso a CDE per deployare da qui: tre passi, poi le verifiche. Tieni aperte la UI di CDE e la console di CDP.",
    "Ctrl+C per interrompere: ciò che inserisci è salvato subito nel .env, e rilanciando si riparte da lì.",
)
CLUSTER_DETAILS = (
    "Apri la UI di CDE e, nel menu a sinistra, Administration (nelle versioni meno recenti è la pagina Overview).",
    "Nella colonna Services scegli il servizio di CDE.",
    "Nella colonna Virtual Clusters, sul virtual cluster su cui deployi, clicca l'icona Cluster Details.",
)
CLI_STEPS = (
    *CLUSTER_DETAILS,
    "Sotto CLI TOOL scarica la versione Linux, anche se usi Windows o Mac: la CLI gira nel Dev Container.",
    "Trascina il file scaricato, cde, nella cartella del repo in VS Code.",
)
ENDPOINT_STEPS = (
    *CLUSTER_DETAILS,
    "Clicca JOBS API URL: l'indirizzo viene copiato. È lo stesso per test e prod.",
)
ACCESS_KEY_STEPS = (
    "Apri la console di CDP.",
    "Clicca il tuo nome in basso a sinistra, poi Profile.",
    "Clicca Generate Access Key, e conferma se te lo chiede.",
    "Lascia aperta la finestra: la Private Key si vede solo adesso.",
)
CONNECTION_CHECKS = (
    "il Jobs API URL sia quello del virtual cluster su cui deployi;",
    "l'access key sia copiata per intero e non sia stata cancellata dal tuo profilo;",
    "tu abbia i ruoli DEUser ed EnvironmentUser sull'environment di CDE: li assegna l'amministratore di CDP;",
    "la tua rete raggiunga il vcluster.",
)
ONCE_PER_ENV = "si crea su CDE, una volta per ambiente: vedi i prerequisiti nella sezione Deploy del README"
RETRY = "\nNon ho finito: rilancia make cde-setup per continuare da dove eri."


def _print(*lines: str) -> None:
    for line in lines:
        print(f"{INDENT}{line}")


def _steps(lines: tuple[str, ...]) -> None:
    _print(*(f"{number}. {line}" for number, line in enumerate(lines, start=1)))


def _title(number: int, title: str, state: str) -> None:
    print(f"\n[{number}/3] {title}: {state}")


def _done(number: int, title: str, state: str, steps: tuple[str, ...]) -> None:
    _title(number, title, f"già fatto, {state}")
    _steps(steps)


def _input(question: str, secret: bool = False) -> str | None:
    try:
        return (getpass.getpass if secret else input)(f"{INDENT}{question}: ").strip()
    except EOFError:
        print()
        return None


def _ask(question: str, parse: Callable[[str], str], secret: bool = False, keep: str = "") -> str | None:
    if keep:
        question += " (invio per tenere il valore attuale)"
    while (raw := _input(question, secret)) is not None:
        if keep and not raw:
            return keep
        try:
            return parse(raw)
        except ValueError as error:
            _print(str(error))
    return None


def _yes(question: str) -> bool:
    return (_input(f"{question} [s/N]") or "").lower() in ("s", "si", "sì")


def _endpoint(raw: str) -> str:
    if not ENDPOINT.match(raw):
        raise ValueError(f"{raw or 'vuoto'}: il Jobs API URL comincia con https:// e finisce con /dex/api/v1")
    return raw


def _url(raw: str) -> str:
    if not raw.startswith(("https://", "http://")) or not VALUE.match(raw):
        raise ValueError(f"{raw}: non è un URL http o https")
    return raw


def _key(raw: str) -> str:
    if not VALUE.match(raw):
        raise ValueError("vuota o incompleta: copiala di nuovo, per intero")
    return raw


def _valid(parse: Callable[[str], str], raw: str) -> bool:
    try:
        parse(raw)
    except ValueError:
        return False
    return True


def save(values: dict[str, str]) -> None:
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    else:
        example = ROOT / ".env.example"
        lines = example.read_text(encoding="utf-8").splitlines() if example.exists() else []
    for key, value in values.items():
        found = [index for index, line in enumerate(lines) if re.match(rf"[#\s]*{key}\s*=", line)]
        for index in found:
            lines[index] = f"{key}={value}"
        if not found:
            lines.append(f"{key}={value}")
        os.environ[key] = value
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with contextlib.suppress(OSError):
        ENV_FILE.chmod(0o600)


def _cde(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["cde", *args], cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except OSError as error:
        return subprocess.CompletedProcess(["cde", *args], 1, "", str(error))


def _tail(result: subprocess.CompletedProcess) -> list[str]:
    lines = [line.strip() for line in f"{result.stdout or ''}\n{result.stderr or ''}".splitlines() if line.strip()]
    return lines[-5:]


def _version() -> str | None:
    result = _cde("--version")
    return (result.stdout or result.stderr).strip() if result.returncode == 0 else None


def _download(url: str) -> None:
    result = subprocess.run(["curl", "-fsSL", "--max-time", "120", "-o", str(CLI), url], capture_output=True, text=True)
    if result.returncode != 0:
        CLI.unlink(missing_ok=True)
        raise OSError(result.stderr.strip() or f"curl è uscito con il codice {result.returncode}")


def _install(put: Callable[[], object]) -> bool:
    try:
        put()
        CLI.chmod(0o755)
    except OSError as error:
        _print(f"Non riesco a installarla in {CLI}: {error}")
        return False
    return True


def _wait_for_cli(dropped: Path) -> str | None:
    """Aspetta il file della CLI nella cartella del repo, o il suo URL: '' per il file, None se l'input finisce."""
    while not dropped.is_file():
        answer = _input("Premi invio quando il file cde è nella cartella del repo")
        if answer is None:
            return None
        if _valid(_url, answer):
            save({"CDE_CLI_DOWNLOAD_URL": answer})
            return answer
        if answer:
            _print(f"{answer}: non è un URL http o https.")
        elif not dropped.is_file():
            _print(f"Non trovo il file cde in {ROOT}: trascinalo lì, poi premi invio.")
    return ""


def cli() -> bool:
    dropped = ROOT / "cde"
    version = None if dropped.is_file() else _version()
    if version:
        _done(1, "CLI cde", version, CLI_STEPS)
        return True
    _title(1, "CLI cde", "da installare")
    url = os.environ.get("CDE_CLI_DOWNLOAD_URL", "")
    if not dropped.is_file() and not _valid(_url, url):
        if shutil.which("cde"):
            _print("Quella installata non parte: va sostituita con la versione Linux del vcluster.")
        _steps(CLI_STEPS)
        _print("Se hai l'URL della CLI (CDE_CLI_DOWNLOAD_URL della CD), puoi incollarlo qui al posto del file.")
        url = _wait_for_cli(dropped)
        if url is None:
            return False
    if not _install((lambda: shutil.move(dropped, CLI)) if dropped.is_file() else (lambda: _download(url))):
        _print("Trascina il file cde nella cartella del repo e rilancia make cde-setup.")
        return False
    version = _version()
    if not version:
        _print("La CLI non parte: serve la versione Linux, presa dal vcluster su cui deployi.")
        return False
    _print(f"-> installata: {version}")
    return True


def endpoint(force: bool = False) -> bool:
    current = os.environ.get("CDE_VCLUSTER_ENDPOINT", "")
    valid = _valid(_endpoint, current)
    if valid and not force:
        _done(2, "Endpoint del vcluster", current, ENDPOINT_STEPS)
        return True
    _title(2, "Endpoint del vcluster", "da ricontrollare" if valid else "da configurare")
    _steps(ENDPOINT_STEPS)
    value = _ask("Incolla il Jobs API URL", _endpoint, keep=current if valid else "")
    if value is None:
        return False
    if value != current:
        save({"CDE_VCLUSTER_ENDPOINT": value})
        _print("-> salvato nel .env")
    return True


def _credentials_file() -> Path | None:
    custom = os.environ.get("CDE_CREDENTIALS_FILE")
    return next((path for path in ((Path(custom),) if custom else CREDENTIALS) if path.is_file()), None)


def _key_in_env() -> bool:
    return all(_valid(_key, os.environ.get(name, "")) for name in ACCESS_KEY)


def configured() -> bool:
    """I tre passi fatti, senza collegarsi al vcluster: per make help, che carica il .env."""
    installed = shutil.which("cde") is not None and not (ROOT / "cde").is_file()
    has_endpoint = _valid(_endpoint, os.environ.get("CDE_VCLUSTER_ENDPOINT", ""))
    return installed and has_endpoint and (_key_in_env() or _credentials_file() is not None)


def access_key(force: bool = False) -> bool:
    in_env = _key_in_env()
    file = None if in_env else _credentials_file()
    if (in_env or file) and not force:
        _done(3, "Access key", "nel .env" if in_env else f"in {file}", ACCESS_KEY_STEPS)
        return True
    _title(3, "Access key", "da ricontrollare" if in_env or file else "da creare")
    _steps(ACCESS_KEY_STEPS)
    _print("Se Generate Access Key non c'è, chiedi una chiave all'amministratore di CDP.")
    kept = [os.environ[name] if in_env else "" for name in ACCESS_KEY]
    key_id = _ask("Incolla l'Access Key ID", _key, keep=kept[0])
    question = "Incolla la Private Key, che non si vede mentre la incolli"
    secret = _ask(question, _key, secret=True, keep=kept[1]) if key_id else None
    if not secret:
        return False
    if [key_id, secret] != kept:
        save(dict(zip(ACCESS_KEY, (key_id, secret))))
        _print("-> salvata nel .env, che git ignora")
    return True


def connection() -> bool:
    result = _cde("job", "list")
    if result.returncode == 0:
        print("\nVerifica del collegamento al vcluster: ok")
        return True
    print("\nVerifica del collegamento al vcluster: non risponde")
    _print("Errore della CLI:", *(f"  {line}" for line in _tail(result)), "Controlla che:")
    _steps(CONNECTION_CHECKS)
    return False


def prerequisites(env: str) -> list[tuple[str, ...]]:
    ctx = render.context(env)
    credentials = ctx["env"]["credentials"]
    wanted = [("credential", name, f"workload credential {name}", ONCE_PER_ENV) for name in credentials]
    wheels = {job: f"{job}.whl" for job in render.jobs()}
    for path in render.deployable_files():
        if path.parent.name == "cde_cfg":
            resource = yaml.safe_load(render.render_file(path, env, wheels)).get("pythonEnvResource")
            if resource:
                wanted.append(("resource", resource, f"resource python-env {resource}", ONCE_PER_ENV))
    if "quality" in ctx:
        job = ctx["quality"]["dqJob"]
        hint = "lo deploya il dq-framework: senza, la quality fallisce"
        wanted.append(("job", job, f"job del dq-framework {job}", hint))
    checks = [
        (OK, label) if _cde(kind, "describe", "--name", name).returncode == 0 else (MISSING, label, hint)
        for kind, name, label, hint in wanted
    ]
    for job in render.jobs():
        if apply.requirements(job):
            checks.append((OK, f"python-env del job {job}", "la crea il deploy da requirements.txt"))
    if "quality" in ctx and ctx["quality"]["pool"] != "default_pool":
        hint = "in Airflow, Admin e Pools; se non si può creare, default_pool in quality/config/<env>.yaml"
        checks.append((CHECK, f"pool Airflow {ctx['quality']['pool']} con uno slot", hint))
    return checks or [(OK, "niente da controllare")]


def _print_checks(checks: list[tuple[str, ...]]) -> None:
    for label, *hints in checks:
        print(f"    {label}")
        for hint in hints:
            print(f"      {hint}")


def report(envs: list[str]) -> list[str]:
    """OK per ogni ambiente a cui non manca nulla, i dettagli solo di ciò che manca; i controlli a mano una volta."""
    print("\nPrerequisiti su CDE:")
    missing, manual = [], {}
    for env in envs:
        checks = prerequisites(env)
        absent = [check[1:] for check in checks if check[0] == MISSING]
        manual.update(dict.fromkeys(check[1:] for check in checks if check[0] == CHECK))
        print(f"  {env}: manca qualcosa, da creare una volta per ambiente" if absent else f"  OK {env}")
        _print_checks(absent)
        if absent:
            missing.append(env)
    if manual:
        print("  Da verificare a mano, perché la CLI non lo vede:")
        _print_checks(list(manual))
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("env", nargs="?", choices=render.envs(), help="l'ambiente da controllare, di default tutti")
    args = parser.parse_args()
    print(*INTRO, sep="\n")
    try:
        if not all([cli(), endpoint(), access_key()]):
            sys.exit(RETRY)
        while not connection():
            if not _yes("Vuoi reinserire endpoint e access key?"):
                sys.exit(RETRY)
            endpoint(force=True)
            access_key(force=True)
    except KeyboardInterrupt:
        sys.exit(f"\n{RETRY}")
    envs = [args.env] if args.env else sorted(render.envs(), key=lambda env: (env != "test", env))
    missing = " e ".join(report(envs))
    if missing:
        sys.exit(f"\nPer {missing} su CDE manca qualcosa: chiedilo a chi gestisce il vcluster, poi rilancia.")


if __name__ == "__main__":
    main()
