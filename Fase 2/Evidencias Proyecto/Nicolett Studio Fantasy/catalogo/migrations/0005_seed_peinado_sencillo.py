from django.db import migrations


def create_peinado_sencillo(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    categoria_peluqueria = categoria.objects.get(nombre='Peluquería')
    servicio.objects.get_or_create(
        nombre='Peinado sencillo',
        categoria=categoria_peluqueria,
        defaults={
            'descripcion': 'Peinado sencillo para una ocasión especial.',
            'duracion_minutos': 60,
            'precio': '10000.00',
            'activo': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0004_seed_depilacion_facial'),
    ]

    operations = [
        migrations.RunPython(create_peinado_sencillo, migrations.RunPython.noop),
    ]
