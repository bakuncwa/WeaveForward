from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0011_prediction_hot_path_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='maya_card_id',
            field=models.CharField(default=None, max_length=255, null=True),
        ),
    ]
