from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0009_reservacitatemporal'),
    ]

    operations = [
        migrations.AddField(
            model_name='reserva',
            name='viene_con_acompanante',
            field=models.BooleanField(default=False),
        ),
    ]
