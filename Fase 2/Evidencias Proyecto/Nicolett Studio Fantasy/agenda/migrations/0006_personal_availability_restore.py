from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0005_cambiodisponibilidadpendiente_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='disponibilidad',
            name='desactivado_por_personal',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='ServicioDesactivadoPorPersonal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('servicio_id', models.PositiveBigIntegerField(unique=True)),
                ('categoria_id', models.PositiveBigIntegerField()),
            ],
            options={
                'db_table': 'agenda_servicio_desactivado_personal',
            },
        ),
    ]
