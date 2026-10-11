import logging
import smtplib
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from agenda.models import Reserva
from .models import Configuracion, RecordatorioEnviado

logger = logging.getLogger(__name__)

HORAS_CITA_KEY = 'recordatorios_horas_antes'
DIAS_SEGUIMIENTO_KEY = 'recordatorios_dias_despues'
HORAS_CITA_DEFAULT = [48, 24]
DIAS_SEGUIMIENTO_DEFAULT = [30, 15]
VENTANA_ENVIO = timedelta(hours=24)


def _obtener_intervalos(clave, predeterminados):
    configuracion = Configuracion.objects.filter(clave=clave).first()
    if configuracion is None:
        return predeterminados
    try:
        valores = [int(item) for item in configuracion.valor.split(',')]
    except ValueError:
        logger.error('La configuración de recordatorios %s no contiene intervalos válidos.', clave)
        raise ValueError(f'La configuración de recordatorios {clave} no es válida.')
    if not valores or any(valor < 1 for valor in valores):
        logger.error('La configuración de recordatorios %s no contiene intervalos positivos.', clave)
        raise ValueError(f'La configuración de recordatorios {clave} no es válida.')
    return sorted(set(valores), reverse=True)


def obtener_configuracion_recordatorios():
    horas_cita = _obtener_intervalos(HORAS_CITA_KEY, HORAS_CITA_DEFAULT)
    dias_seguimiento = _obtener_intervalos(
        DIAS_SEGUIMIENTO_KEY,
        DIAS_SEGUIMIENTO_DEFAULT,
    )
    return horas_cita, dias_seguimiento


def guardar_configuracion_recordatorios(horas_cita, dias_seguimiento):
    valores = (
        (
            HORAS_CITA_KEY,
            horas_cita,
            'Horas antes de una cita para enviar recordatorios.',
        ),
        (
            DIAS_SEGUIMIENTO_KEY,
            dias_seguimiento,
            'Días después de una atención para enviar recordatorios de seguimiento.',
        ),
    )
    for clave, intervalos, descripcion in valores:
        Configuracion.objects.update_or_create(
            clave=clave,
            defaults={
                'valor': ','.join(str(intervalo) for intervalo in intervalos),
                'descripcion': descripcion,
            },
        )


def listar_recordatorios_pendientes(ahora=None):
    ahora = ahora or timezone.now()
    horas_cita, dias_seguimiento = obtener_configuracion_recordatorios()
    tareas = []

    reservas_proximas = Reserva.objects.select_related(
        'cliente', 'servicio', 'profesional',
    ).filter(
        fecha_hora__gt=ahora,
        fecha_hora__lte=ahora + timedelta(hours=max(horas_cita)) + VENTANA_ENVIO,
        estado__in=['pendiente', 'confirmada'],
    )
    for reserva in reservas_proximas:
        for desfase in horas_cita:
            programado = reserva.fecha_hora - timedelta(hours=desfase)
            if programado < ahora - VENTANA_ENVIO:
                continue
            if RecordatorioEnviado.objects.filter(
                reserva=reserva,
                tipo='cita',
                desfase=desfase,
            ).exists():
                continue
            tareas.append({
                'reserva': reserva,
                'tipo': 'cita',
                'desfase': desfase,
                'programado': programado,
                'vencido': programado <= ahora,
                'unidad': 'horas',
            })

    visitas_completadas = Reserva.objects.select_related(
        'cliente', 'servicio',
    ).filter(
        estado='completada',
        fecha_hora__gte=ahora - timedelta(days=max(dias_seguimiento)) - VENTANA_ENVIO,
        fecha_hora__lte=ahora,
    )
    for reserva in visitas_completadas:
        for desfase in dias_seguimiento:
            programado = reserva.fecha_hora + timedelta(days=desfase)
            if programado > ahora + timedelta(days=max(dias_seguimiento)):
                continue
            if programado < ahora - VENTANA_ENVIO:
                continue
            if RecordatorioEnviado.objects.filter(
                reserva=reserva,
                tipo='seguimiento',
                desfase=desfase,
            ).exists():
                continue
            tareas.append({
                'reserva': reserva,
                'tipo': 'seguimiento',
                'desfase': desfase,
                'programado': programado,
                'vencido': programado <= ahora,
                'unidad': 'días',
            })

    return sorted(tareas, key=lambda tarea: tarea['programado'])


def enviar_recordatorio(tarea, ahora=None):
    ahora = ahora or timezone.now()
    reserva = tarea['reserva']
    tipo = tarea['tipo']
    desfase = tarea['desfase']
    programado = tarea['programado']

    if tipo not in {'cita', 'seguimiento'}:
        raise ValueError('El tipo de recordatorio no es válido.')
    if programado > ahora or programado < ahora - VENTANA_ENVIO:
        raise ValueError('El recordatorio aún no está dentro de su ventana de envío.')
    if not reserva.correo_cliente:
        raise ValueError('La cita no tiene correo electrónico registrado.')
    if RecordatorioEnviado.objects.filter(
        reserva=reserva,
        tipo=tipo,
        desfase=desfase,
    ).exists():
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
        asunto = '¿Agendamos tu próxima atención? - Nicolett Studio'
        mensaje = (
            f'Hola {reserva.nombre_cliente}, han pasado {desfase} días desde tu atención de '
            f'{reserva.servicio_nombre or reserva.servicio or "servicio"}. '
            'Si deseas continuar tu tratamiento o realizar retoques, estaremos felices '
            'de ayudarte a agendar una nueva cita.'
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
