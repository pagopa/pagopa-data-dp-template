# Data product dp-demo-blueprint

TODO: descrizione del data product in una riga.

## Partire da questa blueprint

Questo repo è la blueprint dei data product della piattaforma dati PagoPa su CDE, ed è già un data product funzionante: `dp-demo-blueprint`. Un nuovo data product nasce copiandolo: niente template, i file sono quelli veri, e `make setup` li adatta una volta sola. Un data product corrisponde a uno use case: i job che lo alimentano, le tabelle che espone e la loro quality, anche su più layer del Data Lake.

1. Crea il repo `dp-<dominio>-<use-case>` da questo, con "Use this template" su GitHub, e aprilo nel Dev Container.
2. Lancia `make setup`. Chiede dominio, use case, descrizione, owner e moduli; per i moduli scelti, il nome del primo job, se deve leggere le input port con Spark e se tenere il job export, e il layer della quality e il branch dei contratti da cui legge i check; poi le porte, una alla volta con il loro contratto: un'input port ha il nome della tabella che legge. Dove c'è un default lo mostra fra parentesi quadre, e invio lo accetta. Dopo la conferma sostituisce l'esempio con il tuo data product: descrittore, `CODEOWNERS`, questo README, il primo job al posto dei due di esempio, il DAG, una DDL scheletro per ogni output port e la configurazione della quality.
3. Leggi l'elenco dei file che ha modificato, creato o cancellato, e segui i prossimi passi che stampa alla fine: li ripete in ogni momento `make help`, o `make` da solo.

Finché non lo committi, il setup si rifà rilanciando `make setup`: mostra le modifiche non committate, chiede conferma, le annulla con git e riparte dalla blueprint. Per questo, la prima volta, non vuole modifiche non committate.

Le risposte si possono passare anche come variabili, e quelle passate non vengono chieste: `make setup DOMAIN=gpd USE_CASE=kpi OWNER=@pagopa/team-kpi`. Le variabili sono `DOMAIN`, `USE_CASE`, `DESCRIPTION`, `OWNER`, `MODULES` (`data`, `quality` o `data,quality`), `JOB`, `SPARK` (`s` perché il primo job apra una SparkSession, legga le tabelle delle input port e le stampi, `n` per lo scheletro senza Spark; di default `s`), `EXPORT` (`s` per tenere il job export, che copia le output port su Azure Blob Storage; di default `n`), `QUALITY_LAYER` (il `dlLayer` della quality, nel nome delle sue tabelle, di default `silver`), `CONTRACTS_REF` (il branch dei contratti da cui la quality legge i check, in test e in prod, di default `main`; va bene anche un tag o un commit), `INPUTS` e `OUTPUTS`, con le porte separate da virgola, come `nome` o `nome=<path del contratto>`. Con `YES=1` non chiede nulla: quello che manca prende il default, e senza default va passato come variabile. Per esempio basta `make setup DOMAIN=gpd USE_CASE=kpi DESCRIPTION="KPI giornalieri" OWNER=@pagopa/team-kpi OUTPUTS=kpi_positions YES=1`.

Le modifiche successive della blueprint non arrivano da sole nei data product già creati: vanno riportate a mano.

## Il descrittore

`data-product.yaml` descrive il data product e non lo configura: la configurazione sta nei moduli. I campi ammessi sono questi, e un test lo controlla:

| Campo | Contenuto |
|---|---|
| `name` | nome del repo e prefisso dei nomi su CDE: `dp-<dominio>-<use-case>` |
| `domain` | dominio dei dati, identificatore SQL (`gpd`, `fdr`): entra nel nome delle tabelle di quality |
| `version` | semver: la major cambia con una modifica incompatibile su una output port |
| `description` | una riga |
| `owner` | handle GitHub del team, lo stesso di `CODEOWNERS` |
| `status` | `draft`, `active` o `deprecated` |
| `modules` | i moduli presenti: `data` e `quality` |
| `inputPorts` | le tabelle che il data product legge: il nome di un'input port è quello della sua tabella, nel database `databases.inputs` |
| `outputPorts` | le tabelle che il data product espone, almeno una |
| `observabilityPorts` | dove si monitora il data product: ognuna con `name` e `type`, poi `url` per una dashboard `superset`, o `datasets` per `sodacloud`, ognuno con `name` e `url` |

Ogni input e output port ha un `name`, un identificatore SQL, e un `dataContractPath`, il path del contratto nel repo centrale dei Data Contract (`pagopa/pdnd-data-contracts`). SLA e controlli di quality stanno nel contratto, non qui.

I file deployabili possono leggere il descrittore con i segnaposto `${dp.*}`: il DAG di quality, per esempio, misura le `outputPorts`.

## L'esempio

Il data product di esempio legge due tabelle, le input port `raw_payments` e `raw_transfers`, ed espone le due tabelle silver che ne ricava, le output port `payments` e `transfers`. Lo fanno due job, e un terzo copia le tabelle silver su Azure; girano in sequenza nello stesso DAG (`data/dags/dag_pipeline.py`):

| Job | Legge | Scrive |
|---|---|---|
| `ingestion` | le tabelle delle input port | `bronze_demo_payments`, `bronze_demo_transfers` |
| `deduplication` | le tabelle bronze | `silver_demo_payments`, `silver_demo_transfers` |
| `export` | le tabelle silver | un Parquet per tabella su Azure Blob Storage (vedi [Il job export](#il-job-export)) |

Le tabelle bronze restano interne al data product: non sono output port, quindi il descrittore non le elenca e la quality non le misura. Le DDL di tutte e quattro sono in `data/ddl/tables/`. `ingestion` e `deduplication` hanno lo stesso entrypoint di esempio, quello di un job nuovo: aprono una SparkSession, leggono le tabelle delle input port e le stampano. La logica vera è un `TODO`.

## Struttura

```text
├── data-product.yaml          # il descrittore
├── CODEOWNERS                 # lo stesso owner del descrittore
├── Makefile                   # tutti i comandi, in locale e in CI
├── ruff.toml                  # regole di lint per tutto il repo
├── pytest.ini                 # i test di dp-setup-utils/; ogni job ha i suoi nel suo pyproject.toml
├── data/                      # Modulo Dati, opzionale
│   ├── jobs/<job>/            # un job Spark per cartella
│   │   ├── cde_cfg/           # definizione del job su CDE
│   │   ├── src/<job>/         # package del job: common/config per ambiente, entrypoints/
│   │   ├── tests/
│   │   ├── launcher.py        # application file per spark-submit
│   │   ├── pyproject.toml     # build del wheel
│   │   └── requirements.txt   # facoltativo: librerie che il runtime di CDE non ha
│   ├── ddl/tables/            # migrazioni V<nnn>__<descrizione>.sql
│   ├── ddl/views/             # viste
│   └── dags/                  # DAG della pipeline
├── quality/                   # Modulo Quality, opzionale
│   ├── config/<env>.yaml      # configurazione della quality, per ambiente
│   ├── ddl/tables/            # tabelle dei risultati del dq-framework
│   └── dags/dag_quality.py    # DAG di quality, uguale in tutti i data product
├── envs/<env>.yaml            # parametri di test e prod, senza segreti
├── dp-setup-utils/            # strumenti del data product, da non modificare
│   ├── render.py              # risolve i segnaposto dei file deployabili
│   ├── apply.py               # deploy su CDE con la CLI cde
│   ├── cde_setup.py           # make cde-setup: guida all'accesso a CDE per il deploy da locale
│   ├── new_job.py             # crea un job con il codice di esempio e la struttura di uno esistente
│   ├── new_port.py            # aggiunge una porta, con la DDL scheletro se è una output port, o un'observability port
│   ├── setup.py               # make setup e i prossimi passi di make help
│   └── tests/                 # controlli su descrittore, moduli e segnaposto, e test degli strumenti
├── .devcontainer/
└── .github/                   # CI, CD manuale, controlli sulle PR
```

`dp-setup-utils/` contiene gli strumenti che il Makefile lancia e i test che controllano il data product: è uguale in tutti i data product e non va modificato. Una correzione si fa nella blueprint e si porta nei data product sostituendo la cartella.

## Dove va il tuo codice

| Per… | Cosa fare |
|---|---|
| la logica di un job | `data/jobs/<job>/src/<job>/entrypoints/`, con i test in `data/jobs/<job>/tests/`. L'entrypoint riceve gli stessi parametri in ogni job: `--database`, dove scrive, `--input-database`, dove legge le input port, e `--from` e `--to`, l'intervallo da elaborare. Nell'esempio con Spark apre una SparkSession e stampa le tabelle delle input port da `--input-database`, o senza, come in locale, l'elenco dei database: va sostituito con la logica vera. Le tabelle sono in `INPUT_TABLES`, che `make setup` e `make new-job` riempiono con le input port di `data-product.yaml`, che hanno il nome della loro tabella. Il job deve essere rieseguibile sullo stesso intervallo senza duplicare dati, perché i backfill passano da lì |
| un parametro che cambia per ambiente | un campo dell'`AppConfig` in `src/<job>/common/config/`. Se il valore sta già in `envs/`, come i database, passalo come argomento nella definizione del job: `--database=${env.databases.data}` |
| un nuovo job | `make new-job JOB=<job>`: crea il job con il codice di esempio, con o senza Spark (lo chiede, oppure `SPARK=s` o `SPARK=n`), e lo installa. Da un job esistente, di default il primo di `data/jobs/` che non sia `export` (oppure `FROM=<job>`), copia solo la struttura: configurazione, logging, definizione su CDE e `pyproject.toml`, con il nome sostituito. Il suo codice, i suoi test e il suo `requirements.txt` no. Poi aggiungi `job("<job>")` nel DAG |
| librerie che il runtime Spark di CDE non ha | `data/jobs/<job>/requirements.txt`, senza pyspark: il deploy crea la python-env del job e gliela collega, `make install` le installa in locale (vedi [Python-env di un job](#python-env-di-un-job)) |
| una tabella esposta | `make new-port PORT=<nome>`: aggiunge l'output port a `data-product.yaml`, con il path del contratto della convenzione o `CONTRACT=<path>`, e con il Modulo Dati crea la DDL scheletro come migrazione successiva. Con `INPUT=1` aggiunge invece una tabella da leggere, e `PORT` è il nome della tabella. Riscrive `data-product.yaml` nel suo formato standard |
| il monitoraggio | `make new-observability-port TYPE=superset URL=<url>` per una dashboard Superset, o `TYPE=sodacloud DATASETS=<dataset>=<url>,...` per i dataset su Soda Cloud: aggiunge a `data-product.yaml` un'observability port che si chiama come il tipo, o `PORT=<nome>`. Chiede quello che manca, i dataset uno alla volta |
| una tabella da copiare su Azure | una voce in `TABLES` del job `export`, come spiega [Il job export](#il-job-export) |
| una modifica di schema | una nuova migrazione, mai la modifica di una già applicata. Deve restare compatibile con la versione del job in esecuzione durante il deploy |
| una vista | un file in `data/ddl/views/` con `CREATE OR REPLACE VIEW ${env.databases.data}.<nome> AS ...` |
| l'orchestrazione | `data/dags/dag_pipeline.py`, un task per job con `job("<job>")`: job in sequenza nello stesso DAG, per esempio `job("ingestion") >> job("deduplication")`, e schedule indipendenti in DAG separati. Con Airflow installato, un test controlla che la pipeline lanci tutti e soli i job di `data/jobs/` |

Un job non si modifica mai dalla UI di CDE: al deploy successivo la definizione in `cde_cfg/` la sovrascrive. Il vcluster è piccolo: prima di alzare il `sizing` di un job verifica la quota. Se un job ha bisogno di librerie che il runtime Spark di CDE non ha, le elenca nel suo `requirements.txt`: la python-env la crea il deploy.

### Configurazione e log di un job

Ogni job sceglie la sua configurazione con la variabile `ENV`: `dev` in locale, con `make run-dev`, e `test` o `prod` su CDE, dove la imposta la definizione del job. I campi, con i loro default, stanno in `common/config/base.py`; un ambiente ridefinisce solo quelli che cambiano. Nell'esempio `dev.py` alza il log a `DEBUG` e spegne `write_enabled`, così in locale si prova la logica senza toccare tabelle, e l'entrypoint salta la scrittura.

Nella configurazione vanno i parametri del codice. I valori dell'infrastruttura, come i database, arrivano come argomenti dalla definizione del job, che li prende da `envs/`; i segreti sono workload credential, mai nella configurazione.

`setup_logging` usa il `log_level` della configurazione, ma la variabile `LOG_LEVEL`, per esempio nel `.env`, ha la precedenza. `py4j` resta a `WARNING`, perché in debug riempirebbe il log. Ogni modulo prende il suo logger con `logging.getLogger(__name__)`. Lo smoke test di ogni job lancia l'entrypoint in tutti e tre gli ambienti e controlla che in `dev` non scriva. Con l'esempio Spark usa una SparkSession finta: i test non avviano Spark, che vuole Java, e girano anche in CI.

### Il job export

Il job `export` copia su Azure Blob Storage le tabelle elencate in `TABLES`, nel suo entrypoint, nello stesso formato in cui il dq-framework esporta le sue tabelle di risultati: un Parquet con tutto il contenuto della tabella, caricato con un SAS token.

```text
<container>/<name>/<tabella>.parquet                      di default
<container>/<name>/<tabella>/<colonna>=<valore>.parquet   con una colonna in TABLES, un Parquet per ogni suo valore
```

È un job come gli altri, in coda alla pipeline: `job("deduplication") >> job("export")` nell'esempio, così parte appena i dati sono aggiornati. Legge le tabelle da `--database`, e ogni run riscrive i blob con tutta la tabella: rilanciarlo non duplica nulla, e `--from` e `--to` non servono. Una tabella che fallisce non ferma le altre, ma alla fine il job esce con errore. In `dev` prepara i Parquet senza caricarli.

- **Dove carica**: nella sezione `export` di `envs/<env>.yaml`, `account`, `container` e `credential`, la workload credential con il SAS token nel file `sas_token`. Il job monta solo quella e la legge da `/etc/dex/secrets/<credential>/sas_token`. Test e prod non scrivono mai nello stesso container, e un test lo controlla.
- **Cosa carica**: `TABLES`, che `make setup` riempie con le output port. Le colonne esportabili sono di tipo semplice: stringhe, numeri, decimali, booleani, date, timestamp e binari; una colonna array, map o struct fa fallire l'export della sua tabella.
- **Limite**: ogni tabella passa per intero dal driver di Spark, quindi va bene per tabelle piccole e medie, come i risultati del dq-framework, non per quelle molto grandi. Per questo la definizione del job dà memoria al driver.
- **Dipendenze**: `pyarrow`, in `requirements.txt`: la python-env la crea il deploy.

Non è un modello per i job nuovi: `make new-job` non parte da `export`, che ha argomenti e credential suoi. Con `make setup` si tiene con `EXPORT=s`; senza, il setup cancella il job e la sezione `export` di `envs/`.

## Sviluppo

Si lavora nel Dev Container, che alla creazione lancia `make install`. Il Makefile carica `.env` se esiste (vedi `.env.example`).

| Comando | Cosa fa |
|---|---|
| `make` o `make help` | i prossimi passi, numerati nell'ordine in cui si fanno fino al rilascio in prod, e marcati obbligatori o facoltativi. Per ognuno dice a cosa serve e quale comando lo fa, o quale file toccare a mano. L'accesso a CDE sparisce quando CLI, endpoint e access key ci sono già. In fondo, senza numero, quelli che servono in qualsiasi momento: aggiungere un job, una input o output port o un'observability port |
| `make setup` | una volta sola, sulla copia della blueprint: sostituisce l'esempio con il tuo data product |
| `make install` | strumenti di sviluppo, job in modalità editabile e i loro `requirements.txt` |
| `make lint` | `ruff check .` |
| `make test` | test di `dp-setup-utils/` (descrittore, moduli, segnaposto, DAG, deploy), poi quelli di ogni job |
| `make run-dev JOB=ingestion ARGS="--from 2026-09-01"` | lancia il `launcher.py` di un job in locale, con `ENV=dev` |
| `make new-job JOB=<job>` | un nuovo job con il codice di esempio, con o senza Spark (`SPARK=s` o `n`, altrimenti lo chiede), e la struttura di uno esistente (`FROM=<job>`, di default il primo di `data/jobs/` che non sia `export`) |
| `make new-port PORT=<nome>` | una nuova output port con la sua DDL scheletro, o con `INPUT=1` una tabella da leggere |
| `make new-observability-port` | un'observability port: una dashboard Superset (`TYPE=superset URL=<url>`) o i dataset su Soda Cloud, ognuno con il suo URL (`TYPE=sodacloud DATASETS=<dataset>=<url>,...`); quello che manca lo chiede |
| `make build` | un wheel per job, in `dist/wheels/<job>/` |
| `make render ENV=test` | build, poi i file deployabili con i segnaposto risolti, in `dist/test/`; si ferma se un file contiene ancora un `TODO` |
| `make cde-setup` | prima del primo deploy da locale: guida a configurare CLI `cde`, endpoint del vcluster e access key, poi controlla i prerequisiti su CDE (vedi [Deploy](#deploy)) |
| `make plan ENV=test`, `make deploy ENV=test` | render, poi il deploy su CDE con la CLI `cde`: `plan` stampa i comandi, `deploy` li esegue (vedi [Deploy](#deploy)) |

Nei file deployabili (SQL, definizioni dei job, DAG) i valori si scrivono come segnaposto, risolti al deploy:

| Segnaposto | Valore |
|---|---|
| `${dp.<campo>}` | `data-product.yaml` |
| `${env.<campo>}` | `envs/<env>.yaml` |
| `${quality.<campo>}` | `quality/config/<env>.yaml` |
| `${build.wheel}` | il wheel del job, solo nei file di `data/jobs/<job>/` |
| `${job.name}` | il nome della cartella del job, solo nei file di `data/jobs/<job>/` |

Liste e mappe diventano JSON, e un segnaposto che non si risolve è un errore. `{{ ds }}` nei DAG non è un segnaposto: lo risolve Airflow a ogni run. Un file deployabile che contiene ancora un `TODO` non si renderizza: i `TODO` segnano ciò che manca.

I test che caricano davvero i DAG girano solo con Airflow installato, cioè nel Dev Container costruito con `--build-arg AIRFLOW_VERSION=<versione dell'Airflow di CDE>`; senza, vengono saltati.

## Modulo Quality

Il DAG `quality/dags/dag_quality.py` è lo stesso in tutti i data product e non si modifica: per ogni output port lancia il job del dq-framework con il contratto della porta. I task girano uno alla volta e una porta che fallisce non ferma le altre. La quality misura e non blocca nulla: ha uno schedule proprio e la pipeline dati non la aspetta.

Si compila solo `quality/config/<env>.yaml`. La terza colonna serve a portare qui una configurazione di `pagopa-data-dqf-dags`, le cui `contracts` diventano le `outputPorts` del descrittore:

| Campo | Contenuto | In `pagopa-data-dqf-dags` |
|---|---|---|
| `dqJob` | job del dq-framework nell'ambiente | `dq-quality-<env>` |
| `database` | database delle tabelle di quality: lo stesso `results_database` del dq-framework in quell'ambiente | |
| `dlLayer` | layer nel nome delle tabelle di quality: `<dlLayer>_dqf_<domain>_results` e `_failed_records` | `dl_layer` |
| `contracts.repository`, `contracts.ref` | repo dei contratti e branch, tag o commit da cui leggerli. `make setup` chiede il branch e lo scrive in tutti e due gli ambienti; qui lo si cambia per un ambiente solo | `repository`, `ref` |
| `schedule` | cron del DAG, sfasato rispetto agli altri data product | `schedule` |
| `pool` | pool Airflow condiviso dai DAG di quality (`default_pool` se non si può creare) | |
| `watermarkColumn` | colonna dei check incrementali | `watermark_column` |
| `sodaCloudEnabled` | `true` per pubblicare le metriche su Soda Cloud | `soda_cloud_enabled` |
| `primaryKeys` | chiavi dei record falliti, per output port; senza, il framework usa `dl_id` | `dataset_pk_map` |
| `xrefDatasets` | tabelle dei check cross-entity, per output port | `xref_datasets` |

`watermark_bootstrap_from` non c'è: il DAG passa sempre la data logica del run, quindi al primo run, o con un check incrementale nuovo, non serve intervenire.

Le tabelle di quality si creano con le DDL di `quality/ddl/tables/`, che copiano lo schema del dq-framework: quando il framework lo cambia, va aggiunta una migrazione.

Un run verde significa "check eseguiti", non "check passati": gli esiti stanno in `<dlLayer>_dqf_<domain>_results` e i record falliti in `<dlLayer>_dqf_<domain>_failed_records`, nel `database` della configurazione. Per rimisurare una sola output port si rilancia il suo task dall'interfaccia di Airflow. `failed_records` contiene chiave e valore dei record falliti: il database di quality va protetto almeno quanto la sorgente.

## Deploy

`make plan ENV=<env>` stampa i comandi `cde` del deploy senza eseguirli, `make deploy ENV=<env>` li esegue; tutti e due rifanno prima build e render. Funzionano da locale, su test e su prod, e dal workflow `CD`, che si lancia a mano e su prod chiede l'approvazione. Finché non esiste la CLI `dp` li esegue `dp-setup-utils/apply.py`.

Si deploya sempre il data product intero, in due passi:

1. **DDL**, a mano: il deploy non le applica, le elenca soltanto all'inizio. `make render ENV=<env>` scrive in `dist/<env>/` i file con i segnaposto risolti, con gli stessi path del repo. Esegui con Spark SQL, per esempio da una sessione CDE, le migrazioni non ancora applicate di `dist/<env>/data/ddl/tables/` e `dist/<env>/quality/ddl/tables/`, in ordine di numero, e le viste di `dist/<env>/data/ddl/views/`. Una migrazione già applicata non si riesegue.
2. **Resource, job e DAG**, con `make deploy ENV=<env>`. Per ogni job carica wheel e launcher nella resource `<name>-<job>-<env>` e crea il job Spark dalla sua definizione in `cde_cfg/`, o lo aggiorna se esiste già; poi carica i DAG nella resource `<name>-dags-<env>`, ognuno con il nome del suo job (`<name>-pipeline-<env>.py`, `<name>-quality-<env>.py`), e crea i job Airflow che mancano. Per aggiornare un DAG basta il file nuovo nella resource.

Qui e sotto `<name>` è il campo `name` di `data-product.yaml`, `<job>` una cartella di `data/jobs/` e `<env>` vale `test` o `prod`. I comandi sono quelli di `scripts/deploy.sh` del dq-framework, per i job Spark, e di `pagopa-data-dqf-dags`, per i DAG. Se il deploy si ferma a metà si rilancia: crea solo ciò che manca. I comandi stampati da `make plan` si possono anche lanciare a mano: vogliono la CLI e l'accesso configurati con `make cde-setup` e, da un terminale fuori da `make`, il `.env` caricato prima con `set -a; . ./.env; set +a`.

I file `envs/<env>.yaml` hanno già i valori predefiniti, che un data product può cambiare:

| Campo | test | prod |
|---|---|---|
| `databases.data`, il database delle tabelle del data product | `pagopa_dev` | `pagopa` |
| `databases.inputs`, il database delle tabelle delle input port | `pagopa` | `pagopa` |
| `dags.schedulePaused`, i DAG nascono in pausa | `true` | `false` |
| `credentials`, le workload credential dei job | `[]` | `[]` |
| `export`, dove il [job export](#il-job-export) carica i Parquet | container `dp-export-test` | container `dp-export` |

Test e prod condividono vcluster e Data Lake: in test le tabelle del data product non vanno mai in `pagopa`, e un test controlla che i due ambienti scrivano in database diversi. I DAG di test nascono in pausa per non togliere capacità a prod. Il valore arriva al DAG come `is_paused_upon_creation`, perché per i job Airflow la CLI di CDE non accetta opzioni di schedule, e Airflow lo usa solo la prima volta che vede il DAG. Un run lanciato a mano su un DAG in pausa resta in coda: per provarlo togli la pausa dalla UI di Airflow, lancia il run e, se il DAG ha uno schedule, rimetti la pausa quando ha finito.

### Prerequisiti, una volta per ambiente

- Con il Modulo Quality: il pool Airflow indicato in `pool` di `quality/config/<env>.yaml`, con un solo slot (va verificato che su CDE si possa creare; altrimenti `pool: default_pool` e schedule sfasati), e il job del dq-framework indicato in `dqJob`.
- Con il job export: la workload credential indicata in `export.credential` di `envs/<env>.yaml`, con il SAS token nel file `sas_token`, e su Azure il container indicato in `export.container`, su cui il SAS deve permettere di scrivere.
- Le workload credential elencate in `credentials` di `envs/<env>.yaml`, e le resource python-env che le definizioni dei job indicano con `pythonEnvResource`. Quelle dei job con un `requirements.txt` le crea il deploy.
- Per deployare da locale: l'accesso configurato con `make cde-setup`, come spiega [Accesso a CDE da locale](#accesso-a-cde-da-locale), che controlla anche i prerequisiti qui sopra, tranne il pool Airflow e il container dell'export, da verificare a mano.
- Per la CD: i GitHub Environments `test` e `prod` con i segreti `CDP_ACCESS_KEY_ID`, `CDP_PRIVATE_KEY` e `CDE_CLUSTER_URL` (anche a livello di organizzazione), e approvatori obbligatori su `prod`; le variabili `CODEBUILD_RUNNER_PROJECT` e `CDE_CLI_DOWNLOAD_URL`, a livello di repo o di organizzazione.

### Accesso a CDE da locale

Prima di deployare da locale la prima volta lancia `make cde-setup`, con la UI di CDE e la console di CDP aperte nel browser. La guida fa tre passi e per ognuno elenca cosa cliccare, anche se è già fatto: lo segna come fatto e passa al successivo. Per quelli che mancano aspetta la tua risposta:

1. **CLI `cde`**: nella UI di CDE apri Administration dal menu a sinistra (nelle versioni meno recenti è la pagina Overview), scegli il servizio nella colonna Services e, sul virtual cluster su cui deployi, clicca l'icona Cluster Details. Scarica la versione Linux sotto CLI TOOL, anche da Windows o Mac, perché la CLI gira nel Dev Container. Trascina il file nella cartella del repo e premi invio: la guida la installa in `/usr/local/bin`. Se conosci l'URL della CLI, la variabile `CDE_CLI_DOWNLOAD_URL` della CD, puoi incollarlo al posto del file.
2. **Endpoint del vcluster**: nella stessa pagina Cluster Details clicca JOBS API URL, che lo copia, e incollalo. È lo stesso per test e prod.
3. **Access key**: nella console di CDP clicca il tuo nome in basso a sinistra, poi Profile e Generate Access Key, e incolla Access Key ID e Private Key. La chiave è personale: se non puoi generarla, chiedila all'amministratore di CDP.

Poi si collega al vcluster. Se non risponde mostra l'errore della CLI e cosa controllare, tra cui i ruoli DEUser ed EnvironmentUser sull'environment di CDE, e ti fa reinserire endpoint e access key. Infine controlla su CDE i prerequisiti di ogni ambiente che la CLI sa vedere: le workload credential di `credentials`, le resource python-env dei job e il job del dq-framework. Per ogni ambiente a cui non manca nulla scrive solo `OK test` o `OK prod`; per gli altri elenca cosa manca. Il pool Airflow della quality resta da verificare a mano, e lo ricorda una volta in fondo.

Ciò che inserisci finisce subito nel `.env`, che git ignora: `CDE_VCLUSTER_ENDPOINT`, `CDE_ACCESS_KEY_ID` e `CDE_ACCESS_KEY_SECRET` (vedi `.env.example`), che la CLI legge da sola quando la lancia `make`. Il `.env` resta anche quando il Dev Container si ricostruisce, e va bene anche un'access key già in `~/.cdp/credentials`. Con Ctrl+C la guida si interrompe e, rilanciata, riparte da dove eri; con `ENV=test` controlla i prerequisiti di un solo ambiente.

L'endpoint del vcluster non sta nel repo. Il Dev Container installa la CLI da solo se sulla macchina che lo costruisce c'è la variabile `CDE_CLI_DOWNLOAD_URL`. In CD il workflow usa il segreto `CDE_CLUSTER_URL`, la variabile `CDE_CLI_DOWNLOAD_URL` e le chiavi CDP del GitHub Environment.

### Python-env di un job

Serve solo a un job che usa librerie che il runtime Spark di CDE non ha: si elencano in `data/jobs/<job>/requirements.txt`, senza pyspark, e il deploy fa il resto. Prima del job crea la sua python-env, `<name>-<job>-pyenv-<env>-<impronta>`, ci carica il file e aspetta che la build finisca, poi la collega al job. L'impronta è quella del contenuto di `requirements.txt`, perché su CDE una python-env non si modifica: se il file cambia, il deploy ne crea una nuova e il job usa la vecchia finché la nuova non è pronta.

- La build richiede qualche minuto, e il vcluster deve raggiungere PyPI (pypi.org, files.pythonhosted.org) o un suo mirror. Il deploy aspetta al massimo 30 minuti; se scade, rilancialo quando la build è finita.
- Se la build fallisce, per esempio per un pacchetto che non esiste, il deploy si ferma: guarda gli eventi, correggi `requirements.txt` e rilancia. Il file corretto ha un'altra impronta, quindi il deploy crea una python-env nuova; quella fallita si può cancellare.
- Le python-env vecchie restano su CDE: cancellale quando nessun job le usa più.

```bash
cde resource list-events --name <name>-<job>-pyenv-<env>-<impronta>
cde resource list --filter 'name[rlike]<name>-<job>-pyenv-<env>-'
cde resource delete --name <name>-<job>-pyenv-<env>-<impronta-vecchia>
```

Un job senza `requirements.txt` può usare una python-env creata a mano, indicandola con `pythonEnvResource` nella sua definizione in `cde_cfg/`; con un `requirements.txt`, invece, il deploy si ferma se la definizione la indica.

### Diagnosi e backfill

I run di un job e i log del driver:

```bash
cde run list --filter 'job[eq]<nome-job>'
cde run logs --id <run-id> --type driver --follow
```

Un backfill rilancia i job sullo stesso intervallo con `--from` e `--to`: per questo devono essere rieseguibili senza duplicare dati.
