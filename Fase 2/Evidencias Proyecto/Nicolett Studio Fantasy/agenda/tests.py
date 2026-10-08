import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from panel_admin.models import Categoria, Servicio
from usuarios.models import Rol, Usuario
from .models import (
    CambioDisponibilidadPendiente,
    Disponibilidad,
    DiaCerrado,
    ProfesionalCategoria,
    Reserva,
)
from .views import horas_disponibles


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AgendaTests(TestCase):
    def setUp(self):
        administrador = Usuario.objects.create_superuser(
            email='admin@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Admin',
            apellido_materno='Test',
            telefono='+56912345678',
        )
        self.client.force_login(administrador)
        self.categoria = Categoria.objects.create(nombre='Uñas', tipo='Manicure')
        self.servicio = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria,
            duracion_minutos=60,
            precio='12000',
            activo=True,
        )
        rol_colaborador = Rol.objects.create(id=5, nombre='Colaborador')
        self.profesional = Usuario(
            nombre='Juan',
            segundo_nombre='',
            apellido_paterno='Pérez',
            apellido_materno='Soto',
            telefono='+56912345678',
            email='juan.agenda@example.com',
            rol=rol_colaborador,
        )
        self.profesional.set_unusable_password()
        self.profesional.save()
        ProfesionalCategoria.objects.create(
            profesional=self.profesional,
            categoria_id=self.categoria.pk,
        )
        self.fecha = timezone.localdate() + timedelta(days=1)
        while self.fecha.weekday() != 1:
            self.fecha += timedelta(days=1)

    def crear_bloque(self, inicio, fin=None, fecha=None, servicio=None, profesional=None, activo=True):
        inicio_time = datetime.strptime(inicio, '%H:%M').time()
        if fin is None:
            fin = (
                datetime.combine(self.fecha, inicio_time)
                + timedelta(minutes=(servicio or self.servicio).duracion_minutos)
            ).strftime('%H:%M')
        return Disponibilidad.objects.create(
            servicio_id=(servicio or self.servicio).pk,
            profesional=profesional or self.profesional,
            fecha_especifica=fecha or self.fecha,
            dia_semana=str((fecha or self.fecha).weekday()),
            hora_inicio=inicio_time,
            hora_fin=datetime.strptime(fin, '%H:%M').time(),
            intervalo_minutos=(servicio or self.servicio).duracion_minutos,
            activo=activo,
        )

    def crear_reserva(self, hora='09:00', correo='clienta@example.com'):
        return Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(self.fecha, datetime.strptime(hora, '%H:%M').time())),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente_nombre='Camila Pérez',
            cliente_email=correo,
            estado='confirmada',
            origen='manual',
        )

    def post_bloques(self, bloques, **extra):
        data = {
            'fecha': self.fecha.isoformat(),
            'servicio': str(self.servicio.pk),
            'profesional': str(self.profesional.pk),
            'bloques': json.dumps(bloques),
        }
        data.update(extra)
        return self.client.post(reverse('guardar_disponibilidad_dia'), data)

    def test_admin_calendar_removes_horizon_and_weekly_configuration(self):
        response = self.client.get(reverse('admin_agenda'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Calendario de disponibilidad')
        self.assertContains(response, 'Añadir bloque horario')
        self.assertNotContains(response, 'Horizonte de agenda')
        self.assertNotContains(response, 'Configuración semanal avanzada')
        self.assertNotContains(response, 'Meses disponibles para agendar')

    def test_calendar_can_navigate_to_past_months_for_read_only(self):
        mes_pasado = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
        response = self.client.get(
            reverse('admin_agenda'),
            {'mes': mes_pasado.strftime('%Y-%m'), 'dia': mes_pasado.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['calendario_mes']['label'].endswith(str(mes_pasado.year)))
        self.assertFalse(response.context['fecha_configurable'])
        self.assertContains(response, 'día es solo de consulta')

    def test_saves_multiple_individual_slots_using_service_duration(self):
        response = self.post_bloques([
            {'inicio': '08:00', 'fin': '09:00'},
            {'inicio': '10:00', 'fin': '11:00'},
        ])

        self.assertRedirects(
            response,
            f'{reverse("admin_agenda")}?mes={self.fecha:%Y-%m}&dia={self.fecha:%Y-%m-%d}',
        )
        reglas = Disponibilidad.objects.filter(fecha_especifica=self.fecha).order_by('hora_inicio')
        self.assertEqual(
            list(reglas.values_list('hora_inicio', 'hora_fin')),
            [
                (datetime.strptime('08:00', '%H:%M').time(), datetime.strptime('09:00', '%H:%M').time()),
                (datetime.strptime('10:00', '%H:%M').time(), datetime.strptime('11:00', '%H:%M').time()),
            ],
        )
        self.assertEqual(horas_disponibles(self.fecha, self.servicio, self.profesional.pk), ['08:00', '10:00'])

    def test_rejects_blocks_that_do_not_match_service_duration_or_overlap(self):
        self.post_bloques([{'inicio': '08:00', 'fin': '09:30'}])
        self.assertFalse(Disponibilidad.objects.exists())

        self.post_bloques([
            {'inicio': '08:00', 'fin': '09:00'},
            {'inicio': '08:30', 'fin': '09:30'},
        ])
        self.assertFalse(Disponibilidad.objects.exists())

    def test_edit_group_replaces_slots_but_cannot_remove_booked_slot(self):
        self.crear_bloque('08:00')
        self.crear_bloque('10:00')
        edit_url = reverse('editar_disponibilidad_dia')
        data = {
            'fecha': self.fecha.isoformat(),
            'servicio': str(self.servicio.pk),
            'profesional': str(self.profesional.pk),
            'grupo_servicio': str(self.servicio.pk),
            'grupo_profesional': str(self.profesional.pk),
            'bloques': '[{"inicio":"09:00","fin":"10:00"}]',
        }
        response = self.client.post(edit_url, data)
        self.assertRedirects(
            response,
            f'{reverse("admin_agenda")}?mes={self.fecha:%Y-%m}&dia={self.fecha:%Y-%m-%d}',
        )
        self.assertEqual(list(Disponibilidad.objects.values_list('hora_inicio', flat=True)), [
            datetime.strptime('09:00', '%H:%M').time(),
        ])
        self.crear_reserva('09:00')
        data['bloques'] = '[{"inicio":"10:00","fin":"11:00"}]'
        self.client.post(edit_url, data)
        self.assertEqual(list(Disponibilidad.objects.values_list('hora_inicio', flat=True)), [
            datetime.strptime('09:00', '%H:%M').time(),
        ])

    def test_editing_group_can_suspend_only_removed_booked_block(self):
        self.crear_bloque('08:00')
        self.crear_bloque('10:00')
        reserva = self.crear_reserva('08:00')
        response = self.client.post(reverse('editar_disponibilidad_dia'), {
            'fecha': self.fecha.isoformat(),
            'servicio': str(self.servicio.pk),
            'profesional': str(self.profesional.pk),
            'grupo_servicio': str(self.servicio.pk),
            'grupo_profesional': str(self.profesional.pk),
            'bloques': '[{"inicio":"10:00","fin":"11:00"}]',
            'motivo_suspension': 'El profesional debe retirarse antes',
            'notificar_clientes': '1',
        })

        self.assertEqual(response.status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'suspendida')
        self.assertTrue(Disponibilidad.objects.filter(hora_inicio='08:00', activo=False).exists())
        self.assertTrue(Disponibilidad.objects.filter(hora_inicio='10:00', activo=True).exists())
        self.assertEqual(horas_disponibles(self.fecha, self.servicio, self.profesional.pk), ['10:00'])
        self.assertEqual(len(mail.outbox), 1)

    def test_professional_specific_slots_are_returned_and_reserved_slots_removed(self):
        self.crear_bloque('09:00')
        self.crear_bloque('10:00')
        self.assertEqual(horas_disponibles(self.fecha, self.servicio, self.profesional.pk), ['09:00', '10:00'])
        self.crear_reserva('09:00')
        self.assertEqual(horas_disponibles(self.fecha, self.servicio, self.profesional.pk), ['10:00'])

    def test_manual_reservation_uses_an_available_slot(self):
        self.crear_bloque('09:00')
        response = self.client.post(
            reverse('crear_reserva_manual'),
            {
                'cliente_nombre': 'Camila Pérez',
                'cliente_email': 'camila@example.com',
                'servicio': self.servicio.pk,
                'fecha': self.fecha.isoformat(),
                'hora': '09:00',
                'profesional': self.profesional.pk,
            },
        )

        self.assertRedirects(response, reverse('admin_agenda'))
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.estado, 'confirmada')
        self.assertEqual(reserva.profesional_id, self.profesional.pk)

    def test_blocking_day_keeps_existing_bookings_but_prevents_new_ones(self):
        self.crear_bloque('09:00')
        reserva = self.crear_reserva('09:00')
        response = self.client.post(reverse('cerrar_dia'), {
            'fecha': self.fecha.isoformat(),
            'motivo': 'Festivo',
        })

        self.assertRedirects(response, reverse('admin_agenda'))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'confirmada')
        self.assertTrue(DiaCerrado.objects.filter(fecha=self.fecha).exists())
        self.assertEqual(horas_disponibles(self.fecha, self.servicio, self.profesional.pk), [])

    def test_deleting_group_without_bookings_deletes_availability(self):
        self.crear_bloque('09:00')
        response = self.client.post(reverse('eliminar_disponibilidad_grupo'), {
            'fecha': self.fecha.isoformat(),
            'servicio': self.servicio.pk,
            'profesional': self.profesional.pk,
            'motivo': 'Cambio de horario',
            'notificar_clientes': '1',
        })

        self.assertRedirects(
            response,
            f'{reverse("admin_agenda")}?mes={self.fecha:%Y-%m}&dia={self.fecha:%Y-%m-%d}',
        )
        self.assertFalse(Disponibilidad.objects.exists())
        self.assertFalse(CambioDisponibilidadPendiente.objects.exists())

    def test_deleting_group_suspends_bookings_blocks_new_slots_and_emails_options(self):
        self.crear_bloque('09:00')
        self.crear_bloque('10:00')
        reserva = self.crear_reserva('09:00')
        response = self.client.post(reverse('eliminar_disponibilidad_grupo'), {
            'fecha': self.fecha.isoformat(),
            'servicio': self.servicio.pk,
            'profesional': self.profesional.pk,
            'motivo': 'Profesional ausente por fuerza mayor',
            'notificar_clientes': '1',
        })

        self.assertEqual(response.status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'suspendida')
        self.assertTrue(Disponibilidad.objects.filter(activo=False).exists())
        self.assertEqual(Disponibilidad.objects.count(), 1)
        self.assertEqual(horas_disponibles(self.fecha, self.servicio, self.profesional.pk), [])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('cancelar o solicitar', mail.outbox[0].body)

        path = urlparse(re.search(r'https?://\S+', mail.outbox[0].body).group(0)).path
        token = path.rstrip('/').split('/')[-1]
        page = self.client.get(reverse('responder_suspension', args=[token]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Solicitar re-agendamiento')

        response = self.client.post(reverse('guardar_respuesta_suspension', args=[token]), {
            'respuesta': 'cancelar',
        })
        self.assertEqual(response.status_code, 200)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'cancelada')
        self.assertFalse(CambioDisponibilidadPendiente.objects.exists())
        self.assertFalse(Disponibilidad.objects.exists())

    def test_client_can_request_reschedule_and_booking_stays_suspended_until_admin_acts(self):
        self.crear_bloque('09:00')
        reserva = self.crear_reserva('09:00')
        self.client.post(reverse('eliminar_disponibilidad_grupo'), {
            'fecha': self.fecha.isoformat(),
            'servicio': self.servicio.pk,
            'profesional': self.profesional.pk,
            'motivo': 'Imprevisto del profesional',
            'notificar_clientes': '1',
        })
        token = urlparse(re.search(r'https?://\S+', mail.outbox[0].body).group(0)).path.rstrip('/').split('/')[-1]
        self.client.post(reverse('guardar_respuesta_suspension', args=[token]), {
            'respuesta': 'reagendar',
        })
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'suspendida')
        self.assertEqual(reserva.respuesta_suspension, 'reagendar')
        self.assertTrue(CambioDisponibilidadPendiente.objects.exists())

    def test_reschedule_suspended_booking_clears_pending_group(self):
        self.crear_bloque('09:00')
        self.crear_bloque('10:00')
        reserva = self.crear_reserva('09:00')
        self.client.post(reverse('eliminar_disponibilidad_grupo'), {
            'fecha': self.fecha.isoformat(),
            'servicio': self.servicio.pk,
            'profesional': self.profesional.pk,
            'motivo': 'Fuerza mayor',
        })
        nueva_fecha = self.fecha + timedelta(days=7)
        self.crear_bloque('09:00', fecha=nueva_fecha)
        response = self.client.post(reverse('reagendar_cita', args=[reserva.pk]), {
            'fecha': nueva_fecha.isoformat(),
            'hora': '09:00',
        })

        self.assertRedirects(response, reverse('admin_agenda'))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'confirmada')
        self.assertIsNone(reserva.cambio_disponibilidad_id)
        self.assertFalse(CambioDisponibilidadPendiente.objects.exists())
        self.assertFalse(Disponibilidad.objects.filter(fecha_especifica=self.fecha).exists())

    def test_no_horizon_limits_future_availability(self):
        fecha_futura = self.fecha + timedelta(days=365)
        response = self.client.post(reverse('guardar_disponibilidad_dia'), {
            'fecha': fecha_futura.isoformat(),
            'servicio': str(self.servicio.pk),
            'profesional': str(self.profesional.pk),
            'bloques': '[{"inicio":"08:00","fin":"09:00"}]',
        })

        self.assertRedirects(
            response,
            f'{reverse("admin_agenda")}?mes={fecha_futura:%Y-%m}&dia={fecha_futura:%Y-%m-%d}',
        )
        self.assertTrue(Disponibilidad.objects.filter(fecha_especifica=fecha_futura).exists())
