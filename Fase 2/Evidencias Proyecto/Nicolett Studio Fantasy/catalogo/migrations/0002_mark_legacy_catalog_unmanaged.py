from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='categoria',
            options={'managed': False},
        ),
        migrations.AlterModelOptions(
            name='producto',
            options={'managed': False},
        ),
        migrations.AlterModelOptions(
            name='servicio',
            options={'managed': False},
        ),
    ]
