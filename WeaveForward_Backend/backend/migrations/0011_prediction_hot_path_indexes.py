from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backend", "0010_alter_user_first_name_alter_user_last_name_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["role", "status"], name="users_role_status_idx"),
        ),
        migrations.AddIndex(
            model_name="donationitem",
            index=models.Index(fields=["donation", "is_archived"], name="don_item_donation_arch_idx"),
        ),
        migrations.AddIndex(
            model_name="matchprediction",
            index=models.Index(fields=["item", "is_archived_version"], name="match_pred_item_arch_idx"),
        ),
    ]
