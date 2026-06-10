"""Upload a list of dicts to GCS as newline-delimited JSON.

Filename convention: {YYYYMMDDHHMM}_{table_name}.ndjson
Each row gets a _row_hash field (MD5 of its business fields) injected here
so both the GCS file and the BigQuery staging table carry it.
"""

import hashlib
import json
import datetime
from google.cloud import storage


def _row_hash(record: dict) -> str:
    """MD5 of sorted business fields (excludes keys starting with '_')."""
    business = {k: v for k, v in record.items() if not k.startswith("_")}
    payload  = json.dumps(business, sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()


def upload(
    records:    list[dict],
    table_name: str,
    bucket:     str,
    prefix:     str = "raw",
) -> str:
    """
    Inject _row_hash, serialize to NDJSON, upload to GCS.
    Returns the gs:// URI of the uploaded object.
    """
    stamp     = datetime.datetime.utcnow().strftime("%Y%m%d%H%M")
    blob_name = f"{prefix}/{table_name}/{stamp}_{table_name}.ndjson"

    enriched = []
    for row in records:
        enriched.append({**row, "_row_hash": _row_hash(row)})

    ndjson = "\n".join(json.dumps(row, default=str) for row in enriched)

    client     = storage.Client()
    bucket_obj = client.bucket(bucket)
    blob       = bucket_obj.blob(blob_name)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")

    uri = f"gs://{bucket}/{blob_name}"
    print(f"  [GCS] uploaded {len(records):,} rows → {uri}")
    return uri
