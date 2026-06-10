"""Upload a list of dicts to GCS as newline-delimited JSON."""
import json
import datetime
from google.cloud import storage


def upload(
    records:    list[dict],
    table_name: str,
    bucket:     str,
    prefix:     str = "raw",
) -> str:
    """
    Serialize `records` to NDJSON and upload to GCS.
    Returns the gs:// URI of the uploaded object.
    """
    datestamp = datetime.datetime.utcnow().strftime("%Y%m%d")
    blob_name = f"{prefix}/{table_name}/{datestamp}.ndjson"

    ndjson = "\n".join(json.dumps(row, default=str) for row in records)

    client = storage.Client()
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(blob_name)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")

    uri = f"gs://{bucket}/{blob_name}"
    print(f"  [GCS] uploaded {len(records):,} rows → {uri}")
    return uri
