from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import HistorialReserva, Reserva
from panel_admin.models import Categoria, Servicio
from usuarios.models import Rol, Usuario

# Create your tests here.


class ClienteFichaTecnicaTests(TestCase):
    def test_customer_can_open_pdf_with_only_their_appointments_and_history(self):
        rol_cliente, _ = Rol.objects.get_or_create(nombre='Cliente')
        cliente = Usuario.objects.create_user(
            email='ficha.cliente@example.com',
            password='Cliente123!',
            nombre='Camila',
            apellido_paterno='Pérez',
            apellido_materno='Rojas',
            telefono='+56912345678',
            rol=rol_cliente,
        )
        otra_cliente = Usuario.objects.create_user(
            email='otra.ficha@example.com',
            password='Cliente123!',
            nombre='Otra',
            apellido_paterno='Persona',
            apellido_materno='Prueba',
            telefono='+56912345679',
            rol=rol_cliente,
        )
        categoria = Categoria.objects.create(nombre='Cuidado ficha', tipo='Cuidado')
        servicio = Servicio.objects.create(
            nombre='Servicio ficha PDF',
            categoria=categoria,
            precio=10000,
            duracion_minutos=45,
        )
        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(days=2),
            estado='confirmada',
            origen='cliente',
            cliente=cliente,
            cliente_nombre='Camila Pérez Rojas',
            cliente_email=cliente.email,
            cliente_telefono=cliente.telefono,
            servicio_id=servicio.pk,
            servicio_nombre=servicio.nombre,
            duracion_minutos=45,
        )
        HistorialReserva.objects.create(
            reserva=reserva,
            evento='modificada',
            fecha_hora=timezone.now(),
            servicio_nombre='Servicio anterior PDF',
            profesional_nombre='Profesional Prueba',
            estado='confirmada',
        )
        Reserva.objects.create(
            fecha_hora=timezone.now(),
            estado='confirmada',
            cliente=otra_cliente,
            servicio_nombre='Cita privada PDF',
        )
        Reserva.objects.bulk_create([
            Reserva(
                fecha_hora=timezone.now() + timedelta(days=day + 3),
                estado='confirmada',
                origen='cliente',
                cliente=cliente,
                cliente_nombre='Camila Pérez Rojas',
                cliente_email=cliente.email,
                servicio_id=servicio.pk,
                servicio_nombre=f'Servicio listado {day}',
                duracion_minutos=45,
            )
            for day in range(24)
        ])
        self.client.force_login(cliente)

        response = self.client.get(reverse('cliente_ficha_tecnica_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('inline;', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF-1.4'))
        self.assertIn(b'Servicio ficha PDF', response.content)
        self.assertIn(b'Servicio anterior PDF', response.content)
        self.assertNotIn(b'Cita privada PDF', response.content)
        self.assertIn(b'/Count 2', response.content)
        self.assertIn(b'Helvetica-Bold', response.content)

    def test_admin_opens_same_pdf_as_customer_for_registered_client(self):
        Rol.objects.get_or_create(nombre='Admin')
        cliente_role, _ = Rol.objects.get_or_create(nombre='Cliente')
        admin = Usuario.objects.create_superuser(
            email='admin.ficha@example.com',
            password='Admin123!Test',
            nombre='Administración',
            apellido_paterno='Prueba',
            apellido_materno='',
            telefono='+56912345678',
        )
        cliente = Usuario.objects.create_user(
            email='cliente.ficha.admin@example.com',
            password='Cliente123!Test',
            nombre='Camila',
            apellido_paterno='Pérez',
            apellido_materno='Rojas',
            telefono='+56987654321',
            rol=cliente_role,
        )
        Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(days=3),
            estado='confirmada',
            origen='cliente',
            cliente=cliente,
            cliente_nombre='Camila Pérez Rojas',
            cliente_email=cliente.email,
            cliente_telefono=cliente.telefono,
            servicio_nombre='Cita futura registrada',
            duracion_minutos=45,
        )
        self.client.force_login(cliente)
        ficha_cliente = self.client.get(reverse('cliente_ficha_tecnica_pdf'))
        self.client.force_login(admin)

        ficha_admin = self.client.get(
            reverse('ficha_tecnica_pdf', args=[cliente.pk]),
        )

        self.assertEqual(ficha_admin.status_code, 200)
        self.assertEqual(ficha_admin['Content-Type'], 'application/pdf')
        self.assertEqual(ficha_admin.content, ficha_cliente.content)
        self.assertIn(b'Cita futura registrada', ficha_admin.content)
