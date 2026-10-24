from django.db import migrations


def create_maquillaje_service(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    categoria_maquillaje, _ = categoria.objects.get_or_create(
        nombre='Maquillaje',
        defaults={'tipo': 'Maquillaje', 'activa': True},
    )
    servicio.objects.get_or_create(
        nombre='Maquillaje',
        categoria=categoria_maquillaje,
        defaults={
            'descripcion': (
                'Maquillaje social, novia y eventos especiales. '
                'Prueba previa incluida en bodas.'
            ),
            'duracion_minutos': 60,
            'precio': '22000.00',
            'activo': True,
            'imagen_url': 'img/maquillaje_galeria_brand.png',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0008_update_nail_care_pricing'),
    ]

    operations = [
        migrations.RunPython(create_maquillaje_service, migrations.RunPython.noop),
    ]
