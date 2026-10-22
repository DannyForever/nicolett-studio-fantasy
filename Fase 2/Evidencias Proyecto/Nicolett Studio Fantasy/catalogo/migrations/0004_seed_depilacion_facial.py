from django.db import migrations


def create_depilacion_facial(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    categoria_depilacion = categoria.objects.get(nombre='Depilación Trilaser')
    servicio.objects.get_or_create(
        nombre='Depilación facial',
        categoria=categoria_depilacion,
        defaults={
            'descripcion': 'Depilación facial con cera.',
            'duracion_minutos': 30,
            'precio': '10000.00',
            'activo': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0003_seed_service_categories'),
    ]

    operations = [
        migrations.RunPython(create_depilacion_facial, migrations.RunPython.noop),
    ]
