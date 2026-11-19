from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote, urlencode

from django.core import mail
from django.core import signing
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.models import (
    Disponibilidad,
    ProfesionalCategoria,
    Reserva,
    ReservaCitaTemporal,
)
from panel_admin.models import Categoria, Producto, Servicio
from usuarios.models import Rol, Usuario
from pagos.models import Pago
from ventas.models import DetalleVenta, Venta

from .models import (
    DetallePedido,
    PagoSimulado,
    Pedido,
    ReservaProductoCarrito,
    TransbankPago,
)


@override_settings(TRANSBANK_ENVIRONMENT='SIMULATED')
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

    def crear_cita_en_carrito(
        self,
        pago='completo',
        profesional=None,
        hora='10:00',
        fecha=None,
        viene_con_acompanante=False,
    ):
        profesional = profesional or self.profesional
        fecha = fecha or self.fecha
        response = self.client.post(
            reverse('cliente_crear_reserva'),
            {
                'servicio': self.servicio.pk,
                'profesional': profesional.pk,
                'fecha': fecha.isoformat(),
                'hora': hora,
                'viene_con_acompanante': 'si' if viene_con_acompanante else '',
            },
        )
        self.assertEqual(response.status_code, 302)
        item = self.client.session['carrito_compra']['servicios'][-1]
        self.client.post(
            reverse('cliente_carrito_guardar_cita', args=[item['key']]),
            {
                'fecha': fecha.isoformat(),
                'profesional': str(profesional.pk),
                'hora': hora,
                'pago': pago,
            },
        )
        return item['key']

    def test_product_quantities_recalculate_and_checkout_updates_stock(self):
        add_url = reverse('cliente_carrito_agregar_producto', args=[self.producto.pk])
        self.client.post(add_url, {'cantidad': 1})
        self.client.post(add_url, {'cantidad': 2})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 7)

        cart = self.client.get(reverse('cliente_carrito'))
        self.assertContains(cart, 'Subtotal $7.500')
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
        venta = Venta.objects.get(cliente=self.cliente)
        self.assertEqual(venta.total, Decimal('7500'))
        self.assertEqual(venta.estado, 'Completada')
        detalle_venta = DetalleVenta.objects.get(venta=venta)
        self.assertEqual(detalle_venta.producto_id, self.producto.pk)
        self.assertEqual(detalle_venta.item_nombre, self.producto.nombre)
        self.assertEqual(detalle_venta.item_descripcion, self.producto.descripcion or '')
        self.assertEqual(detalle_venta.precio_unitario, self.producto.precio)
        self.assertEqual(Pago.objects.get(venta=venta).monto, Decimal('7500'))
        self.assertFalse(ReservaProductoCarrito.objects.exists())

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    def test_checkout_review_page_shows_cart_and_does_not_pay_until_submitted(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )

        response = self.client.get(reverse('cliente_carrito_checkout'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.producto.nombre)
        self.assertContains(response, 'Tarjeta de débito o crédito')
        self.assertContains(response, '4051 8856 0044 6623')
        self.assertContains(response, 'Continuar a Webpay')
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(TransbankPago.objects.exists())

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

    def test_product_add_and_remove_keep_selected_category_without_success_notices(self):
        categoria = Categoria.objects.create(nombre='Tratamientos capilares', tipo='producto')
        otra_categoria = Categoria.objects.create(nombre='Cuidado facial', tipo='producto')
        producto = Producto.objects.create(
            nombre='Tratamiento de prueba',
            categoria=categoria,
            precio=Decimal('5000'),
            stock=5,
            activo=True,
        )
        otro_producto = Producto.objects.create(
            nombre='Producto de otra categoría',
            categoria=otra_categoria,
            precio=Decimal('6000'),
            stock=5,
            activo=True,
        )
        catalog_url = f'{reverse("cliente_productos")}?categoria={categoria.pk}'

        add_response = self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[producto.pk]),
            {'cantidad': 1, 'return_to': catalog_url},
        )
        self.assertEqual(add_response.status_code, 302)
        self.assertEqual(add_response['Location'], catalog_url)

        catalog = self.client.get(catalog_url)
        self.assertContains(catalog, producto.nombre)
        self.assertNotContains(catalog, otro_producto.nombre)
        self.assertContains(catalog, f'value="{catalog_url}"')
        self.assertNotContains(catalog, 'se añadió y quedó reservado')

        remove_response = self.client.post(
            reverse('cliente_carrito_actualizar'),
            {
                'tipo': 'producto',
                'clave': producto.pk,
                'cantidad': 0,
                'return_to': catalog_url,
            },
        )
        self.assertEqual(remove_response.status_code, 302)
        self.assertEqual(remove_response['Location'], catalog_url)

        catalog_after_remove = self.client.get(catalog_url)
        self.assertContains(catalog_after_remove, producto.nombre)
        self.assertNotContains(catalog_after_remove, otro_producto.nombre)
        self.assertNotContains(catalog_after_remove, 'Producto eliminado y stock devuelto.')
        self.assertFalse(ReservaProductoCarrito.objects.filter(producto_id=producto.pk).exists())

    def test_cart_summary_and_quantity_controls_update_and_return_to_previous_page(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 2},
        )

        catalog = self.client.get(reverse('cliente_productos'))
        self.assertContains(catalog, 'Resumen de compra')
        self.assertContains(catalog, 'Esmalte carrito')
        self.assertContains(catalog, 'Subtotal $5.000')
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
        self.assertContains(cart_page, 'Subtotal $7.500')
        self.assertContains(cart_page, 'Disminuir cantidad de Esmalte carrito')
        self.assertContains(cart_page, 'Eliminar Esmalte carrito')
        self.assertNotContains(cart_page, 'Actualizar')

    def test_legacy_add_service_route_redirects_to_booking_without_adding_incomplete_item(self):
        response = self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[self.servicio.pk]),
        )
        self.assertRedirects(
            response,
            f"{reverse('cliente_servicios')}?servicio={self.servicio.pk}#servicios-semana",
        )

        catalog = self.client.get(reverse('cliente_servicios'))
        self.assertContains(catalog, 'Manicure carrito')
        self.assertEqual(
            self.client.session.get('carrito_compra', {}).get('servicios', []),
            [],
        )
        self.assertFalse(ReservaCitaTemporal.objects.exists())

    def test_removing_reserved_service_releases_its_available_slot(self):
        key = self.crear_cita_en_carrito()

        response = self.client.post(
            reverse('cliente_carrito_actualizar'),
            {'tipo': 'servicio', 'clave': key},
        )

        self.assertRedirects(response, reverse('cliente_carrito'))
        self.assertFalse(ReservaCitaTemporal.objects.exists())
        self.assertEqual(self.client.session['carrito_compra']['servicios'], [])
        hours = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
            },
        )
        self.assertEqual(hours.json()['hours'], ['10:00'])

    def test_cart_payment_update_cannot_change_reserved_appointment_details(self):
        key = self.crear_cita_en_carrito()
        another_date = self.fecha + timedelta(days=1)

        response = self.client.post(
            reverse('cliente_carrito_guardar_cita', args=[key]),
            {
                'fecha': another_date.isoformat(),
                'profesional': str(self.profesional.pk),
                'hora': '10:00',
                'pago': 'abono',
            },
        )

        self.assertRedirects(response, reverse('cliente_carrito'))
        item = self.client.session['carrito_compra']['servicios'][0]
        self.assertEqual(item['fecha'], self.fecha.isoformat())
        self.assertEqual(item['pago'], 'completo')
        hold = ReservaCitaTemporal.objects.get(cart_item_key=key)
        self.assertEqual(hold.fecha, self.fecha)

    def test_service_without_future_availability_cannot_be_added_to_cart(self):
        servicio = Servicio.objects.create(
            nombre='Servicio sin agenda',
            categoria=self.categoria,
            duracion_minutos=30,
            precio=Decimal('8000'),
            activo=True,
        )

        response = self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[servicio.pk]),
        )

        self.assertEqual(
            response['Location'],
            f"{reverse('cliente_servicios')}?servicio={servicio.pk}#servicios-semana",
        )
        self.assertEqual(
            self.client.session.get('carrito_compra', {}).get('servicios', []),
            [],
        )

    def test_expired_appointment_reservation_releases_the_slot_and_removes_cart_item(self):
        key = self.crear_cita_en_carrito()
        reserva_temporal = ReservaCitaTemporal.objects.get(cart_item_key=key)
        self.assertEqual(reserva_temporal.duracion_minutos, self.servicio.duracion_minutos)
        ReservaCitaTemporal.objects.filter(pk=reserva_temporal.pk).update(
            vence_en=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.get(reverse('cliente_servicios'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ReservaCitaTemporal.objects.exists())
        self.assertEqual(self.client.session['carrito_compra']['servicios'], [])
        hours = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
            },
        )
        self.assertEqual(hours.json()['hours'], ['10:00'])

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

        key = self.crear_cita_en_carrito(pago='abono')

        horas_reservadas = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
            },
        )
        horas_propias = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
                'cart_item_key': key,
            },
        )
        self.assertEqual(horas_reservadas.json()['hours'], [])
        self.assertEqual(horas_propias.json()['hours'], ['10:00'])

        cart = self.client.get(reverse('cliente_carrito'))
        self.assertEqual(cart.context['total_servicios_completo'], Decimal('0'))
        self.assertEqual(cart.context['total_servicios_abono'], Decimal('5000'))
        self.assertEqual(cart.context['saldo_servicios_pendiente'], Decimal('7000'))
        self.assertEqual(cart.context['saldos_servicios'][0]['nombre'], self.servicio.nombre)
        self.assertContains(cart, 'Servicios (pago completo)')
        self.assertContains(cart, 'Servicios (abono)')
        self.assertContains(cart, 'Saldos pendientes')
        self.assertContains(cart, 'Día de atención bloqueado')
        self.assertContains(cart, 'Profesional bloqueado')
        self.assertContains(cart, 'Hora bloqueada')
        self.assertNotContains(cart, 'Guardar cita')
        self.assertNotContains(cart, 'ficticio')
        self.assertNotContains(cart, 'saldo $7000 en el salón')

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
        venta = Venta.objects.get(cliente=self.cliente)
        self.assertEqual(venta.total, Decimal('12000'))
        self.assertEqual(venta.estado, 'Pendiente')
        detalle_venta = DetalleVenta.objects.get(venta=venta)
        self.assertEqual(detalle_venta.servicio_id, self.servicio.pk)
        self.assertEqual(detalle_venta.item_nombre, self.servicio.nombre)
        self.assertEqual(detalle_venta.item_descripcion, self.servicio.descripcion or '')
        self.assertEqual(detalle_venta.precio_unitario, self.servicio.precio)
        self.assertEqual(Pago.objects.get(venta=venta).monto, Decimal('5000'))
        self.assertFalse(ReservaCitaTemporal.objects.exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_service_can_be_paid_in_full_and_emails_confirmation(self):
        self.crear_cita_en_carrito(
            pago='completo',
            viene_con_acompanante=True,
        )

        cart = self.client.get(reverse('cliente_carrito'))
        self.assertContains(cart, 'Asistirás con acompañante')
        self.assertEqual(cart.context['total_servicios_completo'], Decimal('12000'))
        self.assertEqual(cart.context['total_servicios_abono'], Decimal('0'))
        self.assertEqual(cart.context['saldo_servicios_pendiente'], Decimal('0'))

        response = self.client.post(reverse('cliente_carrito_pagar'))

        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertRedirects(
            response,
            reverse('cliente_compra_resultado', args=[pedido.pk]),
        )
        self.assertEqual(pedido.total, Decimal('12000'))
        self.assertEqual(pedido.monto_pagado, Decimal('12000'))
        self.assertEqual(pedido.saldo_pendiente, Decimal('0'))
        self.assertEqual(pedido.estado, 'pagado')
        self.assertEqual(PagoSimulado.objects.get(pedido=pedido).monto, Decimal('12000'))
        venta = Venta.objects.get(cliente=self.cliente)
        self.assertEqual(venta.total, Decimal('12000'))
        self.assertEqual(venta.estado, 'Completada')
        self.assertEqual(Pago.objects.get(venta=venta).monto, Decimal('12000'))
        self.assertTrue(Reserva.objects.get(cliente=self.cliente).viene_con_acompanante)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.cliente.email])
        self.assertIn('comprobante de tu compra', mail.outbox[0].body)
        self.assertIn(f'Número de compra: {pedido.pk}', mail.outbox[0].body)
        self.assertIn('Número de transacción:', mail.outbox[0].body)
        self.assertIn(self.servicio.nombre, mail.outbox[0].body)
        self.assertIn(reverse('cliente_gestionar_citas'), mail.outbox[0].body)
        resultado = self.client.get(reverse('cliente_compra_resultado', args=[pedido.pk]))
        self.assertContains(resultado, 'citas incluidas en esta compra quedaron confirmadas')
        self.assertContains(resultado, 'Mis citas')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_checkout_does_not_claim_receipt_was_sent_without_email_delivery(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )

        response = self.client.post(
            reverse('cliente_carrito_pagar'),
            follow=True,
        )

        self.assertContains(response, 'no se pudo enviar el comprobante al correo')
        self.assertNotContains(response, 'Enviamos el comprobante a tu correo')

    def test_mixed_checkout_records_products_services_and_paid_amount_for_admin(self):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 2},
        )
        self.crear_cita_en_carrito(pago='abono')

        response = self.client.post(reverse('cliente_carrito_pagar'))

        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertRedirects(
            response,
            reverse('cliente_compra_resultado', args=[pedido.pk]),
        )
        self.assertEqual(pedido.total, Decimal('17000'))
        self.assertEqual(pedido.monto_pagado, Decimal('10000'))
        venta = Venta.objects.get(cliente=self.cliente)
        self.assertEqual(venta.total, Decimal('17000'))
        self.assertEqual(venta.estado, 'Pendiente')
        detalles = list(DetalleVenta.objects.filter(venta=venta).order_by('pk'))
        self.assertEqual(len(detalles), 2)
        self.assertEqual(detalles[0].producto_id, self.producto.pk)
        self.assertEqual(detalles[0].cantidad, 2)
        self.assertEqual(detalles[0].item_nombre, self.producto.nombre)
        self.assertEqual(detalles[0].precio_unitario, self.producto.precio)
        self.assertEqual(detalles[1].servicio_id, self.servicio.pk)
        self.assertEqual(detalles[1].item_nombre, self.servicio.nombre)
        self.assertEqual(detalles[1].precio_unitario, self.servicio.precio)
        self.assertEqual(Pago.objects.get(venta=venta).monto, Decimal('10000'))

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
        key = self.crear_cita_en_carrito()
        second_key = 'overlapping-service-key'
        session = self.client.session
        carrito = session['carrito_compra']
        carrito['servicios'].append({
            'key': second_key,
            'id': self.servicio.pk,
            'fecha': self.fecha.isoformat(),
            'profesional': str(segundo_profesional.pk),
            'hora': '10:00',
            'pago': 'completo',
            'viene_con_acompanante': False,
        })
        session['carrito_compra'] = carrito
        session.save()
        ReservaCitaTemporal.objects.create(
            session_key=session.session_key,
            cart_item_key=second_key,
            servicio_id=self.servicio.pk,
            profesional=segundo_profesional,
            fecha=self.fecha,
            hora=datetime.strptime('10:00', '%H:%M').time(),
            duracion_minutos=self.servicio.duracion_minutos,
            vence_en=timezone.now() + timedelta(minutes=30),
        )
        self.assertIn(
            key,
            [item['key'] for item in self.client.session['carrito_compra']['servicios']],
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

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.create_transaction')
    @patch('carrito.views.get_transaction')
    def test_transbank_checkout_creates_attempt_before_redirecting(self, mock_gateway, mock_create):
        mock_create.return_value = {
            'token': 'token-integracion',
            'url': 'https://webpay3gint.transbank.cl/webpayserver/initTransaction',
        }
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )

        response = self.client.post(reverse('cliente_carrito_pagar'))

        intento = TransbankPago.objects.get(cliente=self.cliente)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'action="{reverse("cliente_webpay_abrir")}"',
        )
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'rel="noopener"')
        self.assertNotContains(response, 'noreferrer')
        self.assertNotContains(response, 'name="token_ws"')
        self.assertContains(response, 'data-webpay-launch')
        self.assertEqual(intento.estado, 'pendiente')
        self.assertEqual(intento.monto, Decimal('2500'))
        self.assertEqual(intento.carrito['productos'], {str(self.producto.pk): 1})
        self.assertFalse(Pedido.objects.exists())
        self.assertContains(response, 'Volver al carrito y modificar la compra')
        self.assertContains(response, 'Cada intento se abre una sola vez')
        self.assertContains(response, 'podrás elegir crédito, débito o prepago')
        mock_gateway.assert_called_once()

        referencia = response.context['referencia']
        webpay = self.client.post(
            reverse('cliente_webpay_abrir'),
            {'ref': referencia},
        )
        intento.refresh_from_db()
        self.assertEqual(webpay.status_code, 200)
        self.assertContains(webpay, f'action="{mock_create.return_value["url"]}"')
        self.assertContains(webpay, 'name="token_ws" value="token-integracion"')
        self.assertContains(webpay, 'data-webpay-form')
        self.assertContains(webpay, "window.addEventListener('load'")
        self.assertEqual(intento.estado, 'webpay_abierto')

        webpay_repetido = self.client.post(
            reverse('cliente_webpay_abrir'),
            {'ref': referencia},
        )
        self.assertEqual(webpay_repetido.status_code, 200)
        self.assertNotContains(webpay_repetido, 'name="token_ws"')
        self.assertContains(webpay_repetido, 'Este intento ya fue enviado a Webpay')

        response_reintentado = self.client.post(reverse('cliente_carrito_pagar'))
        self.assertEqual(response_reintentado.status_code, 200)
        self.assertNotContains(response_reintentado, 'name="token_ws"')
        self.assertContains(response_reintentado, 'Este intento ya fue enviado a Webpay')
        mock_create.assert_called_once()

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.create_transaction')
    @patch('carrito.views.get_transaction')
    def test_ajax_transbank_checkout_returns_modal_data(self, mock_gateway, mock_create):
        mock_create.return_value = {
            'token': 'token-integracion',
            'url': 'https://webpay3gint.transbank.cl/webpayserver/initTransaction',
        }
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )

        response = self.client.post(
            reverse('cliente_carrito_pagar'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['webpay_abierto'], False)
        self.assertTrue(response.json()['referencia'])
        self.assertTrue(TransbankPago.objects.filter(cliente=self.cliente, estado='pendiente').exists())
        checkout = self.client.get(reverse('cliente_carrito_checkout'))
        self.assertContains(checkout, 'data-webpay-dialog')
        self.assertContains(checkout, 'Ir al formulario de tarjeta')
        self.assertContains(checkout, 'Volver al carrito y modificar la compra')
        mock_gateway.assert_called_once()
        mock_create.assert_called_once()

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.create_transaction')
    @patch('carrito.views.get_transaction')
    def test_expired_webpay_attempt_is_replaced_before_retry(self, mock_gateway, mock_create):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )
        session = self.client.session
        intento_anterior = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-vencida',
            session_id='sesion-vencida',
            session_key=session.session_key,
            carrito=session['carrito_compra'],
            monto=Decimal('2500'),
            token='token-vencido',
            webpay_url='https://webpay3gint.transbank.cl/webpayserver/initTransaction',
            estado='pendiente',
        )
        TransbankPago.objects.filter(pk=intento_anterior.pk).update(
            creado_en=timezone.now() - timedelta(minutes=10),
        )
        mock_create.return_value = {
            'token': 'token-nuevo',
            'url': 'https://webpay3gint.transbank.cl/webpayserver/initTransaction',
        }

        response = self.client.post(reverse('cliente_carrito_pagar'))

        intento_anterior.refresh_from_db()
        intento_nuevo = TransbankPago.objects.exclude(pk=intento_anterior.pk).get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(intento_anterior.estado, 'error')
        self.assertEqual(intento_nuevo.token, 'token-nuevo')
        self.assertEqual(intento_nuevo.estado, 'pendiente')
        mock_gateway.assert_called_once()
        mock_create.assert_called_once()

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.create_transaction')
    @patch('carrito.views.get_transaction')
    @patch('carrito.views.transaction_status')
    def test_returning_to_cart_cancels_opened_attempt_and_allows_updated_cart(
        self,
        mock_status,
        mock_gateway,
        mock_create,
    ):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )
        session = self.client.session
        intento_anterior = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-abandonada',
            session_id='sesion-abandonada',
            session_key=session.session_key,
            carrito=session['carrito_compra'],
            monto=Decimal('2500'),
            token='token-abandonado',
            webpay_url='https://webpay3gint.transbank.cl/webpayserver/initTransaction',
            estado='webpay_abierto',
        )
        referencia = signing.dumps(
            {'attempt': intento_anterior.pk},
            salt='carrito.transbank.return',
            compress=True,
        )
        mock_status.return_value = {
            'status': 'INITIALIZED',
            'response_code': 0,
            'buy_order': intento_anterior.buy_order,
            'session_id': intento_anterior.session_id,
            'amount': 2500,
        }

        volver = self.client.post(
            reverse('cliente_webpay_volver_carrito'),
            {'ref': referencia},
        )

        intento_anterior.refresh_from_db()
        self.assertRedirects(volver, reverse('cliente_carrito'))
        self.assertEqual(intento_anterior.estado, 'anulado')
        self.assertEqual(self.client.session['carrito_compra']['productos'], {str(self.producto.pk): 1})

        producto_adicional = Producto.objects.create(
            nombre='Esmalte adicional',
            categoria=self.categoria,
            precio=Decimal('1500'),
            stock=5,
            activo=True,
        )
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[producto_adicional.pk]),
            {'cantidad': 1},
        )
        mock_create.return_value = {
            'token': 'token-nuevo',
            'url': 'https://webpay3gint.transbank.cl/webpayserver/initTransaction',
        }

        reintento = self.client.post(reverse('cliente_carrito_pagar'))

        intento_nuevo = TransbankPago.objects.exclude(pk=intento_anterior.pk).get()
        self.assertEqual(reintento.status_code, 200)
        self.assertEqual(intento_nuevo.estado, 'pendiente')
        self.assertEqual(
            intento_nuevo.carrito['productos'],
            {str(self.producto.pk): 1, str(producto_adicional.pk): 1},
        )
        mock_status.assert_called_once()
        self.assertEqual(mock_gateway.call_count, 2)
        mock_create.assert_called_once()

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.get_transaction')
    @patch('carrito.views.transaction_status')
    def test_returning_to_cart_after_failed_payment_preserves_cart(
        self,
        mock_status,
        mock_gateway,
    ):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )
        self.crear_cita_en_carrito()
        session = self.client.session
        intento = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-rechazada',
            session_id='sesion-rechazada',
            session_key=session.session_key,
            carrito=session['carrito_compra'],
            monto=Decimal('2500'),
            token='token-rechazado',
            estado='webpay_abierto',
        )
        referencia = signing.dumps(
            {'attempt': intento.pk},
            salt='carrito.transbank.return',
            compress=True,
        )
        mock_status.return_value = {
            'status': 'FAILED',
            'response_code': -1,
            'buy_order': intento.buy_order,
            'session_id': intento.session_id,
            'amount': 2500,
        }

        response = self.client.post(
            reverse('cliente_webpay_volver_carrito'),
            {'ref': referencia},
        )

        intento.refresh_from_db()
        self.assertRedirects(response, reverse('cliente_carrito'))
        self.assertEqual(intento.estado, 'rechazado')
        self.assertEqual(self.client.session['carrito_compra']['productos'], {str(self.producto.pk): 1})
        self.assertEqual(self.client.session['carrito_compra']['servicios'], [])
        self.assertFalse(ReservaCitaTemporal.objects.filter(
            session_key=session.session_key,
        ).exists())
        hours = self.client.get(
            reverse('cliente_horas_disponibles'),
            {
                'servicio': self.servicio.pk,
                'profesional': self.profesional.pk,
                'fecha': self.fecha.isoformat(),
            },
        )
        self.assertEqual(hours.json()['hours'], ['10:00'])
        mock_status.assert_called_once_with(mock_gateway.return_value, intento.token)

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.get_transaction')
    @patch('carrito.views.transaction_status')
    def test_returning_to_cart_resumes_authorized_payment_instead_of_cancelling(
        self,
        mock_status,
        mock_gateway,
    ):
        intento = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-autorizada',
            session_id='sesion-autorizada',
            session_key=self.client.session.session_key,
            carrito={},
            monto=Decimal('2500'),
            token='token-autorizado',
            estado='webpay_abierto',
        )
        referencia = signing.dumps(
            {'attempt': intento.pk},
            salt='carrito.transbank.return',
            compress=True,
        )
        mock_status.return_value = {
            'status': 'AUTHORIZED',
            'response_code': 0,
            'buy_order': intento.buy_order,
            'session_id': intento.session_id,
            'amount': 2500,
        }

        response = self.client.post(
            reverse('cliente_webpay_volver_carrito'),
            {'ref': referencia},
        )

        intento.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('cliente_webpay_retorno'), response['Location'])
        self.assertIn('token_ws=token-autorizado', response['Location'])
        self.assertEqual(intento.estado, 'autorizado')
        mock_gateway.assert_called_once()
        mock_status.assert_called_once_with(mock_gateway.return_value, intento.token)

    def test_transbank_callback_with_expired_reference_redirects_to_cart(self):
        response = self.client.get(
            f"{reverse('cliente_webpay_retorno')}?{urlencode({'ref': 'referencia-vencida'})}",
        )

        self.assertRedirects(response, reverse('cliente_carrito'))

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.commit_transaction')
    @patch('carrito.views.get_transaction')
    def test_transbank_callback_approves_and_records_order_once(self, mock_gateway, mock_commit):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )
        session = self.client.session
        intento = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-prueba-1',
            session_id='sesion-prueba-1',
            session_key=session.session_key,
            carrito=session['carrito_compra'],
            monto=Decimal('2500'),
            token='token-integracion',
            estado='webpay_abierto',
        )
        referencia = signing.dumps(
            {'attempt': intento.pk},
            salt='carrito.transbank.return',
            compress=True,
        )
        mock_commit.return_value = {
            'status': 'AUTHORIZED',
            'response_code': 0,
            'buy_order': intento.buy_order,
            'session_id': intento.session_id,
            'amount': 2500,
            'authorization_code': '123456',
        }
        client_sin_sesion = Client()

        response = client_sin_sesion.get(
            f"{reverse('cliente_webpay_retorno')}?{urlencode({
                'ref': quote(referencia, safe=''),
                'token_ws': intento.token,
            })}",
        )
        respuesta_duplicada = client_sin_sesion.post(
            f"{reverse('cliente_webpay_retorno')}?ref={referencia}",
            {'token_ws': intento.token},
        )

        intento.refresh_from_db()
        pedido = Pedido.objects.get(cliente=self.cliente)
        pago = Pago.objects.get(venta__cliente=self.cliente)
        self.assertEqual(response.status_code, 302, response.content.decode())
        self.assertIn(reverse('cliente_compra_resultado', args=[pedido.pk]), response['Location'])
        self.assertEqual(intento.estado, 'aprobado')
        self.assertEqual(intento.pedido_id, pedido.pk)
        self.assertEqual(pago.metodo_pago, 'Webpay Plus')
        self.assertEqual(pago.transaccion_id, intento.buy_order)
        self.assertFalse(PagoSimulado.objects.exists())
        self.assertEqual(respuesta_duplicada.status_code, 302)
        self.assertEqual(Pedido.objects.filter(cliente=self.cliente).count(), 1)
        mock_gateway.assert_called_once()
        mock_commit.assert_called_once_with(mock_gateway.return_value, intento.token)

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    @patch('carrito.views.refund_transaction')
    @patch('carrito.views.commit_transaction')
    @patch('carrito.views.get_transaction')
    def test_transbank_callback_refunds_if_product_reservation_expired(
        self,
        mock_gateway,
        mock_commit,
        mock_refund,
    ):
        self.client.post(
            reverse('cliente_carrito_agregar_producto', args=[self.producto.pk]),
            {'cantidad': 1},
        )
        session = self.client.session
        intento = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-prueba-3',
            session_id='sesion-prueba-3',
            session_key=session.session_key,
            carrito=session['carrito_compra'],
            monto=Decimal('2500'),
            token='token-integracion-expirado',
            estado='webpay_abierto',
        )
        ReservaProductoCarrito.objects.filter(session_key=session.session_key).update(
            vence_en=timezone.now() - timedelta(minutes=1),
        )
        referencia = signing.dumps(
            {'attempt': intento.pk},
            salt='carrito.transbank.return',
            compress=True,
        )
        mock_commit.return_value = {
            'status': 'AUTHORIZED',
            'response_code': 0,
            'buy_order': intento.buy_order,
            'session_id': intento.session_id,
            'amount': 2500,
            'authorization_code': '123456',
        }
        mock_refund.return_value = {'type': 'REVERSED', 'response_code': 0}
        client_sin_sesion = Client()

        response = client_sin_sesion.post(
            f"{reverse('cliente_webpay_retorno')}?ref={referencia}",
            {'token_ws': intento.token},
        )

        intento.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(intento.estado, 'reembolsado')
        self.assertFalse(Pedido.objects.exists())
        self.assertEqual(self.producto.stock, 10)
        mock_refund.assert_called_once_with(mock_gateway.return_value, intento.token, 2500)

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    def test_transbank_cancel_callback_requires_matching_attempt_data(self):
        self.crear_cita_en_carrito()
        session = self.client.session
        intento = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-prueba-2',
            session_id='sesion-prueba-2',
            session_key=session.session_key,
            carrito=session['carrito_compra'],
            monto=Decimal('2500'),
            token='token-integracion-cancelado',
            estado='pendiente',
        )
        referencia = signing.dumps(
            {'attempt': intento.pk},
            salt='carrito.transbank.return',
            compress=True,
        )
        client_sin_sesion = Client()

        respuesta_invalida = client_sin_sesion.post(
            f"{reverse('cliente_webpay_retorno')}?ref={referencia}",
            {
                'TBK_TOKEN': intento.token,
                'TBK_ORDEN_COMPRA': 'otra-orden',
                'TBK_ID_SESION': intento.session_id,
            },
        )
        self.assertEqual(respuesta_invalida.status_code, 400)
        intento.refresh_from_db()
        self.assertEqual(intento.estado, 'pendiente')

        respuesta_cancelada = client_sin_sesion.post(
            f"{reverse('cliente_webpay_retorno')}?ref={referencia}",
            {
                'TBK_TOKEN': intento.token,
                'TBK_ORDEN_COMPRA': intento.buy_order,
                'TBK_ID_SESION': intento.session_id,
            },
        )
        intento.refresh_from_db()
        self.assertEqual(respuesta_cancelada.status_code, 200)
        self.assertEqual(intento.estado, 'anulado')
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(ReservaCitaTemporal.objects.filter(
            session_key=session.session_key,
        ).exists())
        self.assertEqual(self.client.session['carrito_compra']['servicios'], [])

    @override_settings(TRANSBANK_ENVIRONMENT='INTEGRATION')
    def test_transbank_cancel_callback_accepts_get_return(self):
        intento = TransbankPago.objects.create(
            cliente=self.cliente,
            buy_order='orden-prueba-get',
            session_id='sesion-prueba-get',
            session_key='session-test-key-get',
            carrito={},
            monto=Decimal('2500'),
            token='token-integracion-cancelado-get',
            estado='pendiente',
        )
        referencia = signing.dumps(
            {'attempt': intento.pk},
            salt='carrito.transbank.return',
            compress=True,
        )

        response = Client().get(
            f"{reverse('cliente_webpay_retorno')}?{urlencode({
                'ref': quote(referencia, safe=''),
                'TBK_TOKEN': intento.token,
                'TBK_ORDEN_COMPRA': intento.buy_order,
                'TBK_ID_SESION': intento.session_id,
            })}",
        )

        intento.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(intento.estado, 'anulado')
        self.assertFalse(Pedido.objects.exists())
