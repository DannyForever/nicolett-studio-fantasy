from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from agenda.models import DiaCerrado, Disponibilidad, ProfesionalCategoria
from panel_admin.models import Servicio
from usuarios.models import Rol, Usuario


class Command(BaseCommand):
    help = 'Crea horarios de prueba para servicios y especialistas ya registrados.'

    @transaction.atomic
    def handle(self, *args, **options):
        rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
        categorias_con_servicios = set(
            Servicio.objects.filter(
                activo=True,
                categoria__activa=True,
                categoria__tipo='servicio',
            ).values_list('categoria_id', flat=True).distinct(),
        )
        categorias_con_profesionales = set(
            ProfesionalCategoria.objects.filter(
                profesional__is_active=True,
                profesional__deleted_at__isnull=True,
                profesional__rol__nombre__iexact='Colaborador',
                categoria__tipo='servicio',
                categoria__activa=True,
            ).values_list('categoria_id', flat=True).distinct(),
        )
        especialistas_demo_creados = 0
        for categoria_id in sorted(categorias_con_servicios - categorias_con_profesionales):
            email = f'demo.agenda.categoria{categoria_id}@example.com'
            profesional = Usuario.objects.filter(email=email).first()
            if profesional is None:
                profesional = Usuario(
                    email=email,
                    correo_contacto=email,
                    nombre=f'Especialista Demo {categoria_id}',
                    apellido_paterno='Prueba',
                    apellido_materno='Agenda',
                    telefono=f'+5690000{categoria_id:04d}',
                    rol=rol_colaborador,
                )
                profesional.set_unusable_password()
                profesional.save()
                especialistas_demo_creados += 1
            elif (
                profesional.rol_id != rol_colaborador.pk
                or not profesional.is_active
                or profesional.deleted_at is not None
            ):
                raise CommandError(
                    f'La cuenta reservada para la categoría {categoria_id} existe, '
                    'pero no es un especialista de demostración activo.',
                )
            ProfesionalCategoria.objects.get_or_create(
                profesional=profesional,
                categoria_id=categoria_id,
            )

        pares_por_profesional = {}
        especialidades = ProfesionalCategoria.objects.filter(
            profesional__is_active=True,
            profesional__deleted_at__isnull=True,
            profesional__rol__nombre__iexact='Colaborador',
            categoria__tipo='servicio',
            categoria__activa=True,
        ).order_by('profesional_id', 'categoria_id')
        servicios_por_categoria = {}
        for especialidad in especialidades:
            if especialidad.categoria_id not in servicios_por_categoria:
                servicios_por_categoria[especialidad.categoria_id] = list(
                    Servicio.objects.filter(
                        categoria_id=especialidad.categoria_id,
                        activo=True,
                    ).order_by('pk'),
                )
            servicios = servicios_por_categoria[especialidad.categoria_id]
            if servicios:
                pares_por_profesional.setdefault(
                    especialidad.profesional_id,
                    [],
                ).append((especialidad.categoria_id, servicios))

        if not pares_por_profesional:
            raise CommandError(
                'No hay especialistas activos asociados a categorías con servicios activos.',
            )

        profesionales = Usuario.objects.in_bulk(pares_por_profesional)
        hoy = timezone.localdate()
        fechas = [hoy + timedelta(days=adelante) for adelante in range(1, 76)]
        cierres = set(DiaCerrado.objects.filter(
            fecha__in=fechas,
        ).values_list('fecha', flat=True))
        horas_por_especialidad = (time(9), time(12, 30), time(16))
        creados = 0
        existentes = 0
        fechas_habilitadas = 0

        for indice_dia, fecha in enumerate(fechas):
            if fecha.weekday() == 6 or fecha in cierres:
                continue
            fechas_habilitadas += 1
            for profesional_id, pares in pares_por_profesional.items():
                profesional = profesionales[profesional_id]
                una_especialidad = len(pares) == 1
                horas = (
                    (time(9), time(14))
                    if una_especialidad
                    else horas_por_especialidad
                )
                for indice_especialidad, (_, servicios) in enumerate(pares):
                    servicio = servicios[
                        (indice_dia + profesional_id + indice_especialidad) % len(servicios)
                    ]
                    inicios = horas if una_especialidad else (
                        horas[indice_especialidad % len(horas)],
                    )
                    for hora_inicio in inicios:
                        hora_fin = (
                            datetime.combine(fecha, hora_inicio)
                            + timedelta(minutes=servicio.duracion_minutos)
                        ).time()
                        _, creado = Disponibilidad.objects.get_or_create(
                            profesional=profesional,
                            servicio_id=servicio.pk,
                            fecha_especifica=fecha,
                            hora_inicio=hora_inicio,
                            defaults={
                                'dia_semana': str(fecha.weekday()),
                                'hora_fin': hora_fin,
                                'intervalo_minutos': servicio.duracion_minutos,
                                'activo': True,
                            },
                        )
                        if creado:
                            creados += 1
                        else:
                            existentes += 1

        self.stdout.write(self.style.SUCCESS(
            f'Horarios listos para {fechas_habilitadas} días, '
            f'{len(pares_por_profesional)} especialistas '
            f'({especialistas_demo_creados} especialistas demo nuevos): '
            f'{creados} bloques creados y {existentes} ya existentes.'
        ))
