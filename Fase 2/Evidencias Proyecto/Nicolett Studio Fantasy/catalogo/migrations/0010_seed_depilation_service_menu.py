from django.db import migrations


DEPILATION_SERVICES = (
    (
        'Pierna completa',
        '15000.00',
        'Depilación integral de piernas para una piel suave y duradera.',
    ),
    (
        'Media pierna',
        '7000.00',
        'Depilación precisa de la zona de la rodilla al tobillo.',
    ),
    (
        'Brazo completo',
        '13000.00',
        'Depilación completa de brazos para una sensación de suavidad.',
    ),
    (
        'Medio brazo',
        '6000.00',
        'Depilación precisa del antebrazo.',
    ),
    (
        'Axila',
        '5000.00',
        'Depilación suave y efectiva en la zona de las axilas.',
    ),
    (
        'Rebaje completo',
        '15000.00',
        'Depilación íntima total para máxima higiene y confort.',
    ),
    (
        'Medio rebaje',
        '10000.00',
        'Depilación precisa de la zona del bikini.',
    ),
    (
        'Bozo',
        '5000.00',
        'Eliminación precisa del vello en el labio superior.',
    ),
    (
        'Cejas',
        '5000.00',
        'Diseño y perfilado de cejas para una mirada perfecta.',
    ),
    (
        'Nariz',
        '5000.00',
        'Depilación delicada del vello nasal exterior.',
    ),
    (
        'Oídos',
        '5000.00',
        'Depilación precisa del vello del pabellón auditivo.',
    ),
    (
        'Mentón',
        '3000.00',
        'Eliminación efectiva del vello en la zona del mentón.',
    ),
)


def create_depilation_services(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    disponibilidad = apps.get_model('agenda', 'Disponibilidad')

    categoria_depilacion = categoria.objects.get(nombre='Depilación Trilaser')
    servicio_base = servicio.objects.get(
        nombre='Depilación facial',
        categoria=categoria_depilacion,
    )
    reglas_base = list(
        disponibilidad.objects.filter(servicio_id=servicio_base.pk).values(
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

    servicio_base.nombre = 'Rostro completo'
    servicio_base.descripcion = (
        'Depilación facial completa para una piel radiante.'
    )
    servicio_base.save(update_fields=['nombre', 'descripcion'])

    for nombre, precio, descripcion in DEPILATION_SERVICES:
        nuevo_servicio, creado = servicio.objects.get_or_create(
            nombre=nombre,
            categoria=categoria_depilacion,
            defaults={
                'descripcion': descripcion,
                'duracion_minutos': 30,
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


def restore_depilation_service(apps, schema_editor):
    categoria = apps.get_model('catalogo', 'Categoria')
    servicio = apps.get_model('catalogo', 'Servicio')
    disponibilidad = apps.get_model('agenda', 'Disponibilidad')

    categoria_depilacion = categoria.objects.get(nombre='Depilación Trilaser')
    for nombre, _, _ in DEPILATION_SERVICES:
        servicio_nuevo = servicio.objects.filter(
            nombre=nombre,
            categoria=categoria_depilacion,
        ).first()
        if servicio_nuevo:
            disponibilidad.objects.filter(servicio_id=servicio_nuevo.pk).delete()
            servicio_nuevo.delete()

    servicio.objects.filter(
        nombre='Rostro completo',
        categoria=categoria_depilacion,
    ).update(
        nombre='Depilación facial',
        descripcion='Depilación facial con cera.',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0010_reserva_viene_con_acompanante'),
        ('catalogo', '0009_seed_maquillaje_service'),
    ]

    operations = [
        migrations.RunPython(
            create_depilation_services,
            restore_depilation_service,
        ),
    ]
