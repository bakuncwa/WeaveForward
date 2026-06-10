"""
Load a GCS NDJSON object into BigQuery with SCD2 change tracking.

Flow per table
──────────────
  1. Load GCS file → {table}_staging  (WRITE_TRUNCATE — always fresh snapshot)
  2. Run SCD2 merge staging → {table} (insert new / close+re-insert changed / skip unchanged)
  3. Drop staging table
"""

import json
import os
from pathlib import Path
from google.cloud import bigquery
from . import scd2

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load_staging_schema(table_name: str) -> list[bigquery.SchemaField]:
    schema_file = _SCHEMA_DIR / f"{table_name}.json"
    with open(schema_file) as f:
        raw = json.load(f)
    fields = [bigquery.SchemaField(**field) for field in raw]
    # Staging always carries _row_hash so SCD2 can detect changes
    fields.append(bigquery.SchemaField("_row_hash", "STRING", mode="NULLABLE"))
    return fields


def load(
    gcs_uri:    str,
    table_name: str,
    dataset:    str | None = None,
    project:    str | None = None,
) -> None:
    """
    Load `gcs_uri` (NDJSON) into the SCD2-tracked BigQuery table `{dataset}.{table_name}`.
    """
    project = project or os.environ["GCP_PROJECT"]
    dataset = dataset or os.environ["BQ_DATASET"]
    client  = bigquery.Client(project=project)

    staging_ref = f"{project}.{dataset}.{table_name}_staging"

    # ── Step 1: Load GCS → staging (full replace) ────────────────────────────
    job_config = bigquery.LoadJobConfig(
        schema=_load_staging_schema(table_name),
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ignore_unknown_values=True,
    )
    load_job = client.load_table_from_uri(gcs_uri, staging_ref, job_config=job_config)
    load_job.result()

    # ── Step 2: SCD2 merge staging → main table ───────────────────────────────
    scd2.apply(client, project, dataset, table_name)

    # ── Step 3: Drop staging ──────────────────────────────────────────────────
    client.delete_table(staging_ref, not_found_ok=True)

    main_table = client.get_table(f"{project}.{dataset}.{table_name}")
    print(f"  [BQ]  loaded → {project}.{dataset}.{table_name}  ({main_table.num_rows:,} rows)")
