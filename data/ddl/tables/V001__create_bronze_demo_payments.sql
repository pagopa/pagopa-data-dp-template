CREATE TABLE IF NOT EXISTS ${env.databases.data}.bronze_demo_payments (
    dl_id        STRING    COMMENT 'Chiave surrogata',
    dl_event_tms TIMESTAMP COMMENT 'Ora evento'
    -- TODO: colonne della sorgente
)
USING iceberg
PARTITIONED BY (days(dl_event_tms))
TBLPROPERTIES ('format-version' = '2');
