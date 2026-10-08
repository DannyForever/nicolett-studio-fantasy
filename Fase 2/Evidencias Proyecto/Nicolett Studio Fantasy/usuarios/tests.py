from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
            'cliente_historial',
            'cliente_cancelar_cita',
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
