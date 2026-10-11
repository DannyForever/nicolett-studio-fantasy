from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Reserva
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

        self.assertRedirects(response, reverse('cliente_home'))
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
            'cliente_home',
            'cliente_servicios',
            'cliente_productos',
            'cliente_agendamiento',
            'cliente_gestionar_citas',
            'cliente_historial',
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
                self.assertContains(
                    response,
                    f'<a href="{reverse("cliente_home")}" aria-label="Ir al inicio de cliente"',
                )
                self.assertContains(response, '© 2026 Nicolett Studio Fantasy')
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
        producto = Producto.objects.create(
            nombre='Shampoo de prueba',
            categoria=categoria,
            descripcion='Producto de prueba para clientes.',
            precio=9900,
            stock=5,
            activo=True,
        )
        Producto.objects.create(
            nombre='Producto oculto',
            categoria=categoria,
            descripcion='No debe aparecer al cliente.',
            precio=5000,
            stock=1,
            activo=False,
        )

        servicios = self.client.get(reverse('cliente_servicios'))
        productos = self.client.get(reverse('cliente_productos'))

        self.assertContains(servicios, 'Corte de prueba')
        self.assertNotContains(servicios, 'Servicio oculto')
        self.assertContains(servicios, 'id="catalog-search"')
        self.assertContains(servicios, 'data-category-filter="Cabello"')
        self.assertContains(servicios, 'data-category-filter="Tratamientos"')
        self.assertContains(servicios, 'data-catalog-item')
        self.assertContains(servicios, 'card.style.display = visible ?')
        self.assertContains(servicios, 'No existe ningún ${itemSingular} llamado')
        self.assertContains(servicios, 'aria-label="Servicios"')
        self.assertContains(
            servicios,
            f'action="{reverse("cliente_carrito_agregar_servicio", args=[servicio.pk])}"',
        )
        self.assertContains(productos, 'Shampoo de prueba')
        self.assertNotContains(productos, 'Producto oculto')
        self.assertContains(productos, 'id="catalog-search"')
        self.assertContains(productos, 'data-category-filter="Cabello"')
        self.assertContains(productos, 'data-category-filter="Tratamientos"')
        self.assertContains(productos, 'data-catalog-item')
        self.assertNotContains(productos, 'Al añadir un producto, su stock se reserva')
        self.assertContains(productos, 'aria-label="Productos"')
        self.assertContains(
            productos,
            f'action="{reverse("cliente_carrito_agregar_producto", args=[producto.pk])}"',
        )

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
        self.client.force_login(cliente)

        response = self.client.get(reverse('cliente_historial'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cita propia')
        self.assertContains(response, 'Pendiente')
        self.assertNotContains(response, 'Cita privada ajena')
        self.assertEqual(response.context['reservas'].count(), 1)

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
