-include .env
export

.DEFAULT_GOAL := help

ENV ?= dev
JOBS := $(sort $(patsubst %/,%,$(wildcard data/jobs/*/)))
FIRST_JOB := $(notdir $(firstword $(JOBS)))
JOB ?= $(FIRST_JOB)
FROM ?= $(FIRST_JOB)
ARGS ?=
SETUP_VARS := DOMAIN USE_CASE DESCRIPTION OWNER MODULES JOB SPARK QUALITY_LAYER CONTRACTS_REF INPUTS OUTPUTS YES
# A setup, new-job, new-port, new-observability-port e cde-setup passano solo le variabili della riga di comando: JOB ed ENV hanno un default qui sopra e PORT è comune nell'ambiente.
cli = $(if $(filter command,$(origin $(1))),$(2))

.PHONY: help setup install lint test build render run-dev new-job new-port new-observability-port cde-setup plan deploy guard-deployable

help:
	@python dp-setup-utils/setup.py --next-steps

setup:
	python dp-setup-utils/setup.py $(foreach v,$(SETUP_VARS),$(call cli,$(v),"$(v)=$($(v))"))

install:
	pip install 'ruff==0.16.5' pytest pyyaml build pre-commit
	@for job in $(JOBS); do pip install -e "./$$job[dev]" || exit 1; done
	@for job in $(JOBS); do if [ -f "$$job/requirements.txt" ]; then pip install -r "$$job/requirements.txt" || exit 1; fi; done

lint:
	ruff check .

test:
	pytest dp-setup-utils/tests
	@for job in $(JOBS); do (cd $$job && pytest) || exit 1; done

build:
	rm -rf dist/wheels
	@for job in $(JOBS); do python -m build --wheel --outdir dist/wheels/$$(basename $$job) $$job || exit 1; done

render: guard-deployable build
	python dp-setup-utils/render.py $(ENV)

run-dev:
	cd data/jobs/$(JOB) && ENV=dev python launcher.py $(ARGS)

new-job:
	python dp-setup-utils/new_job.py $(JOB) --from $(FROM) $(call cli,SPARK,--spark "$(SPARK)")
	pip install -e "./data/jobs/$(JOB)[dev]"

new-port:
	python dp-setup-utils/new_port.py "$(call cli,PORT,$(PORT))" $(call cli,CONTRACT,--contract "$(CONTRACT)") $(call cli,INPUT,--input)

new-observability-port:
	python dp-setup-utils/new_port.py "$(call cli,PORT,$(PORT))" --observability $(call cli,TYPE,--type "$(TYPE)") \
		$(call cli,URL,--url "$(URL)") $(call cli,DATASETS,--datasets "$(DATASETS)")

cde-setup:
	python dp-setup-utils/cde_setup.py $(call cli,ENV,$(ENV))

plan: render
	python dp-setup-utils/apply.py $(ENV) --plan

deploy: render
	python dp-setup-utils/apply.py $(ENV)

guard-deployable:
	@if [ "$(ENV)" = "dev" ]; then echo "ENV=dev non è deployabile: usa ENV=test o ENV=prod"; exit 1; fi
