from django.db import migrations


def create_lash_brow_service(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    categoria_lash_brow = categoria.objects.get(nombre='Lash & Brow')
    servicio.objects.get_or_create(
        nombre='Lash & Brow',
        categoria=categoria_lash_brow,
        defaults={
            'descripcion': 'Diseño y perfilado de cejas, lifting de pestañas y mirada definida.',
            'duracion_minutos': 120,
            'precio': '20000.00',
            'activo': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0005_seed_peinado_sencillo'),
    ]

    operations = [
        migrations.RunPython(create_lash_brow_service, migrations.RunPython.noop),
    ]
