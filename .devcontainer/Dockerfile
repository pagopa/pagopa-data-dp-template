# Python 3.11 e Java 17, come il vcluster CDE. bookworm perché il suo default-jre è Java 17: con Java 21 Spark 3.5 non parte.
FROM python:3.11-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jre-headless procps make curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV SPARK_LOCAL_IP="127.0.0.1"

# Facoltativo, per caricare davvero i DAG nei test: --build-arg AIRFLOW_VERSION=<versione dell'Airflow di CDE>
# TODO: come default la versione dell'Airflow del vcluster, che la CLI cde non mostra.
ARG AIRFLOW_VERSION=""
RUN if [ -n "$AIRFLOW_VERSION" ]; then \
      pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" \
        --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.11.txt"; \
    fi

# Facoltativo, per deployare dal Dev Container: devcontainer.json lo prende da CDE_CLI_DOWNLOAD_URL della macchina.
ARG CDE_CLI_DOWNLOAD_URL=""
RUN if [ -n "$CDE_CLI_DOWNLOAD_URL" ]; then \
      curl -fL -o /usr/local/bin/cde "$CDE_CLI_DOWNLOAD_URL" && chmod +x /usr/local/bin/cde; \
    fi

WORKDIR /workspaces
