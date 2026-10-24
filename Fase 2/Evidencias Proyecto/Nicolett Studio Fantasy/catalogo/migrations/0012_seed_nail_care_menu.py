from django.db import migrations


NAIL_CARE_SERVICES = (
    (
        'Ruber',
        '20000.00',
        'Un solo tono + 2 diseños simples.',
    ),
    (
        'Kapping Poly Gel',
        '20000.00',
        'Uña corta | Un solo tono + 2 diseños simples.',
    ),
    (
        'Soft Gel',
        '25000.00',
        'Un solo tono + 2 diseños simples.',
    ),
    (
        'Extensión Poly Gel',
        '28000.00',
        'Un solo tono + 2 diseños simples.',
    ),
)


def seed_nail_care_menu(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    disponibilidad = apps.get_model('agenda', 'Disponibilidad')

    servicio_base = servicio.objects.filter(
        nombre='Manicure clásica de prueba',
        categoria__nombre__in=('Uñas', 'Nails'),
    ).first()
    if servicio_base:
        categoria_unas = servicio_base.categoria
        reglas_base = list(
            disponibilidad.objects.filter(
                servicio_id=servicio_base.pk,
            ).values(
                'dia_semana',
                'hora_inicio',
                'hora_fin',
                'activo',
                'profesional_id',
                'fecha_especifica',
                'intervalo_minutos',
                'descanso_inicio',
                'descanso_fin',
                'desactivado_por_personal',
            ),
        )
        servicio_base.nombre = 'Permanente'
        servicio_base.descripcion = 'Un solo tono + 2 diseños simples.'
        servicio_base.precio = '15000.00'
        servicio_base.duracion_minutos = 60
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
    else:
        categoria_unas = categoria.objects.filter(
            nombre__in=('Uñas', 'Nails'),
        ).order_by('nombre').first()
        if categoria_unas is None:
            raise categoria.DoesNotExist(
                'No existe la categoría de uñas ni Nails.',
            )
        reglas_base = []
        servicio_base = servicio.objects.create(
            nombre='Permanente',
            descripcion='Un solo tono + 2 diseños simples.',
            duracion_minutos=60,
            precio='15000.00',
            activo=True,
            categoria=categoria_unas,
        )

    for nombre, precio, descripcion in NAIL_CARE_SERVICES:
        nuevo_servicio, creado = servicio.objects.get_or_create(
            nombre=nombre,
            categoria=categoria_unas,
            defaults={
                'descripcion': descripcion,
                'duracion_minutos': 60,
                'precio': precio,
                'activo': True,
            },
        )
        if creado and reglas_base:
            disponibilidad.objects.bulk_create([
                disponibilidad(
                    **regla,
                    servicio_id=nuevo_servicio.pk,
                )
                for regla in reglas_base
            ])


def restore_nail_care_menu(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    disponibilidad = apps.get_model('agenda', 'Disponibilidad')

    servicio_permanente = servicio.objects.filter(
        nombre='Permanente',
        categoria__nombre__in=('Uñas', 'Nails'),
    ).first()
    if servicio_permanente is None:
        return
    categoria_unas = servicio_permanente.categoria
    for nombre, _, _ in NAIL_CARE_SERVICES:
        servicio_nuevo = servicio.objects.filter(
            nombre=nombre,
            categoria=categoria_unas,
        ).first()
        if servicio_nuevo:
            disponibilidad.objects.filter(
                servicio_id=servicio_nuevo.pk,
            ).delete()
            servicio_nuevo.delete()

    servicio.objects.filter(pk=servicio_permanente.pk).update(
        nombre='Manicure clásica de prueba',
        descripcion='Limado, cuidado de cutículas y esmaltado tradicional.',
        precio='15000.00',
        duracion_minutos=60,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0010_reserva_viene_con_acompanante'),
        ('catalogo', '0011_seed_lash_brow_menu'),
    ]

    operations = [
        migrations.RunPython(
            seed_nail_care_menu,
            restore_nail_care_menu,
        ),
    ]
