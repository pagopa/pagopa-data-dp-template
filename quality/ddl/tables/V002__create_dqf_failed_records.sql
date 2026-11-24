-- Stesso schema di _FAILED_RECORDS_TABLE_DDL in dq_framework/quality/result_writer.py: va tenuto allineato.
CREATE TABLE IF NOT EXISTS ${quality.database}.${quality.dlLayer}_dqf_${dp.domain}_failed_records (
    run_id           STRING    NOT NULL,
    check_name       STRING    NOT NULL,
    dataset          STRING    NOT NULL,
    execution_ts     TIMESTAMP NOT NULL,
    execution_date   DATE      NOT NULL,
    failed_record_pk STRING    NOT NULL,
    failed_value     STRING
)
USING iceberg
PARTITIONED BY (execution_date)
TBLPROPERTIES (
    'write.delete.mode' = 'merge-on-read',
    'write.merge.mode' = 'merge-on-read',
    'write.update.mode' = 'merge-on-read',
    'write.parquet.compression-codec' = 'snappy',
    'history.expire.max-snapshot-age-ms' = '7776000000'
);
