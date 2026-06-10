"""Load a GCS NDJSON object into a BigQuery table (full replace)."""
import json
import os
from pathlib import Path
from google.cloud import bigquery


_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(table_name: str) -> list[bigquery.SchemaField]:
    schema_file = _SCHEMA_DIR / f"{table_name}.json"
    with open(schema_file) as f:
        raw = json.load(f)
    return [bigquery.SchemaField(**field) for field in raw]


def load(
    gcs_uri:    str,
    table_name: str,
    dataset:    str | None = None,
    project:    str | None = None,
) -> None:
    """
    Load `gcs_uri` (NDJSON) into BigQuery table `{dataset}.{table_name}`.
    Uses WRITE_TRUNCATE — full refresh each run.
    """
    project = project or os.environ["GCP_PROJECT"]
    dataset = dataset or os.environ["BQ_DATASET"]

    client     = bigquery.Client(project=project)
    table_ref  = f"{project}.{dataset}.{table_name}"
    schema     = _load_schema(table_name)

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ignore_unknown_values=True,
    )

    load_job = client.load_table_from_uri(gcs_uri, table_ref, job_config=job_config)
    load_job.result()

    table = client.get_table(table_ref)
    print(f"  [BQ]  loaded → {table_ref}  ({table.num_rows:,} rows)")
