import logging
import smtplib
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from agenda.models import Reserva
from .models import ProgramacionRecordatorio, RecordatorioEnviado

logger = logging.getLogger(__name__)

HORAS_CITA_DEFAULT = [48, 24]
HORAS_SEGUIMIENTO_DEFAULT = 24


def obtener_configuracion_recordatorios():
    return HORAS_CITA_DEFAULT.copy(), HORAS_SEGUIMIENTO_DEFAULT


def _crear_tarea(reserva, tipo, desfase, programado, programacion=None, ahora=None):
    ahora = ahora or timezone.now()
    fecha_programada = programacion.programado_para if programacion else programado
    return {
        'reserva': reserva,
        'tipo': tipo,
        'desfase': desfase,
        'programado': fecha_programada,
        'programacion': programacion,
        'personalizado': programacion is not None,
        'vencido': fecha_programada <= ahora,
    }


def listar_recordatorios_pendientes(ahora=None):
    ahora = ahora or timezone.now()
    horas_cita, horas_seguimiento = obtener_configuracion_recordatorios()
    tareas = []

    reservas_proximas = Reserva.objects.select_related(
        'cliente', 'servicio', 'profesional',
    ).filter(
        fecha_hora__gt=ahora,
        estado__in=['pendiente', 'confirmada'],
    )
    for reserva in reservas_proximas:
        for desfase in horas_cita:
            programado = reserva.fecha_hora - timedelta(hours=desfase)
            programacion = ProgramacionRecordatorio.objects.filter(
                reserva=reserva,
                tipo='cita',
                desfase=desfase,
                fecha_hora_cita=reserva.fecha_hora,
            ).first()
            if programacion and programacion.enviado_en:
                continue
            if RecordatorioEnviado.objects.filter(
                reserva=reserva,
                tipo='cita',
                desfase=desfase,
                fecha_hora_cita=reserva.fecha_hora,
            ).exists():
                continue
            tareas.append(_crear_tarea(reserva, 'cita', desfase, programado, programacion, ahora))

    visitas_completadas = Reserva.objects.select_related('cliente', 'servicio').filter(
        estado='completada',
        fecha_hora__lte=ahora,
    )
    for reserva in visitas_completadas:
        if RecordatorioEnviado.objects.filter(
            reserva=reserva,
            tipo='seguimiento',
        ).exists():
            continue
        programacion = ProgramacionRecordatorio.objects.filter(
            reserva=reserva,
            tipo='seguimiento',
            desfase=horas_seguimiento,
            fecha_hora_cita=reserva.fecha_hora,
        ).first()
        if programacion and programacion.enviado_en:
            continue
        programado = (
            reserva.fecha_hora
            + timedelta(minutes=reserva.duracion_minutos)
            + timedelta(hours=horas_seguimiento)
        )
        tareas.append(
            _crear_tarea(
                reserva,
                'seguimiento',
                horas_seguimiento,
                programado,
                programacion,
                ahora,
            ),
        )

    return sorted(tareas, key=lambda tarea: tarea['programado'])


def enviar_recordatorio(tarea, ahora=None):
    ahora = ahora or timezone.now()
    reserva = tarea['reserva']
    tipo = tarea['tipo']
    desfase = tarea['desfase']
    programado = tarea['programado']

    if tipo not in {'cita', 'seguimiento'}:
        raise ValueError('El tipo de recordatorio no es válido.')
    if programado > ahora:
        raise ValueError('El recordatorio aún no está dentro de su ventana de envío.')
    if not reserva.correo_cliente:
        raise ValueError('La cita no tiene correo electrónico registrado.')
    envios_anteriores = RecordatorioEnviado.objects.filter(
        reserva=reserva,
        tipo=tipo,
    )
    if tipo == 'cita':
        envios_anteriores = envios_anteriores.filter(
            desfase=desfase,
            fecha_hora_cita=reserva.fecha_hora,
        )
    if envios_anteriores.exists():
        return False

    if tipo == 'cita':
        if reserva.estado not in {'pendiente', 'confirmada'} or reserva.fecha_hora <= ahora:
            raise ValueError('La cita ya no califica para el recordatorio.')
        asunto = 'Recordatorio de tu próxima cita - Nicolett Studio'
        mensaje = (
            f'Hola {reserva.nombre_cliente}, te recordamos tu cita de '
            f'{reserva.servicio_nombre or reserva.servicio or "servicio"} para el '
            f'{timezone.localtime(reserva.fecha_hora):%d-%m-%Y a las %H:%M}. '
            '¡Te esperamos en Nicolett Studio!'
        )
    else:
        if reserva.estado != 'completada':
            raise ValueError('La atención no está marcada como completada.')
        asunto = '¿Qué tal estuvo tu atención? - Nicolett Studio'
        mensaje = (
            f'Hola {reserva.nombre_cliente}, queremos saber cómo estuvo tu atención de '
            f'{reserva.servicio_nombre or reserva.servicio or "servicio"}. '
            'Gracias por preferir Nicolett Studio. Nos encantará conocer tu opinión.'
        )

    enviado = send_mail(
        asunto,
        mensaje,
        getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
        [reserva.correo_cliente],
        fail_silently=False,
    )
    if enviado != 1:
        raise RuntimeError('El sistema de correo no confirmó el envío del recordatorio.')

    RecordatorioEnviado.objects.create(
        reserva=reserva,
        tipo=tipo,
        desfase=desfase,
        fecha_hora_cita=reserva.fecha_hora if tipo == 'cita' else None,
        email=reserva.correo_cliente,
    )
    return True


def enviar_recordatorios_vencidos():
    enviados = 0
    fallidos = 0
    for tarea in listar_recordatorios_pendientes():
        if not tarea['vencido']:
            continue
        try:
            if enviar_recordatorio(tarea):
                programacion = tarea.get('programacion')
                if programacion:
                    programacion.enviado_en = timezone.now()
                    programacion.save(update_fields=['enviado_en'])
                enviados += 1
        except (OSError, smtplib.SMTPException, RuntimeError, ValueError):
            fallidos += 1
            logger.exception(
                'No se pudo enviar el recordatorio de tipo %s, desfase %s, reserva %s.',
                tarea['tipo'],
                tarea['desfase'],
                tarea['reserva'].pk,
            )
    return enviados, fallidos
