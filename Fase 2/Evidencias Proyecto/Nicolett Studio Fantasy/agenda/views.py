import calendar
import json
import logging
import smtplib
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import send_mail
from django.core import signing
from django.db import transaction
from django.db.models import Count, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from config.formatters import formatear_pesos

from .forms import (
    CancelarReservaForm,
    CierreDiaForm,
    DisponibilidadDiaForm,
    ReagendarReservaForm,
    ReservaManualForm,
)
from .models import (
    CambioDisponibilidadPendiente,
    DiaCerrado,
    Disponibilidad,
    HistorialReserva,
    ProfesionalCategoria,
    Reserva,
    ReservaCitaTemporal,
    ServicioAgenda,
)
from usuarios.permissions import es_cliente

logger = logging.getLogger(__name__)
Usuario = get_user_model()
ANTICIPACION_MINIMA_GESTION_CLIENTE = timedelta(hours=48)
RESERVA_CITA_CARRITO_MINUTOS = 30


def _reserva_cliente_gestionable(reserva):
    return (
        reserva.fecha_hora > timezone.now() + ANTICIPACION_MINIMA_GESTION_CLIENTE
        and reserva.estado in ['pendiente', 'confirmada', 'suspendida']
    )


def _registrar_historial_reserva(reserva, evento, motivo=''):
    profesional = reserva.profesional
    profesional_nombre = ' '.join(
        parte for parte in (
            profesional.nombre,
            profesional.segundo_nombre,
            profesional.apellido_paterno,
            profesional.apellido_materno,
        ) if parte
    ) if profesional else 'Sin asignar'
    HistorialReserva.objects.create(
        reserva=reserva,
        evento=evento,
        fecha_hora=reserva.fecha_hora,
        servicio_nombre=reserva.servicio_nombre or (
            reserva.servicio.nombre if reserva.servicio_id else 'Servicio no disponible'
        ),
        profesional_nombre=profesional_nombre,
        estado=reserva.estado,
        duracion_minutos=reserva.duracion_minutos,
        motivo=motivo,
    )


def _reglas_para_fecha(fecha, servicio_id):
    return Disponibilidad.objects.filter(
        activo=True,
        servicio_id=servicio_id,
        fecha_especifica=fecha,
        profesional__isnull=False,
    )


def _ocupa_mismo_horario(reserva, hora_inicio, hora_fin, servicio_id, profesional_id):
    existente_inicio = (
        reserva.hora
        if isinstance(reserva, ReservaCitaTemporal)
        else timezone.localtime(reserva.fecha_hora).time()
    )
    existente_fin = (
        datetime.combine(date.min, existente_inicio)
        + timedelta(minutes=reserva.duracion_minutos)
    ).time()
    se_superponen = existente_inicio < hora_fin and hora_inicio < existente_fin
    mismo_recurso = (
        reserva.servicio_id == servicio_id
        and (
            profesional_id is None
            or reserva.profesional_id is None
            or reserva.profesional_id == profesional_id
        )
    ) or (
        profesional_id is not None
        and reserva.profesional_id == profesional_id
    )
    return se_superponen and mismo_recurso


def horas_disponibles(
    fecha,
    servicio,
    profesional_id=None,
    ignorar_reserva_id=None,
    ignorar_carrito_item_key=None,
    session_key=None,
):
    if fecha < timezone.localdate():
        return []
    if not servicio.activo or DiaCerrado.objects.filter(fecha=fecha).exists():
        return []

    reglas = _reglas_para_fecha(fecha, servicio.pk)
    if profesional_id:
        reglas = reglas.filter(profesional_id=profesional_id)
    else:
        return []
    reglas = list(reglas.select_related('profesional'))
    if not reglas:
        return []

    reservas = list(
        Reserva.objects.filter(fecha_hora__date=fecha)
        .exclude(estado='cancelada').exclude(estado='completada')
    )
    if ignorar_reserva_id:
        reservas = [reserva for reserva in reservas if reserva.pk != ignorar_reserva_id]
    reservas_temporales = list(
        ReservaCitaTemporal.objects.filter(
            fecha=fecha,
            profesional_id=profesional_id,
            vence_en__gt=timezone.now(),
        )
    )
    if ignorar_carrito_item_key and session_key:
        reservas_temporales = [
            reserva for reserva in reservas_temporales
            if not (
                reserva.session_key == session_key
                and reserva.cart_item_key == ignorar_carrito_item_key
            )
        ]

    slots = []
    for regla in reglas:
        comienzo = regla.hora_inicio
        termino = regla.hora_fin
        if not any(
            _ocupa_mismo_horario(
                reserva,
                comienzo,
                termino,
                servicio.pk,
                profesional_id,
            )
            for reserva in (*reservas, *reservas_temporales)
        ) and (fecha > timezone.localdate() or comienzo > timezone.localtime().time()):
            slots.append(comienzo.strftime('%H:%M'))
    return sorted(set(slots))


def servicios_con_horarios_disponibles():
    reglas = Disponibilidad.objects.filter(
        activo=True,
        fecha_especifica__gte=timezone.localdate(),
        servicio__activo=True,
        profesional__is_active=True,
        profesional__deleted_at__isnull=True,
        profesional__rol__nombre__iexact='Colaborador',
        profesional__especialidades__categoria_id=F('servicio__categoria_id'),
    ).values_list(
        'servicio_id',
        'profesional_id',
        'fecha_especifica',
    ).distinct()
    servicio_ids = {servicio_id for servicio_id, _, _ in reglas}
    servicios = {
        servicio.pk: servicio
        for servicio in ServicioAgenda.objects.filter(
            pk__in=servicio_ids,
            activo=True,
        )
    }
    return {
        servicio_id
        for servicio_id, profesional_id, fecha in reglas
        if servicio_id in servicios
        and horas_disponibles(
            fecha,
            servicios[servicio_id],
            profesional_id=profesional_id,
        )
    }


def reservar_horario_carrito(session_key, cart_item_key, servicio, fecha, hora, profesional_id):
    with transaction.atomic():
        profesional = Usuario.objects.select_for_update().filter(
            pk=profesional_id,
            is_active=True,
            deleted_at__isnull=True,
            rol__nombre__iexact='Colaborador',
            especialidades__categoria_id=servicio.categoria_id,
        ).first()
        if profesional is None:
            return False
        list(Disponibilidad.objects.select_for_update().filter(
            activo=True,
            fecha_especifica=fecha,
            servicio_id=servicio.pk,
            profesional_id=profesional.pk,
        ))
        if hora.strftime('%H:%M') not in horas_disponibles(
            fecha,
            servicio,
            profesional_id=profesional.pk,
            ignorar_carrito_item_key=cart_item_key,
            session_key=session_key,
        ):
            return False
        ReservaCitaTemporal.objects.update_or_create(
            session_key=session_key,
            cart_item_key=cart_item_key,
            defaults={
                'servicio_id': servicio.pk,
                'profesional': profesional,
                'fecha': fecha,
                'hora': hora,
                'duracion_minutos': servicio.duracion_minutos,
                'vence_en': timezone.now() + timedelta(
                    minutes=RESERVA_CITA_CARRITO_MINUTOS,
                ),
            },
        )
    return True


def _notificar(reserva, asunto, mensaje):
    destinatario = reserva.correo_cliente
    if not destinatario:
        return False
    send_mail(
        asunto,
        mensaje,
        getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
        [destinatario],
        fail_silently=False,
    )
    return True


def _fecha_texto(reserva):
    return timezone.localtime(reserva.fecha_hora).strftime('%d-%m-%Y a las %H:%M')


def _enviar_aviso_cancelacion(reserva, motivo):
    try:
        enviado = _notificar(
            reserva,
            'Aviso de cancelación de tu cita - Nicolett Studio',
            (
                f'Hola {reserva.nombre_cliente}, lamentamos informarte que tu cita de '
                f'{reserva.servicio_nombre} para el {_fecha_texto(reserva)} fue cancelada. '
                f'Motivo: {motivo}. Por favor, contáctanos para coordinar una nueva hora.'
            ),
        )
        return True if enviado else None
    except (OSError, smtplib.SMTPException):
        logger.exception('No se pudo enviar el aviso de cancelación de la reserva %s.', reserva.pk)
        return False


def _construir_calendario(hoy, mes_seleccionado, fecha_seleccionada):
    primero = mes_seleccionado.replace(day=1)
    ultimo = date(
        primero.year,
        primero.month,
        calendar.monthrange(primero.year, primero.month)[1],
    )
    reglas_por_fecha = {}
    reglas = Disponibilidad.objects.filter(
        activo=True,
        servicio__activo=True,
        fecha_especifica__range=(primero, ultimo),
        profesional__isnull=False,
    ).select_related('servicio', 'profesional')
    for regla in reglas:
        reglas_por_fecha.setdefault(regla.fecha_especifica, []).append(regla)
    fechas_cerradas = set(
        DiaCerrado.objects.filter(fecha__range=(primero, ultimo)).values_list('fecha', flat=True)
    )
    cantidad_citas_por_fecha = {
        fila['fecha_cita']: fila['cantidad']
        for fila in Reserva.objects.filter(
            fecha_hora__date__range=(primero, ultimo),
        ).exclude(estado__in=['cancelada', 'completada'])
        .annotate(fecha_cita=TruncDate('fecha_hora'))
        .values('fecha_cita')
        .annotate(cantidad=Count('pk'))
    }
    reservas_del_mes = list(
        Reserva.objects.filter(
            fecha_hora__date__range=(primero, ultimo),
        ).exclude(estado__in=['cancelada', 'completada'])
    )
    reservas_temporales_mes = list(
        ReservaCitaTemporal.objects.filter(
            fecha__range=(primero, ultimo),
            vence_en__gt=timezone.now(),
        )
    )
    nombres_meses = [
        'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
        'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
    ]
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(primero.year, primero.month):
        cells = []
        for dia in week:
            has_slots = False
            if dia >= hoy and dia not in fechas_cerradas:
                day_rules = reglas_por_fecha.get(dia, [])
                day_reservas = [
                    reserva for reserva in reservas_del_mes
                    if timezone.localtime(reserva.fecha_hora).date() == dia
                ]
                day_reservas.extend(
                    reserva for reserva in reservas_temporales_mes
                    if reserva.fecha == dia
                )
                for regla in day_rules:
                    inicio = regla.hora_inicio
                    fin = regla.hora_fin
                    if not any(
                        _ocupa_mismo_horario(
                            reserva,
                            inicio,
                            fin,
                            regla.servicio_id,
                            regla.profesional_id,
                        )
                        for reserva in day_reservas
                    ):
                        has_slots = True
                        break
            cells.append({
                'date': dia,
                'in_month': dia.month == primero.month,
                'enabled': has_slots,
                'has_configured_slots': bool(reglas_por_fecha.get(dia)),
                'closed': dia in fechas_cerradas,
                'appointments': cantidad_citas_por_fecha.get(dia, 0),
                'can_configure': dia >= hoy,
                'selected': dia == fecha_seleccionada,
            })
        weeks.append(cells)
    return {
        'label': f'{nombres_meses[primero.month - 1].capitalize()} {primero.year}',
        'weeks': weeks,
        'previous': (primero.replace(day=1) - timedelta(days=1)).replace(day=1),
        'next': (ultimo + timedelta(days=1)).replace(day=1),
    }


def _agrupar_disponibilidades(reglas, cambios_pendientes):
    grupos = {}
    cambios = {}
    for cambio in cambios_pendientes:
        cambios.setdefault((cambio.servicio_id, cambio.profesional_id), []).append(cambio)
    for regla in reglas:
        key = (regla.servicio_id, regla.profesional_id)
        grupo = grupos.setdefault(key, {
            'servicio_id': regla.servicio_id,
            'servicio': regla.servicio.nombre if regla.servicio_id else 'Servicio eliminado',
            'profesional_id': regla.profesional_id,
            'profesional': ' '.join(
                part for part in (
                    getattr(regla.profesional, 'nombre', ''),
                    getattr(regla.profesional, 'apellido_paterno', ''),
                    getattr(regla.profesional, 'apellido_materno', ''),
                ) if part
            ) or 'Sin profesional',
            'duracion': regla.servicio.duracion_minutos if regla.servicio_id else regla.intervalo_minutos or 30,
            'activo': True,
            'bloques': [],
            'cambios': cambios.get(key, []),
        })
        grupo['activo'] = grupo['activo'] and regla.activo
        grupo['bloques'].append({
            'inicio': regla.hora_inicio.strftime('%H:%M'),
            'fin': regla.hora_fin.strftime('%H:%M'),
        })
    resultado = []
    for grupo in grupos.values():
        grupo['bloques'].sort(key=lambda bloque: bloque['inicio'])
        grupo['bloques_json'] = json.dumps(grupo['bloques'])
        grupo['cambio'] = bool(grupo['cambios'])
        resultado.append(grupo)
    return sorted(resultado, key=lambda grupo: (grupo['servicio'].casefold(), grupo['profesional'].casefold()))


@require_GET
def gestion_agenda_citas(request):
    hoy = timezone.localdate()
    servicios = ServicioAgenda.objects.filter(activo=True).order_by('nombre')
    reservas = Reserva.objects.select_related(
        'cliente', 'profesional', 'servicio',
    ).order_by('fecha_hora')
    filtro_fecha = request.GET.get('fecha', '').strip()
    if filtro_fecha:
        try:
            fecha_seleccionada = date.fromisoformat(filtro_fecha)
            reservas = reservas.filter(fecha_hora__date=fecha_seleccionada)
        except ValueError:
            messages.error(request, 'La fecha de búsqueda no es válida.')
    else:
        reservas = reservas.filter(fecha_hora__date__gte=hoy)

    mes_param = request.GET.get('mes', '').strip()
    dia_param = request.GET.get('dia', '').strip()
    try:
        mes_seleccionado = date.fromisoformat(f'{mes_param}-01') if mes_param else hoy
    except ValueError:
        mes_seleccionado = hoy
    try:
        fecha_seleccionada = date.fromisoformat(dia_param) if dia_param else (
            hoy if mes_seleccionado.year == hoy.year and mes_seleccionado.month == hoy.month
            else mes_seleccionado.replace(day=1)
        )
    except ValueError:
        fecha_seleccionada = hoy
    if (fecha_seleccionada.year, fecha_seleccionada.month) != (
        mes_seleccionado.year,
        mes_seleccionado.month,
    ):
        fecha_seleccionada = mes_seleccionado.replace(day=1)
    reserva_form = ReservaManualForm()
    disponibilidad_dia_form = DisponibilidadDiaForm(
        initial={'fecha': fecha_seleccionada.isoformat()},
    )
    cierre_form = CierreDiaForm()
    reglas_del_dia = list(Disponibilidad.objects.filter(
        fecha_especifica=fecha_seleccionada,
    ).select_related('servicio', 'profesional').order_by('hora_inicio'))
    cambios_del_dia = list(CambioDisponibilidadPendiente.objects.filter(
        fecha=fecha_seleccionada,
    ))
    disponibilidad_grupos = _agrupar_disponibilidades(reglas_del_dia, cambios_del_dia)
    return render(request, 'agenda/agenda_lista.html', {
        'reservas': reservas,
        'servicios': servicios,
        'reserva_form': reserva_form,
        'disponibilidad_dia_form': disponibilidad_dia_form,
        'cierre_form': cierre_form,
        'calendario_mes': _construir_calendario(
            hoy,
            mes_seleccionado,
            fecha_seleccionada,
        ),
        'disponibilidad_grupos': disponibilidad_grupos,
        'mes_seleccionado': mes_seleccionado,
        'fecha_seleccionada': fecha_seleccionada,
        'hoy': hoy,
        'fecha_configurable': fecha_seleccionada >= hoy
        and not DiaCerrado.objects.filter(fecha=fecha_seleccionada).exists(),
        'dia_cerrado': DiaCerrado.objects.filter(fecha=fecha_seleccionada).first(),
        'filtro_fecha': filtro_fecha,
        'dia_labels': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
    })


@require_GET
def horas_disponibles_json(request):
    try:
        fecha = date.fromisoformat(request.GET.get('fecha', ''))
        servicio = ServicioAgenda.objects.get(pk=request.GET.get('servicio'), activo=True)
    except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
        return JsonResponse({'hours': [], 'error': 'Selecciona un servicio activo y una fecha válida.'}, status=400)
    profesional_id = request.GET.get('profesional') or None
    reserva_id = request.GET.get('reserva') or None
    if profesional_id and (not profesional_id.isdecimal() or int(profesional_id) < 1):
        return JsonResponse({'hours': [], 'error': 'El profesional indicado no es válido.'}, status=400)
    if reserva_id and (not reserva_id.isdecimal() or int(reserva_id) < 1):
        return JsonResponse({'hours': [], 'error': 'La cita indicada no es válida.'}, status=400)
    if profesional_id:
        profesional_id = int(profesional_id)
    horas = horas_disponibles(
        fecha,
        servicio,
        profesional_id=profesional_id,
        ignorar_reserva_id=int(reserva_id) if reserva_id else None,
    )
    return JsonResponse({'hours': horas})


@require_GET
def profesionales_por_servicio_json(request):
    service_id = request.GET.get('servicio', '')
    if not service_id.isdecimal():
        return JsonResponse(
            {'professionals': [], 'error': 'Selecciona un servicio válido.'},
            status=400,
        )
    servicio = ServicioAgenda.objects.filter(pk=service_id, activo=True).first()
    if servicio is None:
        return JsonResponse(
            {'professionals': [], 'error': 'El servicio no existe o está inactivo.'},
            status=404,
        )
    profesionales = Usuario.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
        rol__nombre__iexact='Colaborador',
        especialidades__categoria_id=servicio.categoria_id,
    ).distinct().order_by('nombre', 'apellido_paterno')
    return JsonResponse({
        'professionals': [
            {
                'id': profesional.pk,
                'name': ' '.join(
                    part for part in (
                        profesional.nombre,
                        profesional.segundo_nombre,
                        profesional.apellido_paterno,
                        profesional.apellido_materno,
                    ) if part
                ),
            }
            for profesional in profesionales
        ],
    })


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
@require_GET
def cliente_profesionales_json(request):
    service_id = request.GET.get('servicio', '')
    date_value = request.GET.get('fecha', '')
    try:
        fecha = date.fromisoformat(date_value)
        servicio = ServicioAgenda.objects.get(pk=service_id, activo=True)
    except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
        return JsonResponse(
            {'professionals': [], 'error': 'Selecciona un servicio activo y una fecha válida.'},
            status=400,
        )

    if fecha < timezone.localdate() or DiaCerrado.objects.filter(fecha=fecha).exists():
        return JsonResponse({'professionals': []})

    reserva_id = request.GET.get('reserva', '')
    reserva_ignorada = None
    if reserva_id:
        if not reserva_id.isdecimal():
            return JsonResponse({'professionals': [], 'error': 'La cita indicada no es válida.'}, status=400)
        reserva_ignorada = Reserva.objects.filter(
            pk=reserva_id,
            cliente=request.user,
            estado__in=['pendiente', 'confirmada', 'suspendida'],
            fecha_hora__gt=timezone.now() + ANTICIPACION_MINIMA_GESTION_CLIENTE,
        ).first()
        if reserva_ignorada is None:
            return JsonResponse({'professionals': [], 'error': 'La cita no se puede modificar.'}, status=400)

    profesionales_con_horarios = Disponibilidad.objects.filter(
        activo=True,
        fecha_especifica=fecha,
        servicio_id=servicio.pk,
        profesional__is_active=True,
        profesional__deleted_at__isnull=True,
        profesional__rol__nombre__iexact='Colaborador',
        profesional__especialidades__categoria_id=servicio.categoria_id,
    ).values_list('profesional_id', flat=True).distinct()
    profesionales = Usuario.objects.filter(
        pk__in=profesionales_con_horarios,
    ).order_by('nombre', 'apellido_paterno')
    profesionales_disponibles = [
        profesional
        for profesional in profesionales
        if horas_disponibles(
            fecha,
            servicio,
            profesional.pk,
            ignorar_reserva_id=reserva_ignorada.pk if reserva_ignorada else None,
            ignorar_carrito_item_key=request.GET.get('cart_item_key'),
            session_key=request.session.session_key,
        )
    ]
    return JsonResponse({
        'professionals': [
            {
                'id': profesional.pk,
                'name': ' '.join(
                    part for part in (
                        profesional.nombre,
                        profesional.segundo_nombre,
                        profesional.apellido_paterno,
                        profesional.apellido_materno,
                    ) if part
                ),
            }
            for profesional in profesionales_disponibles
        ],
    })


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
@require_GET
def cliente_horas_disponibles_json(request):
    try:
        fecha = date.fromisoformat(request.GET.get('fecha', ''))
        servicio = ServicioAgenda.objects.get(pk=request.GET.get('servicio'), activo=True)
        profesional_id = request.GET.get('profesional', '')
        if not profesional_id.isdecimal() or int(profesional_id) < 1:
            raise ValueError
    except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
        return JsonResponse(
            {'hours': [], 'error': 'Selecciona un servicio, una fecha y un profesional válidos.'},
            status=400,
        )

    profesional_valido = Usuario.objects.filter(
        pk=profesional_id,
        is_active=True,
        deleted_at__isnull=True,
        rol__nombre__iexact='Colaborador',
        especialidades__categoria_id=servicio.categoria_id,
    ).exists()
    if not profesional_valido:
        return JsonResponse({'hours': [], 'error': 'El profesional no está habilitado para este servicio.'}, status=400)

    reserva_id = request.GET.get('reserva', '')
    reserva_ignorada = None
    if reserva_id:
        if not reserva_id.isdecimal():
            return JsonResponse({'hours': [], 'error': 'La cita indicada no es válida.'}, status=400)
        reserva_ignorada = Reserva.objects.filter(
            pk=reserva_id,
            cliente=request.user,
            estado__in=['pendiente', 'confirmada', 'suspendida'],
            fecha_hora__gt=timezone.now() + ANTICIPACION_MINIMA_GESTION_CLIENTE,
        ).first()
        if reserva_ignorada is None:
            return JsonResponse({'hours': [], 'error': 'La cita no se puede modificar.'}, status=400)

    return JsonResponse({
        'hours': horas_disponibles(
            fecha,
            servicio,
            profesional_id=int(profesional_id),
            ignorar_reserva_id=reserva_ignorada.pk if reserva_ignorada else None,
            ignorar_carrito_item_key=request.GET.get('cart_item_key'),
            session_key=request.session.session_key,
        ),
    })


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
@require_GET
def cliente_calendario_disponibilidad_json(request):
    servicio_id = request.GET.get('servicio')
    try:
        mes = date.fromisoformat(f"{request.GET.get('mes', '')}-01")
    except (ValueError, TypeError):
        return JsonResponse(
            {'error': 'Selecciona un mes válido.'},
            status=400,
        )

    if servicio_id:
        try:
            servicios = [ServicioAgenda.objects.get(pk=servicio_id, activo=True)]
        except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
            return JsonResponse(
                {'error': 'El servicio seleccionado no está disponible.'},
                status=400,
            )
    else:
        servicios = list(ServicioAgenda.objects.filter(activo=True).order_by('pk'))
    servicios_por_id = {servicio.pk: servicio for servicio in servicios}
    servicio_ids = list(servicios_por_id)
    categorias_por_servicio = {
        servicio.pk: servicio.categoria_id
        for servicio in servicios
    }
    especialidades = set(ProfesionalCategoria.objects.filter(
        categoria_id__in=set(categorias_por_servicio.values()),
    ).values_list('profesional_id', 'categoria_id'))

    primer_dia = mes.replace(day=1)
    ultimo_dia = date(
        primer_dia.year,
        primer_dia.month,
        calendar.monthrange(primer_dia.year, primer_dia.month)[1],
    )
    reglas_por_fecha = {}
    for regla in Disponibilidad.objects.filter(
        activo=True,
        fecha_especifica__range=(primer_dia, ultimo_dia),
        servicio_id__in=servicio_ids,
        profesional__is_active=True,
        profesional__deleted_at__isnull=True,
        profesional__rol__nombre__iexact='Colaborador',
    ).values('fecha_especifica', 'servicio_id', 'profesional_id'):
        servicio = servicios_por_id[regla['servicio_id']]
        if (
            regla['profesional_id'],
            categorias_por_servicio[servicio.pk],
        ) not in especialidades:
            continue
        reglas_por_fecha.setdefault(
            (regla['fecha_especifica'], regla['servicio_id']),
            set(),
        ).add(
            regla['profesional_id'],
        )
    fechas_cerradas = set(
        DiaCerrado.objects.filter(
            fecha__range=(primer_dia, ultimo_dia),
        ).values_list('fecha', flat=True)
    )
    today = timezone.localdate()
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
        primer_dia.year,
        primer_dia.month,
    ):
        cells = []
        for day in week:
            past = day < today
            closed = day in fechas_cerradas
            has_slots = False
            if day.month == primer_dia.month and not past and not closed:
                for servicio in servicios:
                    for professional_id in reglas_por_fecha.get((day, servicio.pk), set()):
                        if horas_disponibles(day, servicio, professional_id):
                            has_slots = True
                            break
                    if has_slots:
                        break
            cells.append({
                'date': day.isoformat(),
                'day': day.day,
                'in_month': day.month == primer_dia.month,
                'past': past,
                'closed': closed,
                'available': has_slots,
            })
        weeks.append(cells)

    nombres_meses = (
        'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
        'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
    )
    return JsonResponse({
        'month': primer_dia.strftime('%Y-%m'),
        'label': f'{nombres_meses[primer_dia.month - 1].capitalize()} {primer_dia.year}',
        'weeks': weeks,
    })


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
@require_POST
def crear_reserva_cliente(request):
    try:
        fecha = date.fromisoformat(request.POST.get('fecha', ''))
        hora = time.fromisoformat(request.POST.get('hora', ''))
        servicio = ServicioAgenda.objects.get(
            pk=request.POST.get('servicio'),
            activo=True,
        )
        profesional_id = request.POST.get('profesional', '')
        if (
            not profesional_id.isdecimal()
            or int(profesional_id) < 1
            or hora.second
            or hora.microsecond
        ):
            raise ValueError
    except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
        messages.error(request, 'Selecciona un servicio, fecha, profesional y hora válidos.')
        return redirect('cliente_agendamiento')

    with transaction.atomic():
        Usuario.objects.select_for_update().get(pk=request.user.pk)
        if fecha < timezone.localdate():
            messages.error(request, 'No es posible agendar: la fecha seleccionada ya pasó y no hay horas disponibles.')
            return redirect('cliente_agendamiento')
        if DiaCerrado.objects.filter(fecha=fecha).exists():
            messages.error(request, 'No es posible agendar: el salón está cerrado ese día.')
            return redirect('cliente_agendamiento')

        profesional = Usuario.objects.select_for_update().filter(
            pk=profesional_id,
            is_active=True,
            deleted_at__isnull=True,
            rol__nombre__iexact='Colaborador',
            especialidades__categoria_id=servicio.categoria_id,
        ).first()
        if profesional is None:
            messages.error(request, 'El profesional seleccionado no está habilitado para ese servicio.')
            return redirect('cliente_agendamiento')

        list(Disponibilidad.objects.select_for_update().filter(
            activo=True,
            fecha_especifica=fecha,
            servicio_id=servicio.pk,
            profesional=profesional,
        ))
        from carrito.views import _carrito_sesion, _guardar_carrito, _session_key

        carrito = _carrito_sesion(request)
        cart_item_key = str(uuid4())
        if not reservar_horario_carrito(
            _session_key(request),
            cart_item_key,
            servicio,
            fecha,
            hora,
            profesional.pk,
        ):
            messages.error(request, 'Ese horario acaba de ser ocupado. Selecciona otro.')
            return redirect('cliente_agendamiento')
        carrito['servicios'].append({
            'key': cart_item_key,
            'id': servicio.pk,
            'fecha': fecha.isoformat(),
            'profesional': str(profesional.pk),
            'hora': hora.strftime('%H:%M'),
            'pago': '',
            'viene_con_acompanante': request.POST.get('viene_con_acompanante') == 'si',
        })
        _guardar_carrito(request, carrito)
    messages.success(
        request,
        'La cita quedó preparada en tu carrito. Revisa los datos y selecciona el pago para confirmar.',
    )
    return redirect(f"{reverse('cliente_agendamiento')}?abrir_carrito=1")


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
@require_POST
def cancelar_reserva_cliente(request, pk):
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().filter(
            pk=pk,
            cliente=request.user,
        ).select_related('cambio_disponibilidad').first()
        if (
            reserva is None
            or not _reserva_cliente_gestionable(reserva)
        ):
            messages.error(request, 'Esta cita ya no se puede cancelar; la gestión se cierra 48 horas antes de la atención.')
            return redirect('cliente_gestionar_citas')

        cambio_pendiente = reserva.cambio_disponibilidad
        _registrar_historial_reserva(
            reserva,
            'cancelada',
            'Cancelada por la clienta desde su cuenta.',
        )
        reserva.estado = 'cancelada'
        reserva.motivo_cancelacion = 'Cancelada por la clienta desde su cuenta.'
        reserva.cambio_disponibilidad = None
        reserva.respuesta_suspension = ''
        reserva.save(update_fields=[
            'estado',
            'motivo_cancelacion',
            'cambio_disponibilidad',
            'respuesta_suspension',
            'updated_at',
        ])
        from carrito.models import DetallePedido

        monto_servicio = DetallePedido.objects.filter(
            reserva=reserva,
            tipo='servicio',
        ).values_list('monto_pagado', flat=True).first()
        _limpiar_cambio_si_resuelto(cambio_pendiente)

    if monto_servicio is None:
        monto_servicio = 0
    messages.success(
        request,
        'La cita fue cancelada y quedó registrada en tu historial. '
        f'Se solicitará la devolución de {formatear_pesos(monto_servicio)} correspondiente al servicio '
        '(no incluye productos); el reembolso será gestionado a la brevedad.',
    )
    return redirect('cliente_gestionar_citas')


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
@require_POST
def reagendar_reserva_cliente(request, pk):
    try:
        fecha = date.fromisoformat(request.POST.get('fecha', ''))
        hora = time.fromisoformat(request.POST.get('hora', ''))
        servicio_id = request.POST.get('servicio', '')
        profesional_id = request.POST.get('profesional', '')
        if (
            not servicio_id.isdecimal()
            or not profesional_id.isdecimal()
            or int(servicio_id) < 1
            or int(profesional_id) < 1
            or hora.second
            or hora.microsecond
        ):
            raise ValueError
    except (TypeError, ValueError):
        messages.error(request, 'Selecciona servicio, fecha, profesional y horario válidos.')
        return redirect('cliente_gestionar_citas')

    inicio = datetime.combine(fecha, hora)
    fecha_hora = timezone.make_aware(inicio) if timezone.is_naive(inicio) else inicio
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().filter(
            pk=pk,
            cliente=request.user,
        ).select_related('cambio_disponibilidad').first()
        if (
            reserva is None
            or not _reserva_cliente_gestionable(reserva)
        ):
            messages.error(request, 'Esta cita ya no se puede re-agendar; la gestión se cierra 48 horas antes de la atención.')
            return redirect('cliente_gestionar_citas')

        servicio = ServicioAgenda.objects.filter(
            pk=servicio_id,
            activo=True,
        ).first()
        if servicio is None:
            messages.error(request, 'El servicio seleccionado no está disponible.')
            return redirect('cliente_gestionar_citas')

        profesional = Usuario.objects.filter(
            pk=profesional_id,
            is_active=True,
            deleted_at__isnull=True,
            rol__nombre__iexact='Colaborador',
            especialidades__categoria_id=servicio.categoria_id,
        ).first()
        if profesional is None:
            messages.error(request, 'El profesional seleccionado no está habilitado para ese servicio.')
            return redirect('cliente_gestionar_citas')

        list(Disponibilidad.objects.select_for_update().filter(
            activo=True,
            fecha_especifica=fecha,
            servicio_id=servicio.pk,
            profesional=profesional,
        ))
        if hora.strftime('%H:%M') not in horas_disponibles(
            fecha,
            servicio,
            profesional_id=profesional.pk,
            ignorar_reserva_id=reserva.pk,
        ):
            messages.error(request, 'Ese horario ya no está disponible. Elige otra opción.')
            return redirect('cliente_gestionar_citas')

        nueva_fin = fecha_hora + timedelta(minutes=servicio.duracion_minutos)
        otras_reservas = Reserva.objects.select_for_update().filter(
            cliente=request.user,
            fecha_hora__date=fecha,
        ).exclude(
            pk=reserva.pk,
        ).exclude(
            estado__in=['cancelada', 'completada'],
        )
        for otra_reserva in otras_reservas:
            otra_inicio = timezone.localtime(otra_reserva.fecha_hora)
            otra_fin = otra_inicio + timedelta(minutes=otra_reserva.duracion_minutos)
            if otra_inicio < nueva_fin and fecha_hora < otra_fin:
                messages.error(request, 'Ya tienes otra cita que se cruza con ese horario.')
                return redirect('cliente_gestionar_citas')

        cambio_pendiente = reserva.cambio_disponibilidad
        servicio_anterior = reserva.servicio_nombre
        profesional_anterior = ' '.join(part for part in (
            reserva.profesional.nombre,
            reserva.profesional.segundo_nombre,
            reserva.profesional.apellido_paterno,
            reserva.profesional.apellido_materno,
        ) if part) if reserva.profesional else 'Sin asignar'
        fecha_hora_anterior = _fecha_texto(reserva)
        _registrar_historial_reserva(reserva, 'modificada')
        reserva.fecha_hora = fecha_hora
        reserva.servicio_id = servicio.pk
        reserva.servicio_nombre = servicio.nombre
        reserva.duracion_minutos = servicio.duracion_minutos
        reserva.profesional = profesional
        reserva.cambio_disponibilidad = None
        reserva.motivo_suspension = ''
        if reserva.estado == 'suspendida':
            reserva.estado = 'confirmada'
            reserva.respuesta_suspension = 'reagendar'
        reserva.save(update_fields=[
            'fecha_hora',
            'servicio',
            'servicio_nombre',
            'duracion_minutos',
            'profesional',
            'cambio_disponibilidad',
            'motivo_suspension',
            'estado',
            'respuesta_suspension',
            'updated_at',
        ])
        _limpiar_cambio_si_resuelto(cambio_pendiente)

    try:
        _notificar(
            reserva,
            'Aviso de cambio en tu cita - Nicolett Studio',
            (
                f'Hola {reserva.nombre_cliente}, tu cita fue modificada.\n'
                f'Servicio anterior: {servicio_anterior}.\n'
                f'Nuevo servicio: {reserva.servicio_nombre}.\n'
                f'Horario anterior: {fecha_hora_anterior}.\n'
                f'Nuevo horario: {_fecha_texto(reserva)}.\n'
                f'Profesional anterior: {profesional_anterior}.\n'
                f'Nuevo profesional: {_nombre_profesional(reserva.profesional)}.'
            ),
        )
    except (OSError, smtplib.SMTPException):
        logger.exception('No se pudo enviar el aviso de edición de la reserva %s.', reserva.pk)
        messages.warning(
            request,
            'La cita se modificó y quedó registrada en tu historial, pero no se pudo enviar el aviso por correo.',
        )
    else:
        messages.success(
            request,
            'La cita fue re-agendada, notificada por correo y actualizada en tu historial.',
        )
    return redirect('cliente_gestionar_citas')


def _cargar_opciones_hora(form, fecha_value, servicio_id, profesional_id=None, ignorar_reserva_id=None):
    try:
        fecha = date.fromisoformat(fecha_value)
        servicio = ServicioAgenda.objects.get(pk=servicio_id, activo=True)
    except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
        horas = []
    else:
        profesional = None
        if profesional_id:
            try:
                profesional = int(profesional_id)
            except (TypeError, ValueError):
                horas = []
                form.fields['hora'].choices = [('', 'Selecciona una hora')]
                return horas
        horas = horas_disponibles(
            fecha,
            servicio,
            profesional_id=profesional,
            ignorar_reserva_id=int(ignorar_reserva_id) if ignorar_reserva_id else None,
        )
    form.fields['hora'].choices = [('', 'Selecciona una hora')] + [(hora, hora) for hora in horas]
    return horas


@require_POST
def crear_reserva_manual(request):
    form = ReservaManualForm(request.POST)
    _cargar_opciones_hora(
        form,
        request.POST.get('fecha', ''),
        request.POST.get('servicio', ''),
        request.POST.get('profesional', ''),
    )
    if not form.is_valid():
        messages.error(request, 'No se pudo agendar: ' + ' '.join(
            error for errors in form.errors.values() for error in errors
        ))
        return redirect('admin_agenda')

    reserva = form.save(commit=False)
    servicio = form.cleaned_data['servicio']
    hora = form.cleaned_data['hora']
    fecha = form.cleaned_data['fecha']
    inicio = datetime.combine(fecha, hora)
    reserva.fecha_hora = timezone.make_aware(inicio) if timezone.is_naive(inicio) else inicio
    reserva.servicio = servicio
    reserva.servicio_nombre = servicio.nombre
    reserva.duracion_minutos = servicio.duracion_minutos
    reserva.estado = 'confirmada'
    reserva.origen = 'manual'
    reserva.creada_por = request.user if request.user.is_authenticated else None
    reserva.save()
    messages.success(request, 'La cita presencial se agendó correctamente.')
    return redirect('admin_agenda')


def _destino_dia(fecha):
    return f'{reverse("admin_agenda")}?mes={fecha:%Y-%m}&dia={fecha:%Y-%m-%d}'


def _disponibilidades_del_grupo(fecha, servicio_id, profesional_id):
    return Disponibilidad.objects.filter(
        fecha_especifica=fecha,
        servicio_id=servicio_id,
        profesional_id=profesional_id,
    )


def _intervalos_conflictivos(fecha, servicio, profesional, bloques, grupo_actual=None):
    conflictos = []
    otras_reglas = Disponibilidad.objects.filter(
        fecha_especifica=fecha,
        activo=True,
    ).exclude(
        servicio=servicio,
        profesional=profesional,
    ).select_related('servicio')
    reservas = list(
        Reserva.objects.filter(fecha_hora__date=fecha)
        .exclude(estado__in=['cancelada', 'completada'])
    )
    for bloque in bloques:
        inicio = time.fromisoformat(bloque['inicio'])
        fin = time.fromisoformat(bloque['fin'])
        if any(
            inicio < regla.hora_fin and regla.hora_inicio < fin
            and (
                regla.profesional_id == profesional.pk
                or (regla.profesional_id is None and regla.servicio_id == servicio.pk)
            )
            for regla in otras_reglas
        ):
            conflictos.append(inicio.strftime('%H:%M'))
            continue
        if any(
            _ocupa_mismo_horario(reserva, inicio, fin, servicio.pk, profesional.pk)
            and not (
                grupo_actual is not None
                and reserva.servicio_id == servicio.pk
                and reserva.profesional_id == profesional.pk
                and timezone.localtime(reserva.fecha_hora).time() == inicio
            )
            for reserva in reservas
        ):
            conflictos.append(inicio.strftime('%H:%M'))
    return conflictos


@require_POST
def guardar_disponibilidad_dia(request):
    return _guardar_disponibilidad_dia(request, editar=False)


@require_POST
def editar_disponibilidad_dia(request):
    return _guardar_disponibilidad_dia(request, editar=True)


def _guardar_disponibilidad_dia(request, editar):
    form = DisponibilidadDiaForm(request.POST)
    fecha_texto = request.POST.get('fecha', '')
    try:
        fecha = date.fromisoformat(fecha_texto)
    except ValueError:
        fecha = timezone.localdate()
    destino = _destino_dia(fecha)
    if not form.is_valid():
        errores = ' '.join(error for errors in form.errors.values() for error in errors)
        messages.error(request, 'No se pudo guardar la atención: ' + errores)
        return redirect(destino)

    fecha = form.cleaned_data['fecha']
    servicio = form.cleaned_data['servicio']
    profesional = form.cleaned_data['profesional']
    bloques = form.cleaned_data['bloques']
    grupo = _disponibilidades_del_grupo(fecha, servicio.pk, profesional.pk)
    cambios = CambioDisponibilidadPendiente.objects.filter(
        fecha=fecha,
        servicio=servicio,
        profesional=profesional,
    )
    if cambios.exists():
        messages.error(request, 'No se puede editar mientras haya citas suspendidas esperando respuesta.')
        return redirect(destino)
    if editar and not grupo.exists():
        messages.error(request, 'El registro que intentas editar ya no existe.')
        return redirect(destino)
    if not editar and grupo.exists():
        messages.error(request, 'Ya existe un registro para este servicio y profesional en este día. Usa Editar para cambiarlo.')
        return redirect(destino)

    conflictos = _intervalos_conflictivos(
        fecha,
        servicio,
        profesional,
        bloques,
        grupo_actual=grupo if editar else None,
    )
    if conflictos:
        messages.error(
            request,
            'Hay horarios superpuestos con otra atención o cita: ' + ', '.join(conflictos),
        )
        return redirect(destino)

    actuales = list(grupo)
    horas_nuevas = {time.fromisoformat(bloque['inicio']) for bloque in bloques}
    actuales_por_inicio = {regla.hora_inicio: regla for regla in actuales}
    eliminadas = [
        regla for regla in actuales
        if regla.hora_inicio not in horas_nuevas
    ]
    reservas = list(
        Reserva.objects.filter(
            fecha_hora__date=fecha,
            servicio=servicio,
            profesional=profesional,
        ).exclude(estado__in=['cancelada', 'completada'])
    )
    reservas_eliminadas = {}
    for regla in eliminadas:
        reservas_regla = [
            reserva for reserva in reservas
            if _ocupa_mismo_horario(
                reserva,
                regla.hora_inicio,
                regla.hora_fin,
                servicio.pk,
                profesional.pk,
            )
        ]
        if reservas_regla:
            reservas_eliminadas[regla.pk] = (regla, reservas_regla)
    motivo = form.cleaned_data['motivo_suspension'].strip()
    if reservas_eliminadas and not motivo:
        messages.error(
            request,
            'Indica el motivo para suspender los bloques que tienen citas reservadas.',
        )
        return redirect(destino)

    cambios_creados = []
    with transaction.atomic():
        for regla in eliminadas:
            reservadas = reservas_eliminadas.get(regla.pk)
            if not reservadas:
                regla.delete()
                continue
            cambio = CambioDisponibilidadPendiente.objects.create(
                fecha=fecha,
                servicio=servicio,
                profesional=profesional,
                bloque_inicio=regla.hora_inicio,
                bloque_fin=regla.hora_fin,
                motivo=motivo,
            )
            regla.activo = False
            regla.save(update_fields=['activo'])
            for reserva in reservadas[1]:
                reserva.estado = 'suspendida'
                reserva.motivo_suspension = motivo
                reserva.respuesta_suspension = ''
                reserva.cambio_disponibilidad = cambio
                reserva.save(update_fields=[
                    'estado', 'motivo_suspension', 'respuesta_suspension',
                    'cambio_disponibilidad', 'updated_at',
                ])
                cambios_creados.append((reserva, cambio))

        Disponibilidad.objects.bulk_create([
            Disponibilidad(
                servicio=servicio,
                profesional=profesional,
                fecha_especifica=fecha,
                dia_semana=str(fecha.weekday()),
                hora_inicio=time.fromisoformat(bloque['inicio']),
                hora_fin=time.fromisoformat(bloque['fin']),
                intervalo_minutos=servicio.duracion_minutos,
                activo=True,
            )
            for bloque in bloques
            if time.fromisoformat(bloque['inicio']) not in actuales_por_inicio
        ])
    enviados = fallidos = sin_correo = 0
    if form.cleaned_data['notificar_clientes']:
        for reserva, cambio in cambios_creados:
            resultado = _enviar_aviso_suspension(reserva, cambio, request)
            if resultado is True:
                enviados += 1
            elif resultado is False:
                fallidos += 1
            else:
                sin_correo += 1
    accion = 'actualizó' if editar else 'guardó'
    if cambios_creados:
        messages.warning(
            request,
            f'Se {accion} el registro. Se suspendieron {len(cambios_creados)} cita(s) en los bloques quitados. '
            f'Correos enviados: {enviados}, sin email: {sin_correo}, fallidos: {fallidos}.',
        )
    else:
        messages.success(
            request,
            f'Se {accion} el registro con {len(bloques)} bloque(s) para {profesional.nombre} el {fecha:%d-%m-%Y}.',
        )
    return redirect(destino)


def _limpiar_cambio_si_resuelto(cambio):
    if cambio and not cambio.reservas.filter(estado='suspendida').exists():
        Disponibilidad.objects.filter(
            fecha_especifica=cambio.fecha,
            servicio_id=cambio.servicio_id,
            profesional_id=cambio.profesional_id,
            hora_inicio=cambio.bloque_inicio,
        ).delete()
        cambio.delete()


def _enviar_aviso_suspension(reserva, cambio, request):
    if not reserva.correo_cliente:
        return None
    token = signing.dumps(
        {'cambio': cambio.pk, 'reserva': reserva.pk},
        salt='agenda.respuesta-suspension',
    )
    url = request.build_absolute_uri(
        reverse('responder_suspension', kwargs={'token': token}),
    )
    try:
        send_mail(
            'Necesitamos coordinar tu cita - Nicolett Studio',
            (
                f'Hola {reserva.nombre_cliente}, por motivos de fuerza mayor debemos suspender '
                f'tu cita de {reserva.servicio_nombre} para el {_fecha_texto(reserva)}. '
                f'Motivo: {cambio.motivo}. La cita no se ha cancelado. Ingresa a este enlace '
                f'para cancelar o solicitar que re-agendemos: {url}'
            ),
            getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
            [reserva.correo_cliente],
            fail_silently=False,
        )
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception('No se pudo enviar el aviso de suspensión de la reserva %s.', reserva.pk)
        return False


@require_POST
def eliminar_disponibilidad_grupo(request):
    try:
        fecha = date.fromisoformat(request.POST.get('fecha', ''))
        servicio_id = int(request.POST.get('servicio', ''))
        profesional_id = int(request.POST.get('profesional', ''))
    except (TypeError, ValueError):
        messages.error(request, 'El registro de disponibilidad indicado no es válido.')
        return redirect('admin_agenda')
    destino = _destino_dia(fecha)
    grupo = _disponibilidades_del_grupo(fecha, servicio_id, profesional_id)
    if not grupo.exists():
        messages.error(request, 'El registro de disponibilidad ya no existe.')
        return redirect(destino)
    servicio = get_object_or_404(ServicioAgenda, pk=servicio_id)
    profesional = get_object_or_404(Usuario, pk=profesional_id)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Indica el motivo para quitar este registro.')
        return redirect(destino)
    if CambioDisponibilidadPendiente.objects.filter(
        fecha=fecha,
        servicio=servicio,
        profesional=profesional,
    ).exists():
        messages.error(request, 'Este registro ya está suspendido y espera respuesta de sus clientes.')
        return redirect(destino)

    reservas = list(
        Reserva.objects.filter(
            fecha_hora__date=fecha,
            servicio=servicio,
            profesional=profesional,
        ).exclude(estado__in=['cancelada', 'completada'])
    )
    reglas = list(grupo.order_by('hora_inicio'))
    if not reservas:
        grupo.delete()
        messages.success(request, 'Se eliminó el registro de atenciones.')
        return redirect(destino)

    reservas_por_regla = {}
    asignadas = set()
    for regla in reglas:
        afectadas = [
            reserva for reserva in reservas
            if reserva.pk not in asignadas and _ocupa_mismo_horario(
                reserva,
                regla.hora_inicio,
                regla.hora_fin,
                servicio.pk,
                profesional.pk,
            )
        ]
        if afectadas:
            reservas_por_regla[regla.pk] = (regla, afectadas)
            asignadas.update(reserva.pk for reserva in afectadas)
    if len(asignadas) != len(reservas):
        messages.error(
            request,
            'No se eliminó el registro porque hay citas que no coinciden con sus bloques horarios. Revísalas antes.',
        )
        return redirect(destino)

    cambios_creados = []
    with transaction.atomic():
        for regla in reglas:
            reservadas = reservas_por_regla.get(regla.pk)
            if not reservadas:
                regla.delete()
                continue
            cambio = CambioDisponibilidadPendiente.objects.create(
                fecha=fecha,
                servicio=servicio,
                profesional=profesional,
                bloque_inicio=regla.hora_inicio,
                bloque_fin=regla.hora_fin,
                motivo=motivo,
            )
            regla.activo = False
            regla.save(update_fields=['activo'])
            for reserva in reservadas[1]:
                reserva.estado = 'suspendida'
                reserva.motivo_suspension = motivo
                reserva.respuesta_suspension = ''
                reserva.cambio_disponibilidad = cambio
                reserva.save(update_fields=[
                    'estado', 'motivo_suspension', 'respuesta_suspension',
                    'cambio_disponibilidad', 'updated_at',
                ])
                cambios_creados.append((reserva, cambio))

    if request.POST.get('notificar_clientes') == '1':
        enviados = fallidos = sin_correo = 0
        for reserva, cambio in cambios_creados:
            resultado = _enviar_aviso_suspension(reserva, cambio, request)
            if resultado is True:
                enviados += 1
            elif resultado is False:
                fallidos += 1
            else:
                sin_correo += 1
        messages.warning(
            request,
            f'El horario quedó bloqueado y {len(cambios_creados)} cita(s) suspendidas. '
            f'Correos enviados: {enviados}, sin email: {sin_correo}, fallidos: {fallidos}. '
            'Las disponibilidades se conservarán hasta resolver las citas.',
        )
    else:
        messages.warning(
            request,
            f'El horario quedó bloqueado y {len(cambios_creados)} cita(s) suspendidas. '
            'No se enviaron correos; puedes gestionar las respuestas desde la tabla de citas.',
        )
    return redirect(destino)


@require_GET
def responder_suspension(request, token):
    try:
        datos = signing.loads(token, salt='agenda.respuesta-suspension', max_age=14 * 24 * 60 * 60)
    except signing.BadSignature:
        return render(request, 'agenda/responder_suspension.html', {'error': 'Este enlace no es válido o ya venció.'}, status=400)
    reserva = Reserva.objects.filter(
        pk=datos.get('reserva'),
        cambio_disponibilidad_id=datos.get('cambio'),
        estado='suspendida',
    ).select_related('servicio', 'profesional').first()
    if reserva is None:
        return render(request, 'agenda/responder_suspension.html', {'error': 'Esta cita ya fue resuelta.'}, status=410)
    return render(request, 'agenda/responder_suspension.html', {
        'reserva': reserva,
        'token': token,
    })


@require_POST
def guardar_respuesta_suspension(request, token):
    try:
        datos = signing.loads(token, salt='agenda.respuesta-suspension', max_age=14 * 24 * 60 * 60)
    except signing.BadSignature:
        return render(request, 'agenda/responder_suspension.html', {'error': 'Este enlace no es válido o ya venció.'}, status=400)
    reserva = Reserva.objects.filter(
        pk=datos.get('reserva'),
        cambio_disponibilidad_id=datos.get('cambio'),
        estado='suspendida',
    ).select_related('cambio_disponibilidad').first()
    if reserva is None:
        return render(request, 'agenda/responder_suspension.html', {'error': 'Esta cita ya fue resuelta.'}, status=410)
    accion = request.POST.get('respuesta')
    cambio = reserva.cambio_disponibilidad
    if accion == 'cancelar':
        reserva.estado = 'cancelada'
        reserva.motivo_cancelacion = cambio.motivo
        reserva.respuesta_suspension = 'cancelar'
        reserva.save(update_fields=[
            'estado', 'motivo_cancelacion', 'respuesta_suspension', 'updated_at',
        ])
        _limpiar_cambio_si_resuelto(cambio)
        return render(request, 'agenda/responder_suspension.html', {'completado': 'La cita quedó cancelada.'})
    if accion == 'reagendar':
        reserva.respuesta_suspension = 'reagendar'
        reserva.save(update_fields=['respuesta_suspension', 'updated_at'])
        return render(request, 'agenda/responder_suspension.html', {
            'completado': 'Registramos tu solicitud. La administración se pondrá en contacto para coordinar un nuevo horario.',
        })
    messages.error(request, 'Selecciona si quieres cancelar o solicitar un re-agendamiento.')
    return redirect('responder_suspension', token=token)


@require_POST
def cerrar_dia(request):
    form = CierreDiaForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'No se pudo cerrar el día: ' + ' '.join(
            error for errors in form.errors.values() for error in errors
        ))
        return redirect('admin_agenda')
    fecha = form.cleaned_data['fecha']
    reservas = list(
        Reserva.objects.filter(fecha_hora__date=fecha)
        .exclude(estado__in=['cancelada', 'completada'])
    )
    DiaCerrado.objects.update_or_create(
        fecha=fecha,
        defaults={'motivo': form.cleaned_data['motivo']},
    )
    if reservas:
        messages.warning(
            request,
            f'El día quedó bloqueado para nuevas reservas. Se mantienen {len(reservas)} cita(s) existentes; '
            'gestiónalas individualmente para cancelar o re-agendar.',
        )
    else:
        messages.success(request, 'El día quedó cerrado; no se podrán agendar nuevas citas.')
    return redirect('admin_agenda')


@require_POST
def abrir_dia(request, pk):
    dia = get_object_or_404(DiaCerrado, pk=pk)
    dia.delete()
    messages.success(request, 'El día quedó habilitado de acuerdo con sus reglas de disponibilidad.')
    return redirect('admin_agenda')


@require_POST
def reagendar_cita(request, pk):
    reserva = get_object_or_404(
        Reserva.objects.select_related('servicio', 'cliente', 'profesional'),
        pk=pk,
    )
    if reserva.estado in ['cancelada', 'completada']:
        messages.error(request, 'Esta cita no se puede editar.')
        return redirect('admin_agenda')
    form = ReagendarReservaForm(request.POST)
    _cargar_opciones_hora(
        form,
        request.POST.get('fecha', ''),
        request.POST.get('servicio', ''),
        request.POST.get('profesional', ''),
        reserva.pk,
    )
    if not form.is_valid():
        messages.error(request, 'No se pudo editar la cita: ' + ' '.join(
            error for errors in form.errors.values() for error in errors
        ))
        return redirect('admin_agenda')

    servicio = form.cleaned_data['servicio']
    profesional = form.cleaned_data['profesional']
    nueva_fecha = form.cleaned_data['fecha']
    nueva_hora = form.cleaned_data['hora']
    nueva_fecha_hora = timezone.make_aware(datetime.combine(nueva_fecha, nueva_hora))
    anterior = _fecha_texto(reserva)
    servicio_anterior = reserva.servicio_nombre
    profesional_anterior = _nombre_profesional(reserva.profesional)
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().select_related(
            'cliente',
            'cambio_disponibilidad',
        ).get(pk=pk)
        if reserva.estado in ['cancelada', 'completada']:
            messages.error(request, 'Esta cita ya no se puede editar.')
            return redirect('admin_agenda')
        list(Disponibilidad.objects.select_for_update().filter(
            activo=True,
            fecha_especifica=nueva_fecha,
            servicio=servicio,
            profesional=profesional,
        ))
        if nueva_hora.strftime('%H:%M') not in horas_disponibles(
            nueva_fecha,
            servicio,
            profesional_id=profesional.pk,
            ignorar_reserva_id=reserva.pk,
        ):
            messages.error(
                request,
                'El horario seleccionado ya no está disponible en el calendario. '
                'Elige otra opción.',
            )
            return redirect('admin_agenda')
        cambio_pendiente = reserva.cambio_disponibilidad
        _registrar_historial_reserva(reserva, 'modificada')
        reserva.fecha_hora = nueva_fecha_hora
        reserva.servicio = servicio
        reserva.servicio_nombre = servicio.nombre
        reserva.duracion_minutos = servicio.duracion_minutos
        reserva.profesional = profesional
        if reserva.estado == 'suspendida':
            reserva.estado = 'confirmada'
            reserva.respuesta_suspension = 'reagendar'
            reserva.cambio_disponibilidad = None
            reserva.motivo_suspension = ''
        reserva.save(update_fields=[
            'fecha_hora',
            'servicio',
            'servicio_nombre',
            'duracion_minutos',
            'profesional',
            'estado',
            'respuesta_suspension',
            'cambio_disponibilidad',
            'motivo_suspension',
            'updated_at',
        ])
    _limpiar_cambio_si_resuelto(cambio_pendiente)
    if reserva.cliente_id and reserva.cliente.email:
        try:
            send_mail(
                'Aviso de cambio en tu cita - Nicolett Studio',
                (
                    f'Hola {reserva.nombre_cliente}, tu cita fue modificada.\n'
                    f'Servicio anterior: {servicio_anterior}.\n'
                    f'Nuevo servicio: {reserva.servicio_nombre}.\n'
                    f'Horario anterior: {anterior}.\n'
                    f'Nuevo horario: {_fecha_texto(reserva)}.\n'
                    f'Profesional anterior: {profesional_anterior}.\n'
                    f'Nuevo profesional: {_nombre_profesional(reserva.profesional)}.'
                ),
                getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
                [reserva.cliente.email],
                fail_silently=False,
            )
        except (OSError, smtplib.SMTPException):
            logger.exception('No se pudo enviar el aviso de edición de la reserva %s.', reserva.pk)
            messages.warning(request, 'La cita se modificó, pero no se pudo enviar el aviso por correo.')
        else:
            messages.success(request, 'La cita se modificó y se notificó al cliente por correo.')
    else:
        messages.success(request, 'La cita se modificó correctamente.')
    return redirect('admin_agenda')


def _nombre_profesional(profesional):
    return ' '.join(
        parte for parte in (
            profesional.nombre,
            profesional.segundo_nombre,
            profesional.apellido_paterno,
            profesional.apellido_materno,
        ) if parte
    ) if profesional else 'Sin asignar'


@require_POST
def cancelar_cita(request, pk):
    reserva = get_object_or_404(Reserva.objects.select_related('cambio_disponibilidad'), pk=pk)
    if reserva.estado in ['cancelada', 'completada']:
        messages.error(request, 'La cita ya no está pendiente y no se puede cancelar.')
        return redirect('admin_agenda')
    form = CancelarReservaForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Indica un motivo para cancelar la cita.')
        return redirect('admin_agenda')
    cambio_pendiente = reserva.cambio_disponibilidad
    _registrar_historial_reserva(reserva, 'cancelada', form.cleaned_data['motivo'])
    reserva.estado = 'cancelada'
    reserva.motivo_cancelacion = form.cleaned_data['motivo']
    reserva.cambio_disponibilidad = None
    reserva.save(update_fields=[
        'estado', 'motivo_cancelacion', 'cambio_disponibilidad', 'updated_at',
    ])
    _limpiar_cambio_si_resuelto(cambio_pendiente)
    resultado_aviso = _enviar_aviso_cancelacion(reserva, reserva.motivo_cancelacion)
    if resultado_aviso is True:
        messages.success(request, 'La cita se canceló y se envió el aviso por correo.')
    elif resultado_aviso is False:
        messages.warning(request, 'La cita se canceló, pero ocurrió un error al enviar el correo de aviso.')
    else:
        messages.warning(request, 'La cita se canceló; no hay un correo de contacto registrado.')
    return redirect('admin_agenda')
