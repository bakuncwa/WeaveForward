from django.db import migrations


def _drop_if_exists(index_name, table_name):
    _db = "DATABASE()"
    return [
        f"SELECT COUNT(*) INTO @_m_n FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = {_db} AND TABLE_NAME = '{table_name}' AND INDEX_NAME = '{index_name}'",
        f"SET @_m_s = IF(@_m_n > 0, 'DROP INDEX `{index_name}` ON `{table_name}`', 'SELECT 0')",
        "PREPARE _m_stmt FROM @_m_s",
        "EXECUTE _m_stmt",
        "DEALLOCATE PREPARE _m_stmt",
    ]


class Migration(migrations.Migration):

    dependencies = [
        ("backend", "0023_database_defaults"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE TABLE IF NOT EXISTS `django_content_type` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `app_label` varchar(100) NOT NULL, `model` varchar(100) NOT NULL)",
                *_drop_if_exists("django_content_type_app_label_model_76bd3d3b_uniq", "django_content_type"),
                "ALTER TABLE `django_content_type` ADD CONSTRAINT `django_content_type_app_label_model_76bd3d3b_uniq` UNIQUE (`app_label`, `model`)",
                "CREATE TABLE IF NOT EXISTS `django_session` (`session_key` varchar(40) NOT NULL PRIMARY KEY, `session_data` longtext NOT NULL, `expire_date` datetime(6) NOT NULL)",
                *_drop_if_exists("django_session_expire_date_a5c62663", "django_session"),
                "CREATE INDEX `django_session_expire_date_a5c62663` ON `django_session` (`expire_date`)",
                "CREATE TABLE IF NOT EXISTS `django_admin_log` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `action_time` datetime(6) NOT NULL, `object_id` longtext NULL, `object_repr` varchar(200) NOT NULL, `action_flag` smallint UNSIGNED NOT NULL CHECK (`action_flag` >= 0), `change_message` longtext NOT NULL, `content_type_id` integer NULL, `user_id` integer NOT NULL)",
                "ALTER TABLE `django_admin_log` ADD CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`)",
                "ALTER TABLE `django_admin_log` ADD CONSTRAINT `django_admin_log_user_id_c564eba6_fk_users_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
