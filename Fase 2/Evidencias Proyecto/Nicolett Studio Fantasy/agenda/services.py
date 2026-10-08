import logging
import smtplib

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Disponibilidad, Reserva

logger = logging.getLogger(__name__)


def reservas_activas_futuras(servicio_id):
    return Reserva.objects.filter(
        servicio_id=servicio_id,
        fecha_hora__gte=timezone.now(),
    ).exclude(estado__in=['cancelada', 'completada'])


def desactivar_servicio_y_cancelar_citas(servicio_id, motivo):
    citas = list(reservas_activas_futuras(servicio_id).select_related('cliente'))
    Disponibilidad.objects.filter(servicio_id=servicio_id).delete()
    correos_enviados = 0
    sin_correo = 0
    correos_fallidos = 0
    for cita in citas:
        cita.estado = 'cancelada'
        cita.motivo_cancelacion = motivo
        cita.save(update_fields=['estado', 'motivo_cancelacion', 'updated_at'])
        destinatario = cita.correo_cliente
        if not destinatario:
            sin_correo += 1
            continue
        try:
            fecha = timezone.localtime(cita.fecha_hora).strftime('%d-%m-%Y a las %H:%M')
            send_mail(
                'Aviso importante sobre tu cita - Nicolett Studio',
                (
                    f'Hola {cita.nombre_cliente}, te informamos que tu cita de {cita.servicio_nombre} '
                    f'para el {fecha} fue cancelada porque el servicio ya no está disponible. '
                    f'Motivo: {motivo}. Contáctanos para coordinar una alternativa.'
                ),
                getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
                [destinatario],
                fail_silently=False,
            )
            correos_enviados += 1
        except (OSError, smtplib.SMTPException):
            logger.exception('No se pudo notificar al cliente de la reserva %s.', cita.pk)
            correos_fallidos += 1
    return len(citas), correos_enviados, sin_correo, correos_fallidos
