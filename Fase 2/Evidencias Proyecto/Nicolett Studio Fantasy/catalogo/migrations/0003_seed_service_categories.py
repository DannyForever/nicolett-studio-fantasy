from django.db import migrations


SERVICE_CATEGORIES = (
    'Depilación Trilaser',
    'Lash & Brow',
    'Nails',
    'Peluquería',
    'Tratamientos Faciales',
)


def create_service_categories(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    for name in SERVICE_CATEGORIES:
        categoria.objects.get_or_create(
            nombre=name,
            defaults={'tipo': name, 'activa': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0002_mark_legacy_catalog_unmanaged'),
    ]

    operations = [
        migrations.RunPython(create_service_categories, migrations.RunPython.noop),
    ]
