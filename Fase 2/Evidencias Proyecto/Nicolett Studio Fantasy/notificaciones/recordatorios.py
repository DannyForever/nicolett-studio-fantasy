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


def construir_mensaje_recordatorio(reserva, tipo):
    nombre = reserva.nombre_cliente or 'Hola'
    servicio = reserva.servicio_nombre or (
        reserva.servicio.nombre if reserva.servicio_id else 'tu servicio'
    )
    profesional = ' '.join(
        parte for parte in (
            reserva.profesional.nombre if reserva.profesional_id else '',
            reserva.profesional.apellido_paterno if reserva.profesional_id else '',
            reserva.profesional.apellido_materno if reserva.profesional_id else '',
        ) if parte
    ) or 'por confirmar'
    fecha_cita = timezone.localtime(reserva.fecha_hora)
    if tipo == 'cita':
        return (
            f'Hola {nombre} 😊, te recordamos tu cita en Nicolett Studio ✨\n\n'
            f'💅 Servicio: {servicio}\n'
            f'📅 Día: {fecha_cita:%d-%m-%Y}\n'
            f'🕒 Hora: {fecha_cita:%H:%M}\n'
            f'👩‍🎨 Profesional: {profesional}\n'
            f'👭 ¿Vienes con acompañante?: {"Sí" if reserva.viene_con_acompanante else "No"}\n\n'
            '¡Te esperamos! 💖'
        )
    if tipo == 'seguimiento':
        return (
            f'Hola {nombre} 😊, gracias por preferir Nicolett Studio ✨\n\n'
            f'💅 Servicio realizado: {servicio}\n'
            f'📅 Día de atención: {fecha_cita:%d-%m-%Y}\n'
            f'🕒 Hora de atención: {fecha_cita:%H:%M}\n'
            f'👩‍🎨 Profesional: {profesional}\n'
            f'👭 ¿Viniste con acompañante?: {"Sí" if reserva.viene_con_acompanante else "No"}\n\n'
            '¿Te gustaría agendar nuevamente este servicio o continuar con tu atención? '
            'Escríbenos y con gusto coordinamos tu próxima visita 💖'
        )
    raise ValueError('El tipo de recordatorio no es válido.')


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
    else:
        if reserva.estado != 'completada':
            raise ValueError('La atención no está marcada como completada.')
        asunto = '¿Qué tal estuvo tu atención? - Nicolett Studio'
    mensaje = construir_mensaje_recordatorio(reserva, tipo)

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
        if not tarea['reserva'].correo_cliente:
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
