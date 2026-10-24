import json
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlparse

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from carrito.models import DetallePedido, Pedido
from panel_admin.models import Categoria, Servicio
from usuarios.models import Rol, Usuario
from .models import (
    CambioDisponibilidadPendiente,
    Disponibilidad,
    DiaCerrado,
    HistorialReserva,
    ProfesionalCategoria,
    Reserva,
    ReservaCitaTemporal,
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
            email='jp.soto@nicolettstudio.cl',
            rol=rol_colaborador,
        )
        self.profesional.set_unusable_password()
        self.profesional.save()
        ProfesionalCategoria.objects.create(
            profesional=self.profesional,
            categoria_id=self.categoria.pk,
        )
        self.fecha = timezone.localdate() + timedelta(days=14)
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

    def crear_cliente(self):
        rol_cliente, _ = Rol.objects.get_or_create(nombre='Cliente')
        return Usuario.objects.create_user(
            email='cliente.agenda@example.com',
            password='Cliente123!Test',
            nombre='Camila',
            apellido_paterno='Prueba',
            apellido_materno='Cliente',
            telefono='+56987654321',
            rol=rol_cliente,
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
        self.assertContains(response, f'value="{self.servicio.pk}"')
        self.assertEqual(
            [item['id'] for item in self.client.get(
                reverse('agenda_profesionales_por_servicio'),
                {'servicio': self.servicio.pk},
            ).json()['professionals']],
            [self.profesional.pk],
        )
        self.assertContains(response, 'Calendario de disponibilidad')
        self.assertContains(response, 'Horas disponibles')
        self.assertNotContains(response, 'Ir a Citas')
        self.assertNotContains(response, 'Quedan horas disponibles')
        self.assertContains(response, 'Añadir bloque horario')
        self.assertNotContains(response, 'Horizonte de agenda')
        self.assertNotContains(response, 'Configuración semanal avanzada')
        self.assertNotContains(response, 'Meses disponibles para agendar')
        self.assertNotContains(response, 'Ver ficha técnica')
        self.assertNotContains(response, 'No hay citas para mostrar.')
        self.assertNotContains(response, 'Agendar cita presencial')

    def test_admin_calendar_explains_enabled_services_and_closed_day_reason(self):
        self.crear_bloque('09:00')
        closed_date = self.fecha + timedelta(days=1)
        if closed_date.month != self.fecha.month:
            closed_date -= timedelta(days=2)
        DiaCerrado.objects.create(fecha=closed_date, motivo='Feriado regional')

        response = self.client.get(
            reverse('admin_agenda'),
            {'mes': self.fecha.strftime('%Y-%m'), 'dia': self.fecha.isoformat()},
        )

        days = {
            day['date']: day
            for week in response.context['calendario_mes']['weeks']
            for day in week
        }
        self.assertIn('Manicure', days[self.fecha]['tooltip'])
        self.assertIn('Feriado regional', days[closed_date]['tooltip'])
        self.assertContains(response, 'Servicios habilitados: Manicure')
        self.assertContains(response, 'Día no disponible: Feriado regional')

    def test_admin_citas_page_contains_reservation_management_and_day_filter(self):
        reserva = self.crear_reserva()

        response = self.client.get(reverse('admin_citas'), {'fecha': self.fecha.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Citas')
        self.assertContains(response, 'filtroProfesional')
        self.assertContains(response, '<th>Profesional</th>', html=True)
        self.assertContains(response, 'Camila Pérez')
        self.assertContains(response, 'Ver ficha técnica')
        self.assertContains(response, 'Agendar cita presencial')
        self.assertContains(response, 'Agendada por personal')
        self.assertNotContains(response, 'Las reservas de clientes también aparecerán aquí.')
        profesionales = self.client.get(
            reverse('agenda_profesionales_por_servicio'),
            {'servicio': self.servicio.pk},
        ).json()['professionals']
        self.assertEqual(profesionales[0]['name'], 'Juan Pérez Soto')
        self.assertEqual(profesionales[0]['email'], self.profesional.email)
        body = response.content.decode()
        modal = body[
            body.index('id="modalNuevaCita"'):body.index('id="modalReagendar"')
        ]
        self.assertLess(modal.index('>Profesional</label>'), modal.index('Hora disponible'))
        self.assertEqual([item.pk for item in response.context['reservas']], [reserva.pk])

    def test_admin_citas_filters_by_text_state_and_date_range(self):
        reserva_encontrada = self.crear_reserva()
        reserva_otra = self.crear_reserva('10:00', correo='otra@example.com')
        reserva_otra.cliente_nombre = 'Otra clienta'
        reserva_otra.estado = 'cancelada'
        reserva_otra.save(update_fields=['cliente_nombre', 'estado'])

        response = self.client.get(
            reverse('admin_citas'),
            {
                'desde': self.fecha.isoformat(),
                'hasta': self.fecha.isoformat(),
                'q': 'Camila Pérez',
                'estado': 'confirmada',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [reserva.pk for reserva in response.context['reservas']],
            [reserva_encontrada.pk],
        )
        self.assertContains(response, 'filtroTexto')
        self.assertContains(response, 'filtroServicio')
        self.assertContains(response, 'filtroProfesional')
        self.assertContains(response, 'filtroEstado')
        self.assertContains(response, 'filtroOrigen')

    def test_collaborator_can_book_in_person_as_staff_for_own_specialty(self):
        self.crear_bloque('09:00')
        self.client.force_login(self.profesional)

        page = self.client.get(reverse('admin_citas'))
        response = self.client.post(
            reverse('crear_reserva_manual'),
            {
                'cliente_nombre': 'Visita presencial',
                'cliente_email': 'visita@example.com',
                'cliente_telefono': '+56987654321',
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
                'hora': '09:00',
            },
        )

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Mis citas')
        self.assertNotContains(page, 'filtroProfesional')
        self.assertNotContains(page, '<th>Profesional</th>', html=True)
        self.assertNotContains(page, 'Todos los profesionales')
        self.assertContains(page, f'value="{self.profesional.pk}"')
        self.assertContains(page, 'Juan Pérez Soto · jp.soto@nicolettstudio.cl')
        self.assertContains(page, 'Hora disponible')
        body = page.content.decode()
        modal = body[
            body.index('id="modalNuevaCita"'):body.index('id="modalReagendar"')
        ]
        self.assertLess(modal.index('>Profesional</label>'), modal.index('Hora disponible'))
        self.assertRedirects(response, reverse('admin_citas'))
        reserva = Reserva.objects.get(cliente_nombre='Visita presencial')
        self.assertEqual(reserva.origen, 'personal')
        self.assertEqual(reserva.creada_por_id, self.profesional.pk)

    def test_collaborator_can_only_manage_own_appointments_and_requires_change_reason(self):
        self.crear_bloque('09:00')
        self.crear_bloque('10:00')
        reserva_propia = self.crear_reserva()
        otro_profesional = Usuario(
            nombre='Ana',
            segundo_nombre='',
            apellido_paterno='Otra',
            apellido_materno='Profesional',
            telefono='+56912345679',
            email='ana.otra@example.com',
            rol=self.profesional.rol,
        )
        otro_profesional.set_unusable_password()
        otro_profesional.save()
        reserva_ajena = Reserva.objects.create(
            fecha_hora=reserva_propia.fecha_hora + timedelta(minutes=60),
            profesional=otro_profesional,
            cliente_nombre='Cita ajena',
            servicio_id=self.servicio.pk,
        )
        self.client.force_login(self.profesional)

        response = self.client.get(reverse('admin_citas'))
        self.assertContains(response, 'Mis citas')
        self.assertContains(response, 'Camila Pérez')
        self.assertNotContains(response, 'Cita ajena')
        self.assertNotContains(response, 'filtroProfesional')
        self.assertNotContains(response, '<th>Profesional</th>', html=True)

        editar_url = reverse('reagendar_cita', args=[reserva_propia.pk])
        missing_reason = self.client.post(
            editar_url,
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
                'hora': '10:00',
            },
        )
        self.assertRedirects(missing_reason, reverse('admin_citas'))
        self.assertFalse(HistorialReserva.objects.filter(
            reserva=reserva_propia,
            evento='modificada',
        ).exists())

        edited = self.client.post(
            editar_url,
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
                'hora': '10:00',
                'motivo': 'Cambio solicitado por la clienta',
            },
        )
        self.assertRedirects(edited, reverse('admin_citas'))
        self.assertEqual(
            HistorialReserva.objects.get(reserva=reserva_propia, evento='modificada').motivo,
            'Cambio solicitado por la clienta',
        )
        forbidden = self.client.post(
            reverse('cancelar_cita', args=[reserva_ajena.pk]),
            {'motivo': 'No corresponde'},
        )
        self.assertEqual(forbidden.status_code, 403)
        cancelled = self.client.post(
            reverse('cancelar_cita', args=[reserva_propia.pk]),
            {'motivo': 'La clienta no podrá asistir'},
        )
        self.assertRedirects(cancelled, reverse('admin_citas'))
        reserva_propia.refresh_from_db()
        self.assertEqual(reserva_propia.estado, 'cancelada')
        self.assertEqual(reserva_propia.motivo_cancelacion, 'La clienta no podrá asistir')

    def test_collaborator_can_manage_only_specialty_availability_and_cannot_open_closed_day(self):
        otra_categoria = Categoria.objects.create(nombre='Cabello', tipo='Peluquería')
        otro_servicio = Servicio.objects.create(
            nombre='Corte',
            categoria=otra_categoria,
            duracion_minutos=60,
            precio='15000',
        )
        fecha_cerrada = self.fecha + timedelta(days=1)
        if fecha_cerrada.month != self.fecha.month:
            fecha_cerrada -= timedelta(days=2)
        cierre = DiaCerrado.objects.create(fecha=fecha_cerrada, motivo='Cierre admin')
        self.client.force_login(self.profesional)

        page = self.client.get(
            reverse('admin_agenda'),
            {'mes': self.fecha.strftime('%Y-%m'), 'dia': self.fecha.isoformat()},
        )
        self.assertContains(
            page,
            f'type="hidden" id="id_profesional_disponibilidad" name="profesional" value="{self.profesional.pk}"',
        )
        self.assertNotContains(page, 'for="id_profesional_disponibilidad"')

        allowed = self.post_bloques([{'inicio': '09:00', 'fin': '10:00'}])
        self.assertEqual(allowed.status_code, 302)
        self.assertTrue(Disponibilidad.objects.filter(
            profesional=self.profesional,
            servicio_id=self.servicio.pk,
        ).exists())

        disallowed_service = self.client.post(
            reverse('guardar_disponibilidad_dia'),
            {
                'fecha': self.fecha.isoformat(),
                'servicio': str(otro_servicio.pk),
                'profesional': str(self.profesional.pk),
                'bloques': '[{"inicio":"11:00","fin":"12:00"}]',
            },
        )
        self.assertEqual(disallowed_service.status_code, 302)
        self.assertFalse(Disponibilidad.objects.filter(servicio_id=otro_servicio.pk).exists())

        closed_day = self.client.post(
            reverse('guardar_disponibilidad_dia'),
            {
                'fecha': fecha_cerrada.isoformat(),
                'servicio': str(self.servicio.pk),
                'profesional': str(self.profesional.pk),
                'bloques': '[{"inicio":"11:00","fin":"12:00"}]',
            },
        )
        self.assertEqual(closed_day.status_code, 302)
        self.assertFalse(Disponibilidad.objects.filter(fecha_especifica=fecha_cerrada).exists())
        self.assertEqual(
            self.client.post(reverse('abrir_dia', args=[cierre.pk])).status_code,
            403,
        )
    def test_client_can_request_an_available_appointment(self):
        self.crear_bloque('09:00')
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        page = self.client.get(reverse('cliente_agendamiento'))
        professionals = self.client.get(
            reverse('cliente_profesionales_disponibles'),
            {'servicio': self.servicio.pk, 'fecha': self.fecha.isoformat()},
        )
        hours = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
            },
        )

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Agendar una cita')
        self.assertContains(page, 'Manicure')
        self.assertContains(page, 'Asistiré con acompañante')
        self.assertEqual(professionals.status_code, 200)
        self.assertEqual(
            [item['id'] for item in professionals.json()['professionals']],
            [self.profesional.pk],
        )
        self.assertEqual(hours.json()['hours'], ['09:00'])

        response = self.client.post(
            reverse('cliente_crear_reserva'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
                'hora': '09:00',
                'viene_con_acompanante': 'si',
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('cliente_agendamiento')}?abrir_carrito=1",
        )
        self.assertFalse(Reserva.objects.filter(cliente=cliente).exists())
        cita_carrito = self.client.session['carrito_compra']['servicios'][0]
        self.assertEqual(cita_carrito['id'], self.servicio.pk)
        self.assertEqual(cita_carrito['fecha'], self.fecha.isoformat())
        self.assertEqual(cita_carrito['profesional'], str(self.profesional.pk))
        self.assertEqual(cita_carrito['hora'], '09:00')
        self.assertTrue(cita_carrito['viene_con_acompanante'])
        self.assertTrue(
            ReservaCitaTemporal.objects.filter(
                session_key=self.client.session.session_key,
                cart_item_key=cita_carrito['key'],
                vence_en__gt=timezone.now(),
            ).exists()
        )
        agendamiento = self.client.get(response['Location'])
        self.assertContains(agendamiento, 'Resumen de compra')
        self.assertContains(agendamiento, 'abrir_carrito')
        self.assertContains(agendamiento, 'Manicure')
        self.assertContains(agendamiento, self.fecha.isoformat())
        self.assertContains(agendamiento, 'Juan Pérez')
        carrito = self.client.get(reverse('cliente_carrito'))
        self.assertContains(carrito, 'Manicure')
        self.assertContains(carrito, 'Asistirás con acompañante')
        self.assertContains(carrito, self.fecha.isoformat())
        self.assertContains(carrito, 'Juan Pérez')
        self.assertEqual(
            self.client.get(
                reverse('cliente_horas_disponibles'),
                {
                    'servicio': self.servicio.pk,
                    'profesional': self.profesional.pk,
                    'fecha': self.fecha.isoformat(),
                },
            ).json()['hours'],
            [],
        )

    def test_client_calendar_marks_available_closed_and_past_days(self):
        self.crear_bloque('09:00')
        closed_date = self.fecha - timedelta(days=1)
        if closed_date.month != self.fecha.month:
            closed_date += timedelta(days=2)
        DiaCerrado.objects.create(fecha=closed_date, motivo='Cierre de prueba')
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        response = self.client.get(
            reverse('cliente_calendario_disponibilidad'),
            {
                'servicio': self.servicio.pk,
                'mes': self.fecha.strftime('%Y-%m'),
            },
        )

        self.assertEqual(response.status_code, 200)
        days = {
            day['date']: day
            for week in response.json()['weeks']
            for day in week
        }
        self.assertTrue(days[self.fecha.isoformat()]['available'])
        self.assertIn('Manicure', days[self.fecha.isoformat()]['tooltip'])
        self.assertTrue(days[closed_date.isoformat()]['closed'])
        self.assertIn('Cierre de prueba', days[closed_date.isoformat()]['tooltip'])
        past_days = [
            day for day in days.values()
            if day['in_month'] and day['past']
        ]
        if past_days:
            self.assertFalse(past_days[0]['available'])

    def test_client_calendar_loads_month_and_combined_availability_without_service_filter(self):
        self.crear_bloque('09:00')
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        response = self.client.get(
            reverse('cliente_calendario_disponibilidad'),
            {'mes': self.fecha.strftime('%Y-%m')},
        )

        self.assertEqual(response.status_code, 200)
        days = {
            day['date']: day
            for week in response.json()['weeks']
            for day in week
        }
        self.assertTrue(days[self.fecha.isoformat()]['available'])
        self.assertContains(self.client.get(reverse('cliente_agendamiento')), 'id="bookingCalendar"')

    def test_client_cannot_book_unavailable_or_overlapping_appointment(self):
        self.crear_bloque('09:00')
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        booking_url = reverse('cliente_crear_reserva')
        valid_data = {
            'servicio': self.servicio.pk,
            'profesional': self.profesional.pk,
            'fecha': self.fecha.isoformat(),
            'hora': '10:00',
        }

        self.client.post(booking_url, valid_data)
        self.assertFalse(Reserva.objects.filter(cliente=cliente).exists())

        Reserva.objects.create(
            fecha_hora=timezone.make_aware(
                datetime.combine(self.fecha, datetime.strptime('08:30', '%H:%M').time()),
            ),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=60,
            profesional=self.profesional,
            cliente=cliente,
            cliente_nombre=f'{cliente.nombre} {cliente.apellido_paterno} {cliente.apellido_materno}',
            cliente_email=cliente.email,
            estado='confirmada',
            origen='cliente',
        )
        valid_data['hora'] = '09:00'
        self.client.post(booking_url, valid_data)

        self.assertEqual(Reserva.objects.filter(cliente=cliente).count(), 1)

    def test_client_cannot_book_for_another_category_or_closed_day(self):
        self.crear_bloque('09:00')
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        otra_categoria = Categoria.objects.create(nombre='Cabello', tipo='Cabello')
        otro_servicio = Servicio.objects.create(
            nombre='Corte',
            categoria=otra_categoria,
            duracion_minutos=60,
            precio='15000',
        )
        datos = {
            'servicio': otro_servicio.pk,
            'profesional': self.profesional.pk,
            'fecha': self.fecha.isoformat(),
            'hora': '09:00',
        }

        self.client.post(reverse('cliente_crear_reserva'), datos)
        self.assertFalse(Reserva.objects.filter(cliente=cliente).exists())

        DiaCerrado.objects.create(fecha=self.fecha, motivo='Prueba')
        datos.update(servicio=self.servicio.pk)
        self.client.post(reverse('cliente_crear_reserva'), datos)
        self.assertFalse(Reserva.objects.filter(cliente=cliente).exists())

    def test_client_can_reschedule_own_booking_to_a_different_service(self):
        self.crear_bloque('09:00')
        cliente = self.crear_cliente()
        reserva = Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(self.fecha, time(9, 0))),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente=cliente,
            cliente_nombre='Camila Prueba Cliente',
            cliente_email=cliente.email,
            estado='confirmada',
            origen='cliente',
        )

        otra_categoria = Categoria.objects.create(nombre='Cabello', tipo='Cabello')
        otro_servicio = Servicio.objects.create(
            nombre='Corte',
            categoria=otra_categoria,
            duracion_minutos=45,
            precio='15000',
        )
        otro_profesional = Usuario(
            nombre='Ana',
            segundo_nombre='',
            apellido_paterno='Gómez',
            apellido_materno='Rojas',
            telefono='+56912345679',
            email='ana.agenda@example.com',
            rol=self.profesional.rol,
        )
        otro_profesional.set_unusable_password()
        otro_profesional.save()
        ProfesionalCategoria.objects.create(
            profesional=otro_profesional,
            categoria_id=otra_categoria.pk,
        )
        self.crear_bloque(
            '11:00',
            servicio=otro_servicio,
            profesional=otro_profesional,
        )
        self.client.force_login(cliente)

        response = self.client.post(
            reverse('cliente_reagendar_reserva', args=[reserva.pk]),
            {
                'servicio': otro_servicio.pk,
                'profesional': otro_profesional.pk,
                'fecha': self.fecha.isoformat(),
                'hora': '11:00',
            },
        )

        self.assertRedirects(response, reverse('cliente_gestionar_citas'))
        reserva.refresh_from_db()
        self.assertEqual(reserva.servicio_id, otro_servicio.pk)
        self.assertEqual(reserva.servicio_nombre, otro_servicio.nombre)
        self.assertEqual(reserva.profesional_id, otro_profesional.pk)
        self.assertEqual(reserva.duracion_minutos, 45)
        self.assertEqual(timezone.localtime(reserva.fecha_hora).time(), time(11, 0))
        self.assertEqual(reserva.estado, 'confirmada')
        historial = HistorialReserva.objects.get(
            reserva=reserva,
            evento='modificada',
        )
        self.assertEqual(historial.servicio_nombre, self.servicio.nombre)
        self.assertEqual(historial.duracion_minutos, self.servicio.duracion_minutos)
        self.assertEqual(historial.fecha_hora, timezone.make_aware(
            datetime.combine(self.fecha, time(9, 0)),
        ))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cliente.email])
        self.assertIn('tu cita fue modificada', mail.outbox[0].body)
        self.assertIn('Nuevo servicio: Corte', mail.outbox[0].body)

    def test_client_can_cancel_own_booking_and_cannot_modify_another_clients_booking(self):
        cliente = self.crear_cliente()
        otra_cliente = Usuario.objects.create_user(
            email='otra.agenda@example.com',
            password='Cliente123!Test',
            nombre='Otra',
            apellido_paterno='Cliente',
            apellido_materno='Prueba',
            telefono='+56987654322',
            rol=cliente.rol,
        )
        reserva = Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(self.fecha, time(9, 0))),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente=otra_cliente,
            cliente_nombre='Otra Cliente Prueba',
            cliente_email=otra_cliente.email,
            estado='confirmada',
            origen='cliente',
        )
        self.client.force_login(cliente)

        response = self.client.post(
            reverse('cliente_cancelar_reserva', args=[reserva.pk]),
        )

        self.assertRedirects(response, reverse('cliente_gestionar_citas'))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'confirmada')

        reserva.cliente = cliente
        reserva.save(update_fields=['cliente'])
        pedido = Pedido.objects.create(
            cliente=cliente,
            total='14500',
            monto_pagado='7500',
            estado='abono',
        )
        DetallePedido.objects.create(
            pedido=pedido,
            tipo='servicio',
            nombre=self.servicio.nombre,
            cantidad=1,
            precio_unitario='12000',
            monto_pagado='5000',
            modalidad_pago='abono',
            reserva=reserva,
        )
        DetallePedido.objects.create(
            pedido=pedido,
            tipo='producto',
            nombre='Producto pagado',
            cantidad=1,
            precio_unitario='2500',
            monto_pagado='2500',
            modalidad_pago='no_aplica',
        )
        response = self.client.post(
            reverse('cliente_cancelar_reserva', args=[reserva.pk]),
            follow=True,
        )
        self.assertContains(response, 'devolución de $5.000')
        self.assertContains(response, 'no incluye productos')
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'cancelada')
        self.assertIn('Cancelada por la clienta', reserva.motivo_cancelacion)
        evento = HistorialReserva.objects.get(reserva=reserva)
        self.assertEqual(evento.evento, 'cancelada')
        self.assertEqual(evento.fecha_hora, reserva.fecha_hora)

    def test_client_management_shows_only_their_upcoming_unresolved_bookings(self):
        cliente = self.crear_cliente()
        otra_cliente = Usuario.objects.create_user(
            email='otra.gestion@example.com',
            password='Cliente123!Test',
            nombre='Otra',
            apellido_paterno='Cliente',
            apellido_materno='Prueba',
            telefono='+56987654322',
            rol=cliente.rol,
        )
        reserva_propia = Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(self.fecha, time(9, 0))),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente=cliente,
            estado='pendiente',
            origen='cliente',
        )
        Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(self.fecha, time(10, 0))),
            servicio_id=self.servicio.pk,
            servicio_nombre='Cita ajena',
            duracion_minutos=self.servicio.duracion_minutos,
            cliente=otra_cliente,
            estado='pendiente',
        )
        self.client.force_login(cliente)

        response = self.client.get(reverse('cliente_gestionar_citas'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.servicio.nombre)
        self.assertContains(response, f'action="{reverse("cliente_cancelar_reserva", args=[reserva_propia.pk])}"')
        self.assertContains(response, 'Cancelar')
        self.assertContains(response, 'Modificar')
        self.assertNotContains(response, 'Cancelar citas seleccionadas')
        self.assertNotContains(response, 'Selecciona una o más citas')
        self.assertNotContains(response, 'Cita ajena')
        self.assertEqual(list(response.context['reservas_gestionables']), [reserva_propia])

    def test_customer_cannot_change_or_cancel_appointment_inside_48_hour_window(self):
        self.crear_bloque('09:00')
        cliente = self.crear_cliente()
        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(hours=24),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente=cliente,
            estado='confirmada',
            origen='cliente',
        )
        self.client.force_login(cliente)

        page = self.client.get(reverse('cliente_gestionar_citas'))
        self.assertNotContains(page, f'value="{reserva.pk}" form="cancelSelectedBookings"')
        self.assertNotContains(page, 'Cancelar citas seleccionadas')
        self.assertContains(page, 'dentro de las 48 horas previas')
        self.assertContains(page, 'disabled')
        self.assertIn(reserva, page.context['reservas_gestionables'])

        cancel_response = self.client.post(
            reverse('cliente_cancelar_reserva', args=[reserva.pk]),
        )
        self.assertRedirects(cancel_response, reverse('cliente_gestionar_citas'))
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'confirmada')

    def test_client_booking_endpoints_require_client_role(self):
        self.client.force_login(self.profesional)

        response = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/?next=', response['Location'])
        self.assertIn(reverse('cliente_horas_disponibles'), response['Location'])

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

        self.assertRedirects(response, reverse('admin_citas'))
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.estado, 'confirmada')
        self.assertEqual(reserva.profesional_id, self.profesional.pk)

    def test_admin_can_edit_booking_from_available_calendar_and_account_client_is_emailed(self):
        servicio_nuevo = Servicio.objects.create(
            nombre='Manicure express',
            categoria=self.categoria,
            duracion_minutos=60,
            precio='10000',
        )
        profesional_nuevo = Usuario(
            nombre='Ana',
            segundo_nombre='',
            apellido_paterno='Gómez',
            apellido_materno='Rojas',
            telefono='+56912345679',
            email='ana.agenda@example.com',
            rol=self.profesional.rol,
        )
        profesional_nuevo.set_unusable_password()
        profesional_nuevo.save()
        ProfesionalCategoria.objects.create(
            profesional=profesional_nuevo,
            categoria_id=self.categoria.pk,
        )
        nueva_fecha = self.fecha + timedelta(days=7)
        Disponibilidad.objects.create(
            servicio_id=servicio_nuevo.pk,
            profesional=profesional_nuevo,
            fecha_especifica=nueva_fecha,
            dia_semana=str(nueva_fecha.weekday()),
            hora_inicio=time(11, 0),
            hora_fin=time(12, 0),
            activo=True,
        )
        cliente = self.crear_cliente()
        reserva = Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(self.fecha, time(9, 0))),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente=cliente,
            cliente_email=cliente.email,
            cliente_nombre='Camila Prueba Cliente',
            estado='confirmada',
            origen='cliente',
        )

        response = self.client.post(reverse('reagendar_cita', args=[reserva.pk]), {
            'servicio': servicio_nuevo.pk,
            'profesional': profesional_nuevo.pk,
            'fecha': nueva_fecha.isoformat(),
            'hora': '11:00',
        })

        self.assertRedirects(response, reverse('admin_citas'))
        reserva.refresh_from_db()
        self.assertEqual(reserva.servicio_id, servicio_nuevo.pk)
        self.assertEqual(reserva.profesional_id, profesional_nuevo.pk)
        self.assertEqual(timezone.localtime(reserva.fecha_hora).date(), nueva_fecha)
        self.assertEqual(timezone.localtime(reserva.fecha_hora).time(), time(11, 0))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cliente.email])
        self.assertIn('Manicure express', mail.outbox[0].body)
        self.assertIn('Ana Gómez Rojas', mail.outbox[0].body)

    def test_technical_record_pdf_is_only_available_for_account_bookings(self):
        cliente = self.crear_cliente()
        Reserva.objects.create(
            fecha_hora=timezone.now() - timedelta(days=2),
            servicio_id=self.servicio.pk,
            servicio_nombre=self.servicio.nombre,
            duracion_minutos=self.servicio.duracion_minutos,
            profesional=self.profesional,
            cliente=cliente,
            cliente_email=cliente.email,
            cliente_nombre='Camila Prueba Cliente',
            estado='completada',
            origen='cliente',
        )
        self.crear_reserva(correo='presencial@example.com')

        response = self.client.get(reverse('ficha_tecnica_pdf', args=[cliente.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(b'%PDF-1.4', response.content)
        self.assertIn(b'cliente.agenda@example.com', response.content)
        self.assertIn(b'Manicure', response.content)
        page = self.client.get(reverse('admin_citas'))
        self.assertContains(page, 'Ver ficha técnica')
        self.assertContains(page, 'disabled')
        self.assertContains(page, 'Editar')
        self.assertContains(page, 'Cancelar')

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
            'servicio': self.servicio.pk,
            'profesional': self.profesional.pk,
            'fecha': nueva_fecha.isoformat(),
            'hora': '09:00',
        })

        self.assertRedirects(response, reverse('admin_citas'))
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
