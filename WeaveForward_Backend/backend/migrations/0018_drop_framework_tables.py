from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("backend", "0017_alter_user_email"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS token_blacklist_blacklistedtoken",
                "DROP TABLE IF EXISTS token_blacklist_outstandingtoken",
                "DROP TABLE IF EXISTS django_admin_log",
                "DROP TABLE IF EXISTS auth_user_user_permissions",
                "DROP TABLE IF EXISTS auth_user_groups",
                "DROP TABLE IF EXISTS auth_group_permissions",
                "DROP TABLE IF EXISTS auth_user",
                "DROP TABLE IF EXISTS auth_group",
                "DROP TABLE IF EXISTS auth_permission",
                "DROP TABLE IF EXISTS django_session",
                "DROP TABLE IF EXISTS django_content_type",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
