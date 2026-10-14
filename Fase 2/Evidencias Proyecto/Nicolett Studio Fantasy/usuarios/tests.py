from datetime import datetime, timedelta, time

from config.formatters import formatear_pesos
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import (
    Disponibilidad,
    HistorialReserva,
    ProfesionalCategoria,
    Reserva,
)
from carrito.models import DetallePedido, PagoSimulado, Pedido
from panel_admin.models import Categoria, Producto, Servicio

from .models import Rol, Usuario


class RoleAccessTests(TestCase):
    def setUp(self):
        self.admin_role, _ = Rol.objects.get_or_create(nombre='Admin')
        self.client_role, _ = Rol.objects.get_or_create(nombre='Cliente')

    def crear_admin(self):
        return Usuario.objects.create_superuser(
            email='admin@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Admin',
            apellido_materno='Test',
            telefono='+56912345678',
        )

    def crear_cliente(self):
        return Usuario.objects.create_user(
            email='cliente@example.com',
            password='Cliente123!',
            nombre='Cliente',
            apellido_paterno='Prueba',
            apellido_materno='Prueba',
            telefono='+56987654321',
            rol=self.client_role,
        )

    def test_peso_formatter_uses_periods_as_thousands_separators(self):
        self.assertEqual(
            [
                formatear_pesos(amount)
                for amount in (1000, 10000, 100000, 1000000, 10000000)
            ],
            ['$1.000', '$10.000', '$100.000', '$1.000.000', '$10.000.000'],
        )

    def test_registration_always_creates_client_and_records_terms_acceptance(self):
        response = self.client.post(
            reverse('register'),
            {
                'nombre': 'Valentina',
                'segundo_nombre': '',
                'apellido_paterno': 'Prueba',
                'apellido_materno': 'Cliente',
                'telefono': '+56912345678',
                'email': 'valentina@example.com',
                'password': 'Cliente123!',
                'password_confirm': 'Cliente123!',
                'rol': str(self.admin_role.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        cliente = Usuario.objects.get(email='valentina@example.com')
        self.assertEqual(cliente.rol, self.client_role)
        self.assertFalse(cliente.is_staff)
        self.assertFalse(cliente.is_superuser)
        self.assertIsNotNone(cliente.acepta_terminos_at)
        self.assertLessEqual(cliente.acepta_terminos_at, timezone.now())

    def test_client_login_redirects_to_client_home_and_cannot_open_admin_panel(self):
        cliente = self.crear_cliente()

        response = self.client.post(
            reverse('login'),
            {'email': cliente.email, 'password': 'Cliente123!'},
        )

        self.assertRedirects(response, reverse('cliente_servicios'))
        denied = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(denied.status_code, 403)
        self.assertContains(denied, 'Acceso restringido', status_code=403)
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_admin_login_redirects_to_admin_panel_and_cannot_open_client_home(self):
        administrador = self.crear_admin()

        response = self.client.post(
            reverse('login'),
            {'email': administrador.email, 'password': 'Admin123!Test'},
        )

        self.assertRedirects(response, reverse('admin_dashboard'))
        denied = self.client.get(reverse('cliente_home'))
        self.assertEqual(denied.status_code, 403)
        self.assertContains(denied, 'Acceso restringido', status_code=403)

    def test_staff_record_cannot_access_client_or_admin_views(self):
        rol_personal, _ = Rol.objects.get_or_create(nombre='Colaborador')
        personal = Usuario.objects.create_user(
            email='personal@example.com',
            password=None,
            nombre='Personal',
            apellido_paterno='Prueba',
            apellido_materno='Prueba',
            telefono='+56911111111',
            rol=rol_personal,
            is_staff=True,
        )
        self.client.force_login(personal)

        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 403)
        self.assertEqual(self.client.get('/admin/').status_code, 403)
        self.assertEqual(self.client.get(reverse('cliente_home')).status_code, 403)

    def test_unauthenticated_admin_panel_request_returns_to_site_login(self):
        response = self.client.get(reverse('admin_dashboard'))

        self.assertRedirects(response, reverse('login'))

    def test_customer_sections_render_shared_sidebar_and_highlight_current_link(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        section_names = (
            'cliente_sobre_nosotros',
            'cliente_servicios',
            'cliente_productos',
            'cliente_agendamiento',
            'cliente_gestionar_citas',
        )

        for name in section_names:
            with self.subTest(section=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Hola,')
                self.assertContains(response, cliente.nombre)
                self.assertContains(response, 'Cerrar sesión')
                self.assertContains(response, f'href="{reverse(name)}"')
                self.assertContains(response, 'aria-current="page"')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertContains(response, 'sticky top-14')
                self.assertNotContains(response, 'fixed bottom-0 left-0 top-14')
                self.assertContains(
                    response,
                    f'<a href="{reverse("cliente_servicios")}" aria-label="Ir a Servicios"',
                )
                self.assertContains(
                    response,
                    f'<a href="{reverse("cliente_sobre_nosotros")}"',
                )
                self.assertNotContains(response, '> Inicio</a>')
                self.assertContains(response, '© 2026 Nicolett Studio Fantasy')
        self.assertNotContains(self.client.get(reverse('cliente_gestionar_citas')), 'fa-clock-rotate-left')
        legacy_history = self.client.get(reverse('cliente_historial'))
        self.assertRedirects(legacy_history, f"{reverse('cliente_gestionar_citas')}?tab=historial")
        self.assertEqual(self.client.get(reverse('cliente_cancelar_cita')).status_code, 200)

    def test_customers_only_see_active_services_and_products(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.create(nombre='Cabello', tipo='Tratamientos')
        servicio = Servicio.objects.create(
            nombre='Corte de prueba',
            categoria=categoria,
            descripcion='Servicio de prueba para clientes.',
            precio=15000,
            duracion_minutos=45,
            activo=True,
        )
        Servicio.objects.create(
            nombre='Servicio oculto',
            categoria=categoria,
            descripcion='No debe aparecer al cliente.',
            precio=10000,
            duracion_minutos=30,
            activo=False,
        )
        servicio_caro = Servicio.objects.create(
            nombre='Masaje de prueba',
            categoria=categoria,
            precio=20000,
            duracion_minutos=60,
            activo=True,
            imagen_url='servicios/masaje-prueba.jpg',
        )
        servicio_sin_horarios = Servicio.objects.create(
            nombre='Servicio sin horarios',
            categoria=categoria,
            precio=11000,
            duracion_minutos=30,
            activo=True,
        )
        rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
        profesional = Usuario.objects.create_user(
            email='profesional.catalogo@example.com',
            password='Colaborador123!',
            nombre='Profesional',
            apellido_paterno='Prueba',
            apellido_materno='Catálogo',
            telefono='+56911112222',
            rol=rol_colaborador,
        )
        ProfesionalCategoria.objects.create(
            profesional=profesional,
            categoria_id=categoria.pk,
        )
        fecha = timezone.localdate() + timedelta(days=7)
        for servicio_con_horarios in (servicio, servicio_caro):
            inicio = time(10, 0)
            fin = (
                datetime.combine(fecha, inicio)
                + timedelta(minutes=servicio_con_horarios.duracion_minutos)
            ).time()
            Disponibilidad.objects.create(
                dia_semana=str(fecha.weekday()),
                hora_inicio=inicio,
                hora_fin=fin,
                activo=True,
                profesional=profesional,
                servicio_id=servicio_con_horarios.pk,
                fecha_especifica=fecha,
                intervalo_minutos=servicio_con_horarios.duracion_minutos,
            )
        producto = Producto.objects.create(
            nombre='Shampoo de prueba',
            categoria=categoria,
            descripcion='Producto de prueba para clientes.',
            precio=9900,
            stock=5,
            activo=True,
            imagen_url='productos/shampoo-prueba.jpg',
        )
        Producto.objects.create(
            nombre='Producto oculto',
            categoria=categoria,
            descripcion='No debe aparecer al cliente.',
            precio=5000,
            stock=1,
            activo=False,
        )
        Producto.objects.create(
            nombre='Producto sin stock',
            categoria=categoria,
            descripcion='No debe aparecer sin stock.',
            precio=5000,
            stock=0,
            activo=True,
        )

        servicios = self.client.get(reverse('cliente_servicios'))
        productos = self.client.get(reverse('cliente_productos'))
        agendamiento = self.client.get(reverse('cliente_agendamiento'))

        self.assertContains(servicios, 'Corte de prueba')
        self.assertContains(servicios, '$15.000')
        self.assertNotContains(servicios, 'Servicio oculto')
        self.assertNotContains(servicios, 'Servicio sin horarios')
        self.assertContains(agendamiento, 'Corte de prueba')
        self.assertNotContains(agendamiento, 'Servicio sin horarios')
        self.assertContains(servicios, 'id="catalog-search"')
        self.assertContains(servicios, 'data-category-filter="Cabello"')
        self.assertNotContains(servicios, 'data-category-filter="Tratamientos"')
        self.assertContains(servicios, 'Añadir al carrito')
        self.assertContains(servicios, 'border-[#e8e0da]')
        self.assertContains(servicios, 'Servicio de prueba para clientes.')
        self.assertContains(servicios, 'Sin imagen disponible')
        self.assertContains(servicios, 'data-image-zoom-action="out"')
        self.assertContains(servicios, 'data-image-zoom-action="in"')
        self.assertContains(servicios, 'data-image-zoom-action="reset"')
        self.assertContains(servicios, 'data-zoomable-image')
        self.assertNotContains(
            servicios,
            'mt-auto flex items-center justify-between border-t border-[#e8e0da] pt-4 text-sm',
        )
        self.assertContains(servicios, 'data-catalog-item')
        self.assertContains(servicios, 'card.style.display = visible ?')
        self.assertContains(servicios, 'No existe ningún ${itemSingular} llamado')
        self.assertContains(servicios, 'aria-label="Servicios"')
        self.assertContains(servicios, 'Precio: mayor a menor')
        ordenados = self.client.get(reverse('cliente_servicios'), {'orden': 'precio_desc'})
        self.assertEqual(list(ordenados.context['servicios']), [servicio_caro, servicio])
        self.assertNotContains(servicios, 'Aquí podrás conocer los servicios disponibles.')
        self.assertNotContains(servicios, 'border-b border-[#e8e0da] p-6 sm:p-8')
        self.assertContains(
            servicios,
            f'action="{reverse("cliente_carrito_agregar_servicio", args=[servicio.pk])}"',
        )
        self.assertContains(productos, 'Shampoo de prueba')
        self.assertContains(productos, '$9.900')
        self.assertNotContains(productos, 'Producto oculto')
        self.assertNotContains(productos, 'Producto sin stock')
        self.assertContains(productos, 'id="catalog-search"')
        self.assertContains(productos, 'data-category-filter="Cabello"')
        self.assertNotContains(productos, 'data-category-filter="Tratamientos"')
        self.assertContains(productos, 'border-[#e8e0da]')
        self.assertContains(productos, 'Producto de prueba para clientes.')
        self.assertContains(productos, 'data-image-zoom-action="in"')
        self.assertContains(productos, 'data-zoomable-image')
        self.assertNotContains(
            productos,
            'mt-auto flex items-center justify-between border-t border-[#e8e0da] pt-4 text-sm',
        )
        self.assertContains(productos, 'data-catalog-item')
        self.assertNotContains(productos, 'Al añadir un producto, su stock se reserva')
        self.assertContains(productos, 'aria-label="Productos"')
        self.assertContains(productos, 'Nombre: Z-A')
        self.assertNotContains(productos, 'Aquí podrás revisar los productos del estudio.')
        self.assertNotContains(productos, 'border-b border-[#e8e0da] p-6 sm:p-8')
        self.assertNotContains(productos, 'overflow-auto bg-[#f7f3f0]')
        self.assertContains(
            productos,
            f'action="{reverse("cliente_carrito_agregar_producto", args=[producto.pk])}"',
        )

    def test_client_about_page_shows_brand_story_and_verified_contact_options(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_sobre_nosotros'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nosotras')
        self.assertContains(response, 'Nicolett Studio Fantasy')
        self.assertContains(response, 'Nuestro origen')
        self.assertContains(response, 'Nuestra misión')
        self.assertContains(response, 'Nuestra visión')
        self.assertContains(response, 'fa-seedling')
        self.assertContains(response, 'https://www.instagram.com/nicolettstudiofantasy/')
        self.assertContains(response, 'https://wa.me/56940322551')
        self.assertContains(response, "Av. Bernardo O'Higgins 979")
        self.assertContains(response, 'nicolettstudio@gmail.com')
        self.assertContains(response, '+56 9 4032 2551')
        self.assertNotContains(response, 'Formulario de contacto')
        self.assertNotContains(response, 'Contactar por WhatsApp')

    def test_customer_home_redirects_to_services(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_home'))

        self.assertRedirects(response, reverse('cliente_servicios'))

    def test_client_profile_fields_are_disabled_with_locked_visual_state(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_configuracion'))

        self.assertContains(response, 'disabled:cursor-not-allowed')
        self.assertContains(response, 'disabled:bg-gray-100')
        self.assertContains(response, 'field.disabled = true')
        self.assertContains(response, 'field.disabled = false')
        self.assertContains(response, 'id="cancel-client-profile"')
        self.assertContains(response, 'profileForm.reset();')

    def test_customer_history_lists_only_their_database_appointments(self):
        cliente = self.crear_cliente()
        otra_cliente = Usuario.objects.create_user(
            email='otra.cliente@example.com',
            password='Cliente123!Test',
            nombre='Otra',
            apellido_paterno='Persona',
            apellido_materno='Prueba',
            telefono='+56987654322',
            rol=self.client_role,
        )
        categoria = Categoria.objects.create(nombre='Cabello', tipo='Cabello')
        servicio = Servicio.objects.create(
            nombre='Cita de historial',
            categoria=categoria,
            descripcion='Servicio reservado.',
            precio=15000,
            duracion_minutos=45,
            activo=True,
        )
        for propietario, nombre in (
            (cliente, 'Cita propia'),
            (otra_cliente, 'Cita privada ajena'),
        ):
            Reserva.objects.create(
                fecha_hora=timezone.now(),
                estado='pendiente',
                origen='cliente',
                cliente=propietario,
                creada_por=propietario,
                servicio_id=servicio.pk,
                cliente_nombre=propietario.nombre,
                cliente_email=propietario.email,
                cliente_telefono=propietario.telefono,
                servicio_nombre=nombre,
                duracion_minutos=45,
            )
        reserva_propia = Reserva.objects.get(cliente=cliente)
        HistorialReserva.objects.create(
            reserva=reserva_propia,
            evento='modificada',
            fecha_hora=timezone.now() - timedelta(days=2),
            servicio_nombre='Servicio anterior',
            profesional_nombre='Profesional anterior',
            estado='confirmada',
        )
        self.client.force_login(cliente)

        response = self.client.get(
            reverse('cliente_gestionar_citas'),
            {'tab': 'historial'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cita propia')
        self.assertContains(response, 'En curso')
        self.assertContains(response, 'Servicio anterior')
        self.assertContains(response, 'Modificado')
        self.assertNotContains(response, 'Cita privada ajena')
        self.assertEqual(len(response.context['reservas_historial']), 1)
        self.assertEqual(len(response.context['historial_completo']), 2)
        self.assertContains(response, 'Descargar ficha técnica (PDF)')

    def test_requested_booking_is_manageable_and_history_status_updates_after_cancellation(self):
        cliente = self.crear_cliente()
        categoria = Categoria.objects.create(nombre='Manicure', tipo='Uñas')
        servicio = Servicio.objects.create(
            nombre='Manicure de prueba',
            categoria=categoria,
            precio=12000,
            duracion_minutos=60,
            activo=True,
        )
        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(days=5),
            estado='pendiente',
            origen='cliente',
            cliente=cliente,
            servicio_id=servicio.pk,
            servicio_nombre=servicio.nombre,
            duracion_minutos=servicio.duracion_minutos,
        )
        self.client.force_login(cliente)

        page = self.client.get(reverse('cliente_gestionar_citas'))

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.content.count(b'Solicitado'), 2)
        self.assertContains(page, 'Modificar')
        self.assertContains(page, f'action="{reverse("cliente_cancelar_reserva", args=[reserva.pk])}"')
        self.assertContains(page, 'Cancelar modificación')

        response = self.client.post(reverse('cliente_cancelar_reserva', args=[reserva.pk]))

        self.assertRedirects(response, reverse('cliente_gestionar_citas'))
        historial = self.client.get(reverse('cliente_gestionar_citas'), {'tab': 'historial'})
        self.assertEqual(historial.content.count(b'Cancelado'), 1)
        self.assertContains(historial, 'border-red-200 bg-red-50 text-red-800')

    def test_public_login_logo_links_to_public_home(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a href="{reverse("home")}" aria-label="Ir al inicio"',
        )
        self.assertContains(response, 'bg-customBg')
        self.assertContains(response, 'grid-cols-[1fr_auto_1fr]')
        self.assertNotContains(response, '>INICIO</a>')

    def test_login_query_selects_registration_tab_on_initial_render(self):
        response = self.client.get(reverse('login'), {'tab': 'register'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['mostrar_registro'])
        self.assertContains(response, 'id="section-login" style="display: none;"')
        self.assertContains(response, 'id="section-register" style="display: block;"')
        self.assertContains(response, 'aria-selected="true"')

    def test_logout_requires_post_clears_session_and_protects_back_navigation(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        protected = self.client.get(reverse('cliente_home'))
        self.assertRedirects(protected, reverse('login'))

    def test_admin_sidebar_highlights_current_section(self):
        administrador = self.crear_admin()
        self.client.force_login(administrador)

        response = self.client.get(reverse('listar_servicios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(
            response,
            'href="{}" class="nav-link active"'.format(reverse('listar_servicios')),
        )

    def test_customer_can_update_account_details_and_password(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        response = self.client.post(
            reverse('cliente_configuracion'),
            {
                'accion': 'perfil',
                'nombre': 'Valentina',
                'segundo_nombre': 'Paz',
                'apellido_paterno': 'Pérez',
                'apellido_materno': 'Rojas',
                'email': 'valentina.perez@example.com',
                'telefono': '+56911112222',
            },
        )

        self.assertRedirects(response, reverse('cliente_configuracion'))
        cliente.refresh_from_db()
        self.assertEqual(cliente.email, 'valentina.perez@example.com')
        self.assertEqual(cliente.nombre, 'Valentina')
        self.assertEqual(cliente.telefono, '+56911112222')

        response = self.client.post(
            reverse('cliente_configuracion'),
            {
                'accion': 'contrasena',
                'password_actual': 'Cliente123!',
                'password_nueva': 'NuevaClave123!',
                'password_confirmacion': 'NuevaClave123!',
            },
        )
        self.assertRedirects(response, reverse('cliente_configuracion'))
        cliente.refresh_from_db()
        self.assertTrue(cliente.check_password('NuevaClave123!'))
        config = self.client.get(reverse('cliente_configuracion'))
        self.assertEqual(config.status_code, 200)
        self.assertContains(config, 'Actualizar contraseña')
        self.assertContains(config, 'Modificar')
        self.assertContains(config, 'disabled')
        self.assertNotContains(config, 'Actualiza tus datos personales y credenciales.')

    def test_customer_account_deletion_anonymizes_history_cancels_bookings_and_releases_email(self):
        cliente = self.crear_cliente()
        categoria = Categoria.objects.create(nombre='Cuidado', tipo='Cuidado')
        servicio = Servicio.objects.create(
            nombre='Servicio reservado',
            categoria=categoria,
            precio=10000,
            duracion_minutos=30,
        )
        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(days=3),
            estado='confirmada',
            origen='cliente',
            cliente=cliente,
            cliente_nombre='Cliente Prueba Prueba',
            cliente_email=cliente.email,
            cliente_telefono=cliente.telefono,
            servicio_id=servicio.pk,
            servicio_nombre=servicio.nombre,
            duracion_minutos=30,
        )
        pedido = Pedido.objects.create(
            cliente=cliente,
            total=10000,
            monto_pagado=10000,
            estado='pagado',
        )
        pago = PagoSimulado.objects.create(
            pedido=pedido,
            monto=10000,
            transaccion_id='customer-delete-payment',
        )
        self.client.force_login(cliente)

        response = self.client.post(
            reverse('cliente_eliminar_cuenta'),
            {'confirmar': 'eliminar'},
        )

        self.assertRedirects(response, reverse('login'))
        cliente.refresh_from_db()
        reserva.refresh_from_db()
        self.assertFalse(cliente.is_active)
        self.assertIsNotNone(cliente.deleted_at)
        self.assertNotEqual(cliente.email, 'cliente@example.com')
        self.assertFalse(cliente.check_password('Cliente123!'))
        self.assertEqual(reserva.estado, 'cancelada')
        self.assertEqual(reserva.cliente_email, '')
        self.assertEqual(reserva.cliente_nombre, 'Cliente anonimizado')
        self.assertTrue(HistorialReserva.objects.filter(
            reserva=reserva,
            evento='cancelada',
        ).exists())
        self.assertTrue(PagoSimulado.objects.filter(pk=pago.pk, pedido=pedido).exists())

        registro = self.client.post(
            reverse('register'),
            {
                'nombre': 'Nueva',
                'segundo_nombre': '',
                'apellido_paterno': 'Cuenta',
                'apellido_materno': 'Cliente',
                'telefono': '+56912345678',
                'email': 'cliente@example.com',
                'password': 'Cliente123!',
                'password_confirm': 'Cliente123!',
            },
        )
        self.assertEqual(registro.status_code, 200)
        self.assertTrue(Usuario.objects.filter(
            email='cliente@example.com',
            is_active=True,
            deleted_at__isnull=True,
        ).exists())

    def test_customer_payment_history_is_private_and_lists_transactions(self):
        cliente = self.crear_cliente()
        otro_cliente = Usuario.objects.create_user(
            email='otra.pago@example.com',
            password='Cliente123!',
            nombre='Otra',
            apellido_paterno='Cliente',
            apellido_materno='Prueba',
            telefono='+56900000000',
            rol=self.client_role,
        )
        pedido = Pedido.objects.create(
            cliente=cliente,
            total=10000,
            monto_pagado=5000,
            estado='abono',
        )
        PagoSimulado.objects.create(
            pedido=pedido,
            monto=5000,
            transaccion_id='transaction-visible',
        )
        DetallePedido.objects.create(
            pedido=pedido,
            tipo='producto',
            nombre='Producto de pago',
            cantidad=2,
            precio_unitario=2500,
            monto_pagado=5000,
            modalidad_pago='no_aplica',
        )
        pedido_ajeno = Pedido.objects.create(
            cliente=otro_cliente,
            total=20000,
            monto_pagado=20000,
            estado='pagado',
        )
        PagoSimulado.objects.create(
            pedido=pedido_ajeno,
            monto=20000,
            transaccion_id='transaction-private',
        )
        self.client.force_login(cliente)

        response = self.client.get(reverse('cliente_historial_pagos'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'transaction-visible')
        self.assertContains(response, 'Pago parcial')
        self.assertContains(response, 'Producto de pago')
        self.assertContains(response, '2 × $2.500')
        self.assertContains(response, '$5.000')
        self.assertNotContains(response, 'transaction-private')
