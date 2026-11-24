CREATE TABLE IF NOT EXISTS ${env.databases.data}.silver_demo_payments (
    dl_id        STRING    COMMENT 'Chiave surrogata',
    dl_event_tms TIMESTAMP COMMENT 'Ora evento: colonna watermark di default del dq-framework'
    -- TODO: colonne di business
)
USING iceberg
PARTITIONED BY (days(dl_event_tms))
TBLPROPERTIES ('format-version' = '2');
