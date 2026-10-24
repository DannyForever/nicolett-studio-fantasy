from django.db import migrations


LASH_BROW_SERVICES = (
    (
        'Lifting coreano',
        '25000.00',
        'Lifting coreano de pestañas para una mirada definida y natural.',
    ),
    (
        'Extensiones de pestañas rímel o clásica',
        '25000.00',
        'Extensiones de pestañas con efecto rímel o clásico.',
    ),
    (
        'Extensiones de pestañas tecnológicas',
        '30000.00',
        'Extensiones tecnológicas con diseño personalizado.',
    ),
    (
        'Volumen tecnológico',
        '35000.00',
        'Extensiones de volumen tecnológico para una mirada intensa.',
    ),
)


def seed_lash_brow_menu(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')

    categoria_lash_brow = categoria.objects.get(nombre='Lash & Brow')
    servicio_base = servicio.objects.get(
        nombre='Lash & Brow',
        categoria=categoria_lash_brow,
    )
    servicio_base.nombre = 'Laminado de cejas'
    servicio_base.descripcion = (
        'Laminado de cejas para definir y ordenar su forma natural.'
    )
    servicio_base.precio = '20000.00'
    servicio_base.duracion_minutos = 120
    servicio_base.activo = True
    servicio_base.save(
        update_fields=[
            'nombre',
            'descripcion',
            'precio',
            'duracion_minutos',
            'activo',
        ],
    )

    for nombre, precio, descripcion in LASH_BROW_SERVICES:
        servicio.objects.get_or_create(
            nombre=nombre,
            categoria=categoria_lash_brow,
            defaults={
                'descripcion': descripcion,
                'duracion_minutos': 120,
                'precio': precio,
                'activo': True,
            },
        )


def restore_lash_brow_service(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')

    categoria_lash_brow = categoria.objects.get(nombre='Lash & Brow')
    for nombre, _, _ in LASH_BROW_SERVICES:
        servicio.objects.filter(
            nombre=nombre,
            categoria=categoria_lash_brow,
        ).delete()

    servicio.objects.filter(
        nombre='Laminado de cejas',
        categoria=categoria_lash_brow,
    ).update(
        nombre='Lash & Brow',
        descripcion=(
            'Diseño y perfilado de cejas, lifting de pestañas y mirada definida.'
        ),
        precio='20000.00',
        duracion_minutos=120,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0010_seed_depilation_service_menu'),
    ]

    operations = [
        migrations.RunPython(
            seed_lash_brow_menu,
            restore_lash_brow_service,
        ),
    ]
