"""
SCD Type-2 merge logic for BigQuery.

Pattern per run
───────────────
  1. New data lands in {table}_staging  (WRITE_TRUNCATE each run)
  2. Changed current rows   → _effective_to = now, _is_current = FALSE
  3. New + changed rows     → INSERT with _effective_from = now, _is_current = TRUE
  4. Unchanged rows         → no-op
  5. Append-only tables     → just INSERT rows whose PK is not yet present

All tables gain four meta columns in the *main* table (not staging):
  _row_hash       STRING     — MD5 of business fields; drives change detection
  _effective_from TIMESTAMP  — when this version became active
  _effective_to   TIMESTAMP  — when superseded (NULL = current version)
  _is_current     BOOL       — convenience flag
  _etl_loaded_at  TIMESTAMP  — wall-clock of the ETL run that wrote this row
"""

from google.cloud import bigquery

# Primary key per table
TABLE_PKS: dict[str, str] = {
    "users":                 "user_id",
    "donations":             "donation_id",
    "donation_items":        "item_id",
    "inventory":             "inventory_id",
    "brand_fiber_lookups":   "lookup_id",
    "match_predictions":     "pair_id",
    "subscriptions":         "subscription_id",
    "subscription_payments": "payment_id",
    "audit_trail":           "audit_id",
    "orders":                "order_id",
    "order_payments":        "order_payment_id",
}

# Tables where rows are never updated — only new rows are ever appended
APPEND_ONLY: frozenset[str] = frozenset({"audit_trail"})

_SCD2_COLS = [
    bigquery.SchemaField("_effective_from", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("_effective_to",   "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("_is_current",     "BOOL",      mode="REQUIRED"),
    bigquery.SchemaField("_etl_loaded_at",  "TIMESTAMP", mode="REQUIRED"),
]


def ensure_main_table(
    client:     bigquery.Client,
    project:    str,
    dataset:    str,
    table_name: str,
) -> None:
    """Create the SCD2 main table if it does not already exist."""
    staging_ref = f"{project}.{dataset}.{table_name}_staging"
    main_ref    = f"{project}.{dataset}.{table_name}"

    try:
        client.get_table(main_ref)
        return  # already exists
    except Exception:
        pass

    staging_table = client.get_table(staging_ref)
    main_schema   = list(staging_table.schema) + _SCD2_COLS

    main_table = bigquery.Table(main_ref, schema=main_schema)
    client.create_table(main_table)
    print(f"  [SCD2] created main table {main_ref}")


def apply(
    client:     bigquery.Client,
    project:    str,
    dataset:    str,
    table_name: str,
) -> None:
    """Run the SCD2 merge from {table}_staging into {table}."""
    pk          = TABLE_PKS[table_name]
    main_ref    = f"`{project}.{dataset}.{table_name}`"
    staging_ref = f"`{project}.{dataset}.{table_name}_staging`"

    ensure_main_table(client, project, dataset, table_name)

    if table_name in APPEND_ONLY:
        # Append-only: insert any PK not already present (ever)
        sql = f"""
            INSERT INTO {main_ref}
            SELECT
                s.*,
                CURRENT_TIMESTAMP() AS _effective_from,
                NULL                AS _effective_to,
                TRUE                AS _is_current,
                CURRENT_TIMESTAMP() AS _etl_loaded_at
            FROM {staging_ref} s
            WHERE NOT EXISTS (
                SELECT 1 FROM {main_ref} t WHERE t.{pk} = s.{pk}
            )
        """
        client.query(sql).result()
        return

    # ── Step 1: Close changed current rows ───────────────────────────────────
    close_sql = f"""
        UPDATE {main_ref} AS t
        SET
            t._effective_to = CURRENT_TIMESTAMP(),
            t._is_current   = FALSE
        WHERE t._is_current = TRUE
          AND EXISTS (
              SELECT 1 FROM {staging_ref} s
              WHERE s.{pk} = t.{pk}
                AND s._row_hash != t._row_hash
          )
    """
    client.query(close_sql).result()

    # ── Step 2: Insert new records and new versions of changed records ────────
    insert_sql = f"""
        INSERT INTO {main_ref}
        SELECT
            s.*,
            CURRENT_TIMESTAMP() AS _effective_from,
            NULL                AS _effective_to,
            TRUE                AS _is_current,
            CURRENT_TIMESTAMP() AS _etl_loaded_at
        FROM {staging_ref} s
        WHERE NOT EXISTS (
            SELECT 1 FROM {main_ref} t
            WHERE t.{pk} = s.{pk} AND t._is_current = TRUE
        )
    """
    client.query(insert_sql).result()
