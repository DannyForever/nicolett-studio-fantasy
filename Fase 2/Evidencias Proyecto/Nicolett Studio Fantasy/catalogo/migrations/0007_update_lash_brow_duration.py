from django.db import migrations


def update_lash_brow_duration(apps, schema_editor):
    servicio = apps.get_model('catalogo', 'Servicio')
    servicio.objects.filter(nombre='Lash & Brow').update(duracion_minutos=120)


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0006_seed_lash_brow_service'),
    ]

    operations = [
        migrations.RunPython(update_lash_brow_duration, migrations.RunPython.noop),
    ]
