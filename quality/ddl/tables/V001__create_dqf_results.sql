-- Stesso schema di _RESULTS_TABLE_DDL in dq_framework/quality/result_writer.py: va tenuto allineato.
CREATE TABLE IF NOT EXISTS ${quality.database}.${quality.dlLayer}_dqf_${dp.domain}_results (
    run_id                 STRING    NOT NULL,
    airflow_run_id         STRING,
    dag_id                 STRING    NOT NULL,
    execution_ts           TIMESTAMP NOT NULL,
    execution_date         DATE      NOT NULL,
    dataset                STRING    NOT NULL,
    check_name             STRING    NOT NULL,
    check_column           STRING,
    check_category         STRING,
    check_dimension        STRING,
    outcome                STRING    NOT NULL,
    measured_value_numeric DOUBLE,
    measured_value_string  STRING,
    threshold_warn         STRING,
    threshold_fail         STRING,
    row_count_total        BIGINT,
    row_count_failed       BIGINT,
    has_failed_records     BOOLEAN   NOT NULL,
    watermark_column       STRING,
    watermark_from         TIMESTAMP,
    watermark_to           TIMESTAMP
)
USING iceberg
PARTITIONED BY (execution_date)
TBLPROPERTIES (
    'write.delete.mode' = 'merge-on-read',
    'write.merge.mode' = 'merge-on-read',
    'write.update.mode' = 'merge-on-read',
    'write.parquet.compression-codec' = 'snappy'
);
