from django.db import migrations


FORWARD_SQL = [
    "ALTER TABLE users ALTER COLUMN max_active_claims SET DEFAULT 3",
    "ALTER TABLE users ALTER COLUMN status SET DEFAULT 'UNDER_REVIEW'",
    "ALTER TABLE users ALTER COLUMN is_2fa_enabled SET DEFAULT 0",
    "ALTER TABLE users MODIFY COLUMN created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE users MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",

    "ALTER TABLE donations ALTER COLUMN status SET DEFAULT 'PENDING'",
    "ALTER TABLE donations ALTER COLUMN is_flagged SET DEFAULT 0",
    "ALTER TABLE donations MODIFY COLUMN submitted_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE donations MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",

    "ALTER TABLE donation_items ALTER COLUMN is_archived SET DEFAULT 0",

    "ALTER TABLE brand_fiber_lookup ALTER COLUMN is_active SET DEFAULT 1",
    "ALTER TABLE brand_fiber_lookup MODIFY COLUMN scraped_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",

    "ALTER TABLE match_predictions ALTER COLUMN is_archived_version SET DEFAULT 0",
    "ALTER TABLE match_predictions ALTER COLUMN recommendation_status SET DEFAULT 'PENDING'",
    "ALTER TABLE match_predictions MODIFY COLUMN predicted_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",

    "ALTER TABLE inventory_ledger ALTER COLUMN lifecycle_status SET DEFAULT 'ACTIVE'",
    "ALTER TABLE inventory_ledger ALTER COLUMN is_upcyclable SET DEFAULT 1",
    "ALTER TABLE inventory_ledger ALTER COLUMN low_stock_threshold SET DEFAULT 1.300",
    "ALTER TABLE inventory_ledger ALTER COLUMN was_forced_archived SET DEFAULT 0",
    "ALTER TABLE inventory_ledger MODIFY COLUMN ingested_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE inventory_ledger MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",

    "ALTER TABLE subscriptions MODIFY COLUMN created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE subscriptions MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",

    "ALTER TABLE subscription_payments MODIFY COLUMN created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE subscription_payments MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",

    "ALTER TABLE audit_trail MODIFY COLUMN occurred_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",

    "ALTER TABLE api_tokens MODIFY COLUMN created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",

    "ALTER TABLE orders ALTER COLUMN has_been_edited SET DEFAULT 0",
    "ALTER TABLE orders MODIFY COLUMN created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE orders MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",
    "ALTER TABLE orders ALTER COLUMN no_reassigned SET DEFAULT 0",

    "ALTER TABLE order_payments MODIFY COLUMN created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
    "ALTER TABLE order_payments MODIFY COLUMN updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",
]

REVERSE_SQL = [
    "ALTER TABLE users ALTER COLUMN max_active_claims DROP DEFAULT",
    "ALTER TABLE users ALTER COLUMN status DROP DEFAULT",
    "ALTER TABLE users ALTER COLUMN is_2fa_enabled DROP DEFAULT",
    "ALTER TABLE users MODIFY COLUMN created_at datetime(6) NOT NULL",
    "ALTER TABLE users MODIFY COLUMN updated_at datetime(6) NOT NULL",

    "ALTER TABLE donations ALTER COLUMN status DROP DEFAULT",
    "ALTER TABLE donations ALTER COLUMN is_flagged DROP DEFAULT",
    "ALTER TABLE donations MODIFY COLUMN submitted_at datetime(6) NOT NULL",
    "ALTER TABLE donations MODIFY COLUMN updated_at datetime(6) NOT NULL",

    "ALTER TABLE donation_items ALTER COLUMN is_archived DROP DEFAULT",

    "ALTER TABLE brand_fiber_lookup ALTER COLUMN is_active DROP DEFAULT",
    "ALTER TABLE brand_fiber_lookup MODIFY COLUMN scraped_at datetime(6) NOT NULL",

    "ALTER TABLE match_predictions ALTER COLUMN is_archived_version DROP DEFAULT",
    "ALTER TABLE match_predictions ALTER COLUMN recommendation_status DROP DEFAULT",
    "ALTER TABLE match_predictions MODIFY COLUMN predicted_at datetime(6) NOT NULL",

    "ALTER TABLE inventory_ledger ALTER COLUMN lifecycle_status DROP DEFAULT",
    "ALTER TABLE inventory_ledger ALTER COLUMN is_upcyclable DROP DEFAULT",
    "ALTER TABLE inventory_ledger ALTER COLUMN low_stock_threshold DROP DEFAULT",
    "ALTER TABLE inventory_ledger ALTER COLUMN was_forced_archived DROP DEFAULT",
    "ALTER TABLE inventory_ledger MODIFY COLUMN ingested_at datetime(6) NOT NULL",
    "ALTER TABLE inventory_ledger MODIFY COLUMN updated_at datetime(6) NOT NULL",

    "ALTER TABLE subscriptions MODIFY COLUMN created_at datetime(6) NOT NULL",
    "ALTER TABLE subscriptions MODIFY COLUMN updated_at datetime(6) NOT NULL",

    "ALTER TABLE subscription_payments MODIFY COLUMN created_at datetime(6) NOT NULL",
    "ALTER TABLE subscription_payments MODIFY COLUMN updated_at datetime(6) NOT NULL",

    "ALTER TABLE audit_trail MODIFY COLUMN occurred_at datetime(6) NOT NULL",

    "ALTER TABLE api_tokens MODIFY COLUMN created_at datetime(6) NOT NULL",

    "ALTER TABLE orders ALTER COLUMN has_been_edited DROP DEFAULT",
    "ALTER TABLE orders MODIFY COLUMN created_at datetime(6) NOT NULL",
    "ALTER TABLE orders MODIFY COLUMN updated_at datetime(6) NOT NULL",
    "ALTER TABLE orders ALTER COLUMN no_reassigned DROP DEFAULT",

    "ALTER TABLE order_payments MODIFY COLUMN created_at datetime(6) NOT NULL",
    "ALTER TABLE order_payments MODIFY COLUMN updated_at datetime(6) NOT NULL",
]


class Migration(migrations.Migration):

    dependencies = [
        ("backend", "0022_rename_brandfiberlookup_category_to_product_name"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
