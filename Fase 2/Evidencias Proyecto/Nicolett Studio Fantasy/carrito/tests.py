from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Disponibilidad, ProfesionalCategoria, Reserva
from panel_admin.models import Categoria, Producto, Servicio
from usuarios.models import Rol, Usuario

from .models import (
    DetallePedido,
    PagoSimulado,
    Pedido,
    ReservaProductoCarrito,
)


class CarritoTests(TestCase):
    def setUp(self):
        self.rol_cliente, _ = Rol.objects.get_or_create(nombre='Cliente')
        self.rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
        self.cliente = Usuario.objects.create_user(
            email='cliente.carrito@example.com',
            password='Cliente123!Test',
            nombre='Camila',
            apellido_paterno='Prueba',
            apellido_materno='Cliente',
            telefono='+56987654321',
            rol=self.rol_cliente,
        )
        self.profesional = Usuario.objects.create_user(
            email='profesional.carrito@example.com',
            password='Colaborador123!Test',
            nombre='Juan',
            apellido_paterno='Prueba',
            apellido_materno='Colaborador',
            telefono='+56912345678',
            rol=self.rol_colaborador,
        )
        self.categoria = Categoria.objects.create(nombre='Uñas carrito', tipo='Manicure')
        self.servicio = Servicio.objects.create(
            nombre='Manicure carrito',
            categoria=self.categoria,
            duracion_minutos=60,
            precio=Decimal('12000'),
            activo=True,
        )
        self.producto = Producto.objects.create(
            nombre='Esmalte carrito',
            categoria=self.categoria,
            precio=Decimal('2500'),
            stock=10,
            activo=True,
        )
        ProfesionalCategoria.objects.create(
            profesional=self.profesional,
            categoria_id=self.categoria.pk,
        )
        self.fecha = timezone.localdate() + timedelta(days=14)
        Disponibilidad.objects.create(
            dia_semana=str(self.fecha.weekday()),
            fecha_especifica=self.fecha,
            hora_inicio=datetime.strptime('10:00', '%H:%M').time(),
            hora_fin=datetime.strptime('11:00', '%H:%M').time(),
            intervalo_minutos=60,
            activo=True,
            profesional=self.profesional,
            servicio_id=self.servicio.pk,
        )
        self.client.force_login(self.cliente)

    def test_product_quantities_recalculate_and_checkout_updates_stock(self):
        add_url = reverse('cliente_carrito_agregar_producto', args=[self.producto.pk])
        self.client.post(add_url, {'cantidad': 1})
        self.client.post(add_url, {'cantidad': 2})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 7)

        cart = self.client.get(reverse('cliente_carrito'))
        self.assertContains(cart, 'Subtotal $7500')
        self.assertContains(cart, '>3</span>')

        response = self.client.post(reverse('cliente_carrito_pagar'))

        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertRedirects(response, reverse('cliente_compra_resultado', args=[pedido.pk]))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 7)
        self.assertEqual(pedido.total, Decimal('7500'))
        self.assertEqual(pedido.monto_pagado, Decimal('7500'))
        self.assertEqual(pedido.estado, 'pagado')
        self.assertEqual(DetallePedido.objects.get(pedido=pedido).cantidad, 3)
        self.assertEqual(PagoSimulado.objects.get(pedido=pedido).monto, Decimal('7500'))
        self.assertFalse(ReservaProductoCarrito.objects.exists())

    def test_removing_product_from_cart_restores_stock(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 3},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 7)

        self.client.post(
            reverse('cliente_carrito_actualizar'),
            {'tipo': 'producto', 'clave': self.producto.pk, 'cantidad': 0},
        )

        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertFalse(ReservaProductoCarrito.objects.exists())

    def test_cart_summary_and_quantity_controls_update_and_return_to_previous_page(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 2},
        )

        catalog = self.client.get(reverse('cliente_productos'))
        self.assertContains(catalog, 'Resumen de compra')
        self.assertContains(catalog, 'Esmalte carrito')
        self.assertContains(catalog, 'Subtotal $5000')
        self.assertContains(catalog, 'Aumentar cantidad de Esmalte carrito')
        self.assertContains(catalog, 'Ir al carrito de compras')

        response = self.client.post(
            reverse('cliente_carrito_actualizar'),
            {
                'tipo': 'producto',
                'clave': self.producto.pk,
                'cantidad': 3,
                'return_to': reverse('cliente_productos'),
            },
        )

        self.assertRedirects(response, reverse('cliente_productos'))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 7)
        self.assertEqual(
            self.client.session['carrito_compra']['productos'][str(self.producto.pk)],
            3,
        )
        cart_page = self.client.get(reverse('cliente_carrito'))
        self.assertContains(cart_page, 'Subtotal $7500')
        self.assertContains(cart_page, 'Disminuir cantidad de Esmalte carrito')
        self.assertContains(cart_page, 'Eliminar Esmalte carrito')
        self.assertNotContains(cart_page, 'Actualizar')

    def test_service_summary_can_add_and_remove_a_service_appointment(self):
        self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[self.servicio.pk]),
        )

        catalog = self.client.get(reverse('cliente_servicios'))
        self.assertContains(catalog, 'Manicure carrito')
        self.assertContains(catalog, 'Aumentar citas de Manicure carrito')
        self.assertContains(catalog, 'Eliminar Manicure carrito')
        service_key = self.client.session['carrito_compra']['servicios'][0]['key']

        response = self.client.post(
            reverse('cliente_carrito_actualizar'),
            {
                'tipo': 'servicio',
                'clave': service_key,
                'return_to': reverse('cliente_servicios'),
            },
        )

        self.assertRedirects(response, reverse('cliente_servicios'))
        self.assertEqual(self.client.session['carrito_compra']['servicios'], [])

    def test_expired_product_reservation_returns_stock_and_removes_cart_item(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 2},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 8)
        ReservaProductoCarrito.objects.filter(
            session_key=self.client.session.session_key,
            producto_id=self.producto.pk,
        ).update(vence_en=timezone.now() - timedelta(seconds=1))

        response = self.client.get(reverse('cliente_productos'))

        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertFalse(ReservaProductoCarrito.objects.exists())
        self.assertNotIn(
            str(self.producto.pk),
            self.client.session['carrito_compra']['productos'],
        )
        self.assertContains(response, '10 disponibles')

    def test_service_requires_schedule_and_records_fixed_deposit_and_reservation(self):
        self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[self.servicio.pk]),
        )
        self.client.post(reverse('cliente_carrito_pagar'))
        self.assertFalse(Pedido.objects.exists())

        carrito = self.client.session['carrito_compra']
        key = carrito['servicios'][0]['key']
        response = self.client.post(
            reverse('cliente_carrito_guardar_cita', args=[key]),
            {
                'fecha': self.fecha.isoformat(),
                'profesional': self.profesional.pk,
                'hora': '10:00',
                'pago': 'abono',
            },
        )
        self.assertRedirects(response, reverse('cliente_carrito'))

        response = self.client.post(reverse('cliente_carrito_pagar'))

        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertRedirects(response, reverse('cliente_compra_resultado', args=[pedido.pk]))
        self.assertEqual(pedido.total, Decimal('12000'))
        self.assertEqual(pedido.monto_pagado, Decimal('5000'))
        self.assertEqual(pedido.saldo_pendiente, Decimal('7000'))
        self.assertEqual(pedido.estado, 'abono')
        detalle = DetallePedido.objects.get(pedido=pedido)
        self.assertEqual(detalle.modalidad_pago, 'abono')
        self.assertEqual(detalle.monto_pagado, Decimal('5000'))
        self.assertEqual(detalle.reserva.cliente, self.cliente)
        self.assertEqual(detalle.reserva.profesional, self.profesional)
        self.assertEqual(detalle.reserva.servicio_id, self.servicio.pk)
        self.assertEqual(detalle.reserva.estado, 'confirmada')
        self.assertEqual(PagoSimulado.objects.get(pedido=pedido).monto, Decimal('5000'))

    def test_service_can_be_paid_in_full(self):
        self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[self.servicio.pk]),
        )
        key = self.client.session['carrito_compra']['servicios'][0]['key']
        self.client.post(
            reverse('cliente_carrito_guardar_cita', args=[key]),
            {
                'fecha': self.fecha.isoformat(),
                'profesional': self.profesional.pk,
                'hora': '10:00',
                'pago': 'completo',
            },
        )

        self.client.post(reverse('cliente_carrito_pagar'))

        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertEqual(pedido.total, Decimal('12000'))
        self.assertEqual(pedido.monto_pagado, Decimal('12000'))
        self.assertEqual(pedido.saldo_pendiente, Decimal('0'))
        self.assertEqual(pedido.estado, 'pagado')
        self.assertEqual(PagoSimulado.objects.get(pedido=pedido).monto, Decimal('12000'))

    def test_checkout_rejects_overlapping_service_appointments_for_customer(self):
        segundo_profesional = Usuario.objects.create_user(
            email='segundo.carrito@example.com',
            password='Colaborador123!Test',
            nombre='Pedro',
            apellido_paterno='Prueba',
            apellido_materno='Colaborador',
            telefono='+56912345679',
            rol=self.rol_colaborador,
        )
        ProfesionalCategoria.objects.create(
            profesional=segundo_profesional,
            categoria_id=self.categoria.pk,
        )
        Disponibilidad.objects.create(
            dia_semana=str(self.fecha.weekday()),
            fecha_especifica=self.fecha,
            hora_inicio=datetime.strptime('10:00', '%H:%M').time(),
            hora_fin=datetime.strptime('11:00', '%H:%M').time(),
            intervalo_minutos=60,
            activo=True,
            profesional=segundo_profesional,
            servicio_id=self.servicio.pk,
        )
        self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[self.servicio.pk]),
        )
        self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[self.servicio.pk]),
        )
        servicios = self.client.session['carrito_compra']['servicios']
        for linea, profesional in zip(
            servicios,
            (self.profesional, segundo_profesional),
        ):
            self.client.post(
                reverse('cliente_carrito_guardar_cita', args=[linea['key']]),
                {
                    'fecha': self.fecha.isoformat(),
                    'profesional': profesional.pk,
                    'hora': '10:00',
                    'pago': 'completo',
                },
            )

        self.client.post(reverse('cliente_carrito_pagar'))

        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(Reserva.objects.filter(cliente=self.cliente).exists())

    def test_only_customers_can_access_cart(self):
        administrador = Usuario.objects.create_superuser(
            email='admin.carrito@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Prueba',
            apellido_materno='Admin',
            telefono='+56911111111',
        )
        self.client.force_login(administrador)

        response = self.client.get(reverse('cliente_carrito'))

        self.assertNotEqual(response.status_code, 200)
