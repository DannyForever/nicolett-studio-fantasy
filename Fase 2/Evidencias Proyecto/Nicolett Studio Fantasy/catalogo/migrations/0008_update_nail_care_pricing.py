from django.db import migrations


def update_nail_care_service(apps, schema_editor):
    servicio = apps.get_model('catalogo', 'Servicio')
    servicio.objects.filter(
        nombre='Manicure clásica de prueba',
        categoria__nombre__iexact='Uñas',
    ).update(
        precio='15000.00',
        duracion_minutos=60,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0007_update_lash_brow_duration'),
    ]

    operations = [
        migrations.RunPython(update_nail_care_service, migrations.RunPython.noop),
    ]
