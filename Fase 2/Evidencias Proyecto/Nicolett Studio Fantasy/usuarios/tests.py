from datetime import datetime, timedelta, time
from urllib.parse import parse_qs, urlparse

import re
from urllib.parse import urlparse
from unittest.mock import patch

from django.core import mail
from config.formatters import formatear_pesos
from django.test import TestCase
from django.test.utils import override_settings
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

    def assert_service_category_view_is_empty(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="servicios-semana"')
        self.assertNotContains(response, 'data-service-gallery')
        self.assertContains(response, 'id="serviceBookingCalendar"')
        self.assertContains(response, 'id="serviceBookingForm"')
        self.assertContains(response, 'data-select-service')

    @override_settings(
        DEBUG=True,
        EMAIL_HOST_USER='',
        EMAIL_HOST_PASSWORD='',
        EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend',
    )
    def test_inactive_local_customer_login_shows_activation_link(self):
        cliente = self.crear_cliente()
        cliente.is_active = False
        cliente.save(update_fields=['is_active'])

        response = self.client.post(
            reverse('login'),
            {'email': cliente.email, 'password': 'Cliente123!'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no se envía un correo real')
        self.assertContains(response, 'Prueba local')
        self.assertContains(response, 'Activar mi cuenta')
        self.assertNotContains(response, 'Te hemos enviado un correo')
        self.assertFalse('_auth_user_id' in self.client.session)

        verification_url = response.context['verification_url_local']
        verification_path = urlparse(verification_url).path
        verified = self.client.get(verification_path)
        self.assertEqual(verified.status_code, 200)
        self.assertContains(verified, 'Tu correo fue confirmado')
        cliente.refresh_from_db()
        self.assertTrue(cliente.is_active)

    def test_peso_formatter_uses_periods_as_thousands_separators(self):
        self.assertEqual(
            [
                formatear_pesos(amount)
                for amount in (1000, 10000, 100000, 1000000, 10000000)
            ],
            ['$1.000', '$10.000', '$100.000', '$1.000.000', '$10.000.000'],
        )

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_registration_requires_email_confirmation_before_client_login(self):
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
        self.assertFalse(cliente.is_active)
        self.assertFalse(cliente.is_staff)
        self.assertFalse(cliente.is_superuser)
        self.assertIsNotNone(cliente.acepta_terminos_at)
        self.assertLessEqual(cliente.acepta_terminos_at, timezone.now())
        self.assertContains(response, 'class="success-brand"')
        self.assertContains(response, 'Te hemos enviado un correo')
        self.assertContains(response, 'aria-label="Escribir a Nicolett Studio Fantasy por WhatsApp"')
        self.assertContains(response, 'name="email" placeholder="valentina@ejemplo.cl" value="valentina@example.com"')
        whatsapp_link = re.search(r'href="(https://wa\.me/56982108409\?text=[^"]+)"', response.content.decode()).group(1)
        whatsapp_message = parse_qs(urlparse(whatsapp_link).query)['text'][0]
        self.assertEqual(
            whatsapp_message,
            '✨ ¡Hola! Bienvenida a Nicolett Studio Fantasy 💖\n'
            'Gracias por escribirnos 💌\n'
            'Somos un espacio dedicado a realzar tu belleza con atención 100% personalizada ✨\n'
            '💅 Servicios disponibles:\n'
            '• Uñas\n'
            '• Peluquería 💇‍♀️\n'
            '• Pestañas 👁️\n'
            '• Depilación\n'
            '📍 Atendemos en Buin con previo abono\n'
            '💳 Aceptamos todos los medios de pago\n'
            'Para agendar tu hora, cuéntanos:\n'
            '👉 Qué servicio te interesa\n'
            '👉 Qué día y horario prefieres\n'
            'Te responderemos lo antes posible para coordinar contigo 💕',
        )
        self.assertEqual(len(mail.outbox), 1)
        confirmation_email = mail.outbox[0]
        self.assertEqual(confirmation_email.to, [cliente.email])
        self.assertIn('Nicolett Studio Fantasy', confirmation_email.subject)
        self.assertIn('Nicolett Studio Fantasy', confirmation_email.body)
        self.assertIn('CONFIRMAR MI CORREO', confirmation_email.alternatives[0][0])
        self.assertNotIn('Palumbo', confirmation_email.body)

        inactive_login = self.client.post(
            reverse('login'),
            {'email': cliente.email, 'password': 'Cliente123!'},
        )
        self.assertEqual(inactive_login.status_code, 200)
        self.assertContains(inactive_login, 'verifica tu cuenta')
        self.assertFalse('_auth_user_id' in self.client.session)

        verification_url = re.search(r'http://testserver\S+', confirmation_email.body).group(0)
        verification_path = urlparse(verification_url).path
        verified = self.client.get(verification_path)
        self.assertEqual(verified.status_code, 200)
        self.assertContains(verified, 'Tu correo fue confirmado')
        cliente.refresh_from_db()
        self.assertTrue(cliente.is_active)
        self.assertEqual(len(mail.outbox), 2)
        activation_email = mail.outbox[1]
        self.assertIn('cuenta está activa', activation_email.subject)
        self.assertIn(cliente.email, activation_email.body)
        self.assertIn('http://testserver/login/', activation_email.body)
        self.assertIn('Nicolett Studio Fantasy', activation_email.alternatives[0][0])
        self.assertIn('INICIAR SESIÓN', activation_email.alternatives[0][0])
        self.assertNotIn('Palumbo', activation_email.body)
        self.client.get(verification_path)
        self.assertEqual(len(mail.outbox), 2)

        login_response = self.client.post(
            reverse('login'),
            {'email': cliente.email, 'password': 'Cliente123!'},
        )
        self.assertRedirects(login_response, reverse('cliente_home'))

    def test_registration_without_email_configuration_is_rejected_outside_debug(self):
        with override_settings(EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='', DEBUG=False):
            response = self.client.post(
                reverse('register'),
                {
                    'nombre': 'Valentina',
                    'apellido_paterno': 'Prueba',
                    'apellido_materno': 'Cliente',
                    'telefono': '+56912345678',
                    'email': 'sin.correo@example.com',
                    'password': 'Cliente123!',
                    'password_confirm': 'Cliente123!',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'EMAIL_HOST_USER y EMAIL_HOST_PASSWORD')
        self.assertContains(response, 'el correo del salón que envía los mensajes')
        self.assertContains(response, 'se enviará al correo que ingresaste en el formulario')
        self.assertFalse(Usuario.objects.filter(email='sin.correo@example.com').exists())

    def test_local_registration_without_smtp_creates_account_and_shows_activation_link(self):
        with override_settings(
            DEBUG=True,
            EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend',
            EMAIL_HOST_USER='',
            EMAIL_HOST_PASSWORD='',
        ):
            response = self.client.post(
                reverse('register'),
                {
                    'nombre': 'Valentina',
                    'apellido_paterno': 'Prueba',
                    'apellido_materno': 'Cliente',
                    'telefono': '+56912345678',
                    'email': 'prueba.local@example.com',
                    'password': 'Cliente123!',
                    'password_confirm': 'Cliente123!',
                },
            )

        self.assertEqual(response.status_code, 200)
        cliente = Usuario.objects.get(email='prueba.local@example.com')
        self.assertFalse(cliente.is_active)
        self.assertContains(response, 'No se envió un correo real.')
        self.assertContains(response, 'Activar mi cuenta')
        verification_url = response.context['verification_url_local']
        verification_path = urlparse(verification_url).path
        activation_response = self.client.get(verification_path)

        self.assertEqual(activation_response.status_code, 200)
        cliente.refresh_from_db()
        self.assertTrue(cliente.is_active)

    def test_verified_account_stays_active_if_activation_email_cannot_be_sent(self):
        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            EMAIL_HOST_USER='pruebas@example.com',
            EMAIL_HOST_PASSWORD='password-de-prueba',
            DEFAULT_FROM_EMAIL='pruebas@example.com',
        ):
            self.client.post(
                reverse('register'),
                {
                    'nombre': 'Camila',
                    'apellido_paterno': 'Prueba',
                    'apellido_materno': 'Cliente',
                    'telefono': '+56912345678',
                    'email': 'camila.activada@example.com',
                    'password': 'Cliente123!',
                    'password_confirm': 'Cliente123!',
                },
            )
            confirmation_url = re.search(
                r'http://testserver\S+',
                mail.outbox[0].body,
            ).group(0)

        with override_settings(EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD=''):
            response = self.client.get(urlparse(confirmation_url).path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tu cuenta quedó activa')
        self.assertTrue(Usuario.objects.get(email='camila.activada@example.com').is_active)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_registration_accepts_local_mobile_and_stores_international_format(self):
        response = self.client.post(
            reverse('register'),
            {
                'nombre': 'Camila',
                'apellido_paterno': 'Prueba',
                'apellido_materno': 'Cliente',
                'telefono': '912345678',
                'email': 'camila@example.com',
                'password': 'Cliente123!',
                'password_confirm': 'Cliente123!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Usuario.objects.get(email='camila@example.com').telefono, '+56912345678')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_registration_accepts_long_passwords_generated_by_password_managers(self):
        password = 'Secure!GeneratedPass123'
        response = self.client.post(
            reverse('register'),
            {
                'nombre': 'Camila',
                'apellido_paterno': 'Prueba',
                'apellido_materno': 'Cliente',
                'telefono': '912345678',
                'email': 'camila.password@example.com',
                'password': password,
                'password_confirm': password,
            },
        )

        self.assertEqual(response.status_code, 200)
        cliente = Usuario.objects.get(email='camila.password@example.com')
        self.assertTrue(cliente.check_password(password))

    def test_registration_rejects_incomplete_phone(self):
        response = self.client.post(
            reverse('register'),
            {
                'nombre': 'Camila',
                'apellido_paterno': 'Prueba',
                'apellido_materno': 'Cliente',
                'telefono': '+5691234567',
                'email': 'camila@example.com',
                'password': 'Cliente123!',
                'password_confirm': 'Cliente123!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ingresa un teléfono chileno válido')
        self.assertFalse(Usuario.objects.filter(email='camila@example.com').exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_password_recovery_sends_link_and_changes_password(self):
        cliente = self.crear_cliente()
        response = self.client.post(
            reverse('password_recovery'),
            {'email': cliente.email},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enviamos un enlace')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cliente.email])
        link = re.search(r'http://testserver\S+', mail.outbox[0].body).group(0)
        reset_path = urlparse(link).path

        self.assertEqual(self.client.get(reset_path).status_code, 200)
        response = self.client.post(
            reset_path,
            {'password': 'NuevaClave123!', 'password_confirm': 'NuevaClave123!'},
        )

        self.assertContains(response, 'Tu contraseña se actualizó correctamente')
        cliente.refresh_from_db()
        self.assertTrue(cliente.check_password('NuevaClave123!'))
        self.assertEqual(self.client.get(reset_path).status_code, 400)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_password_recovery_reports_unregistered_email_without_sending(self):
        response = self.client.post(
            reverse('password_recovery'),
            {'email': 'desconocida@example.com'},
        )

        self.assertContains(response, 'No existe una cuenta registrada')
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_terms_link_opens_terms_and_privacy_page(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, reverse('terminos_privacidad'))
        terms = self.client.get(reverse('terminos_privacidad'))
        self.assertContains(terms, 'política de privacidad')
        self.assertContains(terms, 'Datos personales que se utilizan')
        self.assertContains(terms, 'aria-label="Índice de términos y privacidad"')
        self.assertContains(terms, 'position: fixed')
        self.assertContains(terms, '.topbar {\n            position: sticky;')
        self.assertContains(terms, '.section-card ul { list-style: disc; }')
        self.assertContains(terms, '.section-card ol { list-style: decimal; }')
        self.assertContains(terms, 'line-height: 1.9')
        self.assertNotContains(terms, '<header class="hero">')
        self.assertContains(terms, 'id="servicios" data-toc-section')
        self.assertContains(terms, 'id="derechos" data-toc-section')
        self.assertContains(terms, 'atPageEnd')
        self.assertContains(terms, 'position: fixed')
        self.assertContains(terms, 'font-size: clamp(30px, 3vw, 36px)')
        self.assertContains(terms, '<nav class="section-index"')
        self.assertContains(terms, '.section-card h2')
        self.assertContains(terms, '© 2026 Nicolett Studio Fantasy')
        self.assertContains(terms, 'Todos los derechos reservados')
        self.assertContains(terms, 'aria-label="Escribir a Nicolett Studio Fantasy por WhatsApp"')
        self.assertContains(terms, 'mailto:nicolettstudio@gmail.com')
        self.assertContains(terms, 'href="https://wa.me/56940322551?text=')
        self.assertIn(
            'consulta sobre Nicolett Studio Fantasy',
            parse_qs(urlparse(terms.context['whatsapp_legal_url']).query)['text'][0],
        )
        self.assertContains(terms, 'no procesa un cobro bancario real')
        self.assertContains(terms, 'funcionamiento del sitio, tu cuenta u otra dificultad técnica')
        self.assertNotContains(terms, 'Volver a Nicolett Studio Fantasy')

    def test_registration_brand_and_password_manager_autocomplete_are_available(self):
        response = self.client.get(reverse('login'), {'tab': 'register'})

        self.assertContains(response, 'Crea una cuenta en')
        self.assertContains(response, 'Nicolett Studio Fantasy')
        self.assertContains(response, 'id="reg-password" name="password" placeholder="Mínimo 8 caracteres" required minlength="8" autocomplete="new-password"')
        self.assertContains(response, 'id="reg-password-confirm" name="password_confirm" placeholder="Repetir contraseña" required minlength="8" autocomplete="new-password"')
        self.assertContains(response, 'id="telefono-feedback" class="registration-feedback" role="status" aria-live="polite"')
        self.assertContains(response, 'id="password-feedback" class="registration-feedback" role="status" aria-live="polite"')
        self.assertContains(response, "feedback.style.backgroundColor = '#f8d7da';")
        self.assertContains(response, "feedback.style.backgroundColor = '#d4edda';")
        self.assertNotContains(response, 'background: #383d40 !important;')
        self.assertNotContains(response, 'background: #fae9cf !important;')
        self.assertContains(response, 'const regex = /^(?=.*[A-Z])(?=.*\\d)(?=.*[^A-Za-z0-9]).{8,}$/;')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_client_login_sends_email_and_cannot_open_admin_panel(self):
        cliente = self.crear_cliente()

        response = self.client.post(
            reverse('login'),
            {'email': cliente.email, 'password': 'Cliente123!'},
        )

        self.assertRedirects(response, reverse('cliente_home'))
        self.assertEqual(len(mail.outbox), 1)
        login_email = mail.outbox[0]
        self.assertEqual(login_email.to, [cliente.email])
        self.assertIn('Nuevo inicio de sesión', login_email.subject)
        self.assertIn('Nicolett Studio Fantasy', login_email.body)
        self.assertIn('hora de Chile', login_email.body)
        self.assertIn('Nuevo inicio de sesión', login_email.alternatives[0][0])
        denied = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(denied.status_code, 403)
        self.assertContains(denied, 'Acceso restringido', status_code=403)
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='pruebas@example.com',
        EMAIL_HOST_PASSWORD='password-de-prueba',
        DEFAULT_FROM_EMAIL='pruebas@example.com',
    )
    def test_admin_login_redirects_to_admin_panel_and_cannot_open_client_home(self):
        administrador = self.crear_admin()

        response = self.client.post(
            reverse('login'),
            {'email': administrador.email, 'password': 'Admin123!Test'},
        )

        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertEqual(len(mail.outbox), 0)
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
                self.assertContains(response, '<strong class="text-white">Cliente</strong>')
                self.assertContains(response, 'Cerrar sesión')
                self.assertNotContains(response, 'Historial de pagos')
                self.assertContains(response, 'https://www.instagram.com/nicolettstudiofantasy/')
                self.assertContains(response, 'https://wa.me/56982108409')
                self.assertContains(response, 'method="post" class="mt-auto px-5 pb-2 pt-6"')
                self.assertContains(response, 'w-[min(82vw,280px)]')
                self.assertContains(response, 'lg:w-[240px]')
                self.assertContains(response, 'transition-[width] duration-200')
                self.assertContains(response, 'px-5 py-3 text-sm no-underline transition-colors')
                self.assertContains(response, 'w-5 text-center text-base text-[#bd8c43]')
                self.assertContains(response, 'border border-[#e07a5f]/35 bg-[#e07a5f]/10')
                self.assertContains(response, 'id="clientServicesToggle"')
                self.assertContains(response, 'id="clientServicesSubmenu"')
                if name == 'cliente_gestionar_citas':
                    self.assertContains(response, 'client-bookings-page')
                    self.assertNotContains(response, '<nav class="client-bookings-topnav')
                    self.assertContains(response, 'client-bookings-main min-h-[calc(100vh-64px)]')
                    self.assertContains(response, 'class="client-bookings-frame mx-auto w-full max-w-5xl p-4 sm:p-6"')
                    self.assertContains(response, 'client-bookings-corner-bottom-right')
                    self.assertContains(response, 'client-bookings-tabs')
                    self.assertContains(response, 'client-bookings-empty')
                    self.assertContains(response, 'client-bookings-cta')
                    self.assertContains(response, 'client-bookings-download')
                if name in ('cliente_home', 'cliente_sobre_nosotros'):
                    self.assertContains(response, 'client-about-page')
                nosotras_link = re.search(
                    rf'<a href="{re.escape(reverse("cliente_home"))}" title="Nosotras"(?P<attributes>[^>]*)>',
                    response.content.decode(),
                )
                self.assertIsNotNone(nosotras_link)
                self.assertEqual(
                    'aria-current="page"' in nosotras_link.group('attributes'),
                    name in ('cliente_home', 'cliente_sobre_nosotros'),
                )
                self.assertContains(response, 'aria-label="Servicios disponibles"')
                self.assertContains(response, 'id="clientProductsToggle"')
                self.assertContains(response, 'id="clientProductsSubmenu"')
                for categoria in response.context['categorias_cliente_servicios']:
                    self.assertContains(
                        response,
                        f'?categoria={categoria.pk}#servicios-semana',
                    )
                for categoria in response.context['categorias_cliente_productos']:
                    self.assertContains(
                        response,
                        f'?categoria={categoria.pk}"',
                    )
                self.assertContains(response, 'Servicios y citas')
                self.assertContains(response, 'aria-current="page"')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertContains(response, 'lg:fixed lg:inset-y-0 lg:left-0')
                self.assertNotContains(response, 'Todos los derechos reservados')
                self.assertNotContains(response, 'class="client-topbar-brand')
                self.assertContains(response, 'aria-label="Nicolett Studio, ir a Nosotras"')
                self.assertNotContains(response, '> Inicio</a>')
        self.assertNotContains(self.client.get(reverse('cliente_gestionar_citas')), 'fa-clock-rotate-left')
        legacy_history = self.client.get(reverse('cliente_historial'))
        self.assertRedirects(legacy_history, f"{reverse('cliente_gestionar_citas')}?tab=historial")
        self.assertEqual(self.client.get(reverse('cliente_cancelar_cita')).status_code, 200)

    def test_depilation_category_view_is_empty(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Servicio.objects.get(nombre='Rostro completo').categoria
        servicios = Servicio.objects.filter(categoria=categoria, activo=True)

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value=set(servicios.values_list('pk', flat=True)),
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertEqual(response.context['categoria_seleccionada_id'], categoria.pk)
        self.assertEqual(response.context['servicios'].count(), servicios.count())

    def test_lash_brow_category_view_is_empty(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.get(nombre='Lash & brow', tipo='servicio')
        servicios = list(Servicio.objects.filter(categoria=categoria, activo=True))

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk for servicio in servicios},
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertEqual(response.context['categoria_seleccionada_id'], categoria.pk)
        self.assertEqual(
            {servicio.nombre for servicio in response.context['servicios']},
            {servicio.nombre for servicio in servicios},
        )

    def test_nail_care_category_view_is_empty(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Servicio.objects.get(nombre='Permanente').categoria
        servicios = list(Servicio.objects.filter(categoria=categoria, activo=True))

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk for servicio in servicios},
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertEqual(response.context['categoria_seleccionada_id'], categoria.pk)
        self.assertEqual(
            {servicio.nombre for servicio in response.context['servicios']},
            {servicio.nombre for servicio in servicios},
        )

    def test_service_category_link_filters_by_category_id(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Servicio.objects.get(nombre='Permanente').categoria
        servicio = Servicio.objects.create(
            nombre='Service category test',
            categoria=categoria,
            descripcion='Test description',
            precio=18000,
            duracion_minutos=60,
            activo=True,
        )

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk},
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertEqual(response.context['categoria_seleccionada_id'], categoria.pk)
        self.assertIn(servicio.pk, {
            item.pk for item in response.context['servicios']
        })
        self.assertTrue(all(
            item.categoria_id == categoria.pk
            for item in response.context['servicios']
        ))

    def test_service_category_view_has_no_gallery_or_booking_controls(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.get(nombre='Cortes & estilos', tipo='servicio')

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value=Servicio.objects.filter(activo=True).values_list('pk', flat=True),
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertEqual(response.context['categoria_seleccionada_id'], categoria.pk)

    def test_treatment_category_is_empty_and_service_remains_bookable(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.create(
            nombre='Tratamientos prueba',
            tipo='servicio',
        )
        servicio = Servicio.objects.create(
            nombre='Tratamiento reservable de prueba',
            categoria=categoria,
            descripcion='Tratamiento capilar para prueba.',
            precio=22000,
            duracion_minutos=60,
            activo=True,
        )
        colaborador_role, _ = Rol.objects.get_or_create(nombre='Colaborador')
        colaborador = Usuario.objects.create_user(
            email='colaborador.tratamientos@example.com',
            password='Colaborador123!',
            nombre='Colaborador',
            apellido_paterno='Tratamientos',
            apellido_materno='Prueba',
            telefono='+56911112222',
            rol=colaborador_role,
        )
        ProfesionalCategoria.objects.create(
            profesional=colaborador,
            categoria_id=categoria.pk,
        )

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk},
        ):
            category_response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )
            booking_response = self.client.get(
                reverse('cliente_agendamiento'),
                {'servicio': servicio.pk},
            )

        self.assert_service_category_view_is_empty(category_response)
        self.assertEqual(
            [item.pk for item in category_response.context['servicios']],
            [servicio.pk],
        )
        self.assertContains(booking_response, f'<option value="{servicio.pk}" selected>')

    def test_treatment_category_has_no_flyer_booking_buttons(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.get(
            nombre='Tratamientos capilares',
            tipo='servicio',
        )

        response = self.client.get(
            reverse('cliente_servicios'),
            {'categoria': categoria.pk},
        )

        self.assert_service_category_view_is_empty(response)
        self.assertEqual(response.context['categoria_seleccionada_id'], categoria.pk)

    def test_service_category_navigation_keeps_services_submenu_open(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        for categoria in ('corte', 'tratamientos', 'manos'):
            with self.subTest(categoria=categoria):
                respuesta = self.client.get(
                    reverse('cliente_servicios'),
                    {'categoria': categoria},
                )

                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(
                    respuesta,
                    'id="clientServicesToggle" aria-expanded="true"',
                )
                self.assertContains(
                    respuesta,
                    'aria-label="Servicios disponibles">',
                )
                self.assertNotContains(
                    respuesta,
                    'aria-label="Servicios disponibles" hidden',
                )

    def test_client_category_menus_follow_active_catalog_categories(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria_servicio = Categoria.objects.create(
            nombre='Categoría de servicio nueva',
            tipo='servicio',
            activa=True,
        )
        categoria_producto = Categoria.objects.create(
            nombre='Categoría de producto nueva',
            tipo='producto',
            activa=True,
        )
        categoria_eliminable = Categoria.objects.create(
            nombre='Categoría de producto eliminable',
            tipo='producto',
            activa=True,
        )
        categoria_inactiva = Categoria.objects.create(
            nombre='Categoría inactiva',
            tipo='servicio',
            activa=False,
        )
        servicio = Servicio.objects.create(
            nombre='Servicio de categoría nueva',
            descripcion='Descripción de prueba',
            duracion_minutos=30,
            precio=10000,
            activo=True,
            categoria=categoria_servicio,
        )

        servicios = self.client.get(reverse('cliente_servicios'))
        self.assertContains(
            servicios,
            f'?categoria={categoria_servicio.pk}#servicios-semana',
        )
        self.assertNotContains(servicios, 'Categoría inactiva')
        self.assertNotContains(servicios, 'Todos los servicios')
        self.assertContains(servicios, 'client-sidebar-submenu a:hover')
        self.assertContains(servicios, 'linear-gradient(180deg, #3e2a1e 0%, #332218 58%, #291b14 100%)')
        self.assertContains(servicios, 'linear-gradient(105deg, #d6b36d, #f0d99f)')
        self.assertContains(servicios, 'rgb(240 217 159 / 16%)')
        self.assertContains(servicios, 'scrollbar-width: none')
        self.assertContains(servicios, "ArrowDown: 48")
        self.assertNotContains(servicios, 'Todos los productos')

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk},
        ):
            servicios_categoria = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria_servicio.pk},
            )
        self.assertEqual(
            [item.pk for item in servicios_categoria.context['servicios']],
            [servicio.pk],
        )
        self.assertContains(servicios_categoria, 'Categoría de servicio nueva')
        self.assertNotContains(servicios_categoria, 'data-service-gallery')
        self.assertNotContains(servicios_categoria, 'AGENDAR CITA')
        self.assertNotContains(servicios_categoria, 'img/')

        productos = self.client.get(reverse('cliente_productos'))
        self.assertNotContains(productos, 'Todos los productos')
        self.assertNotContains(productos, 'Todos los servicios')
        self.assertContains(
            productos,
            f'?categoria={categoria_producto.pk}"',
        )
        self.assertContains(productos, categoria_eliminable.nombre)
        self.assertContains(productos, 'clientProductsSubmenu')

        categoria_producto.nombre = 'Categoría de producto renombrada'
        categoria_producto.save(update_fields=['nombre'])
        productos_actualizados = self.client.get(reverse('cliente_productos'))
        self.assertContains(productos_actualizados, 'Categoría de producto renombrada')
        self.assertNotContains(productos_actualizados, 'Categoría de producto nueva')

        categoria_producto.activa = False
        categoria_producto.save(update_fields=['activa'])
        productos_actualizados = self.client.get(reverse('cliente_productos'))
        self.assertNotContains(productos_actualizados, 'Categoría de producto renombrada')

        categoria_eliminable.delete()
        productos_actualizados = self.client.get(reverse('cliente_productos'))
        self.assertNotContains(productos_actualizados, 'Categoría de producto eliminable')

    def test_service_category_displays_records_calendar_and_color_banner(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.create(
            nombre='Colorimetría',
            tipo='servicio',
            activa=True,
        )
        servicios = [
            Servicio.objects.create(
                nombre=f'Técnica de color {index}',
                descripcion=f'Descripción amplia {index}.',
                precio=20000 + index,
                duracion_minutos=60,
                activo=True,
                categoria=categoria,
            )
            for index in range(5)
        ]

        response = self.client.get(
            reverse('cliente_servicios'),
            {'categoria': categoria.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item.pk for item in response.context['servicios']},
            {item.pk for item in servicios},
        )
        self.assertContains(response, 'img/catalogo/servicios/colorimetria.jpg')
        self.assertContains(response, '<h1 class="mt-1 font-serif text-4xl font-bold text-[#281b14] sm:text-5xl">Colorimetría</h1>')
        self.assertContains(response, 'Productos profesionales seleccionados')
        self.assertContains(response, 'Evaluación personalizada')
        self.assertContains(response, 'Cuidado capilar')
        self.assertContains(response, 'id="serviceBookingCalendar"')
        self.assertContains(response, 'id="servicePageNext"')
        self.assertContains(response, 'grid items-stretch gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]')
        self.assertContains(response, 'grid flex-1 content-start gap-3 xl:grid-cols-2')
        self.assertContains(response, '<details class="service-description text-xs text-[#6b5643]">')
        self.assertContains(response, '.service-description > p')
        self.assertNotContains(response, '<dialog')
        self.assertContains(response, 'id="bookingPreviousMonth" type="button" class="flex h-8 w-8')
        self.assertContains(response, 'Reservar cita')
        self.assertContains(response, 'data-select-service')
        self.assertContains(response, 'aria-label="Imagen no disponible para Técnica de color 0"')
        self.assertContains(response, 'Reservar cita')
        self.assertContains(response, 'Agendamiento y pago seguros')
        self.assertContains(response, 'Página')
        for servicio in servicios:
            self.assertContains(response, servicio.nombre)
            self.assertContains(response, servicio.descripcion)
        self.assertNotContains(response, 'mx-auto max-w-4xl border border-[#ead7bc] bg-white p-8 shadow-sm')
        self.assertNotContains(response, 'Continuar con la cita')
        self.assertNotContains(response, 'class="mx-auto max-w-6xl overflow-hidden border border-[#ead7bc] bg-white shadow-sm"')

    def test_podology_category_is_empty_and_service_remains_bookable(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.create(nombre='Podologia prueba', tipo='servicio')
        servicio = Servicio.objects.create(
            nombre='Podologia de prueba',
            categoria=categoria,
            descripcion='Cuidado experto para consentir tus pies.',
            precio=20000,
            duracion_minutos=60,
            activo=True,
        )

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk},
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )
            booking_response = self.client.get(
                reverse('cliente_agendamiento'),
                {'servicio': servicio.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertContains(booking_response, f'<option value="{servicio.pk}" selected>')

    def test_colorimetry_category_is_empty_and_service_remains_bookable(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.create(nombre='Colorimetria prueba', tipo='servicio')
        servicio = Servicio.objects.create(
            nombre='Colorimetria de prueba',
            categoria=categoria,
            descripcion='Diagnostico personalizado de color.',
            precio=20000,
            duracion_minutos=60,
            activo=True,
        )

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk},
        ):
            response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria.pk},
            )
            booking_response = self.client.get(
                reverse('cliente_agendamiento'),
                {'servicio': servicio.pk},
            )

        self.assert_service_category_view_is_empty(response)
        self.assertContains(booking_response, f'<option value="{servicio.pk}" selected>')

    def test_customers_only_see_active_services_and_products(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria_servicio = Categoria.objects.create(
            nombre='Servicio category test',
            tipo='servicio',
        )
        servicio = Servicio.objects.create(
            nombre='Active service test',
            categoria=categoria_servicio,
            descripcion='Service description.',
            precio=15000,
            duracion_minutos=45,
            activo=True,
        )
        Servicio.objects.create(
            nombre='Inactive service test',
            categoria=categoria_servicio,
            precio=10000,
            duracion_minutos=30,
            activo=False,
        )
        categoria_producto = Categoria.objects.create(
            nombre='Product category test',
            tipo='producto',
        )
        Producto.objects.create(
            nombre='Available product test',
            categoria=categoria_producto,
            descripcion='Product description.',
            precio=9900,
            stock=5,
            activo=True,
        )
        Producto.objects.create(
            nombre='Inactive product test',
            categoria=categoria_producto,
            precio=5000,
            stock=1,
            activo=False,
        )
        Producto.objects.create(
            nombre='Out of stock product test',
            categoria=categoria_producto,
            precio=5000,
            stock=0,
            activo=True,
        )

        with patch(
            'usuarios.views.servicios_con_horarios_disponibles',
            return_value={servicio.pk},
        ):
            services_response = self.client.get(
                reverse('cliente_servicios'),
                {'categoria': categoria_servicio.pk},
            )
            booking_response = self.client.get(
                reverse('cliente_agendamiento'),
                {'servicio': servicio.pk},
            )

        self.assert_service_category_view_is_empty(services_response)
        self.assertEqual(
            [item.pk for item in services_response.context['servicios']],
            [servicio.pk],
        )
        self.assertContains(booking_response, f'<option value="{servicio.pk}" selected>')
        self.assertNotContains(booking_response, 'Inactive service test')

        products_response = self.client.get(
            reverse('cliente_productos'),
            {'categoria': categoria_producto.pk},
        )
        self.assertContains(products_response, 'Available product test')
        self.assertNotContains(products_response, 'Inactive product test')
        self.assertNotContains(products_response, 'Out of stock product test')

    def test_client_about_page_shows_brand_story_and_verified_contact_options(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_sobre_nosotros'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nosotras')
        self.assertContains(response, 'Nicolett Studio Fantasy')
        self.assertContains(response, 'Nuestro origen')
        self.assertContains(response, 'Nuestra misión')
        self.assertContains(response, 'Nuestra visión')
        self.assertContains(response, '.client-about-frame::before')
        self.assertContains(response, '.client-about-card::after')
        self.assertContains(response, 'fa-seedling')
        self.assertContains(response, 'https://www.instagram.com/nicolettstudiofantasy/')
        self.assertContains(response, 'https://wa.me/56940322551')
        self.assertContains(response, "Av. Bernardo O'Higgins 979")
        self.assertContains(response, 'nicolettstudio@gmail.com')
        self.assertContains(response, '+56 9 4032 2551')
        self.assertNotContains(response, 'Formulario de contacto')
        self.assertNotContains(response, 'Contactar por WhatsApp')

    def test_client_whatsapp_links_include_logged_in_name_and_service_categories(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)

        response = self.client.get(reverse('cliente_servicios'))

        mensaje_general = parse_qs(urlparse(response.context['whatsapp_url']).query)['text'][0]
        self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_general)
        self.assertIn('servicios y productos', mensaje_general)
        categorias = response.context['whatsapp_categoria_urls']
        self.assertEqual(
            set(categorias),
            {
                'corte',
                'tratamientos',
                'manos',
                'depilaciones',
                'peinados',
                'coloracion',
                'podologia',
                'lash_brow',
                'cuidado_facial',
                'maquillaje',
            },
        )
        for categoria, nombre in (
            ('corte', 'Corte y Estilo'),
            ('tratamientos', 'Tratamientos capilares'),
            ('manos', 'Manicure y Pedicure'),
            ('depilaciones', 'Depilación'),
            ('peinados', 'Peinados'),
            ('coloracion', 'Colorimetría'),
            ('podologia', 'Podología'),
            ('lash_brow', 'Lash & Brow'),
            ('maquillaje', 'Maquillaje'),
        ):
            mensaje_categoria = parse_qs(
                urlparse(categorias[categoria]).query,
            )['text'][0]
            self.assertIn(nombre.upper(), mensaje_categoria)
            self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_categoria)
        self.assertNotContains(response, 'Consultar por WhatsApp sobre')

        productos = self.client.get(reverse('cliente_productos'))
        mensaje_productos = parse_qs(
            urlparse(productos.context['whatsapp_url']).query,
        )['text'][0]
        self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_productos)
        self.assertIn('servicios y productos', mensaje_productos)

    def test_product_descriptions_are_visible_without_covering_product_actions(self):
        cliente = self.crear_cliente()
        categoria = Categoria.objects.create(nombre='Cuidado capilar', tipo='Productos')
        producto = Producto.objects.create(
            nombre='Producto con foto',
            descripcion='Producto de prueba.',
            imagen_url='productos/prueba.png',
            precio='9900',
            stock=2,
            activo=True,
            categoria=categoria,
        )
        self.client.force_login(cliente)

        response = self.client.get(reverse('cliente_productos'))
        self.assertContains(response, 'Producto de prueba.')
        self.assertNotContains(response, 'data-image-preview')
        self.assertContains(
            response,
            'aria-label="Abrir imagen completa de Producto con foto"',
        )
        self.assertContains(response, 'object-contain p-2')
        self.assertContains(response, 'Consultar por WhatsApp sobre Producto con foto')
        self.assertContains(response, 'Añadir al carrito')

    def test_customer_home_opens_on_about_section_without_footer(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nosotras')
        self.assertContains(response, 'Nuestro origen')
        self.assertContains(response, 'Nuestra misión')
        self.assertContains(response, 'https://www.instagram.com/nicolettstudiofantasy/')
        self.assertContains(response, 'fa-whatsapp')
        self.assertNotContains(response, '<footer class="flex flex-col')

    def test_client_navigation_has_brand_icons_and_red_logout(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_home'))

        self.assertContains(response, 'h-14')
        self.assertContains(response, 'id="clientMenuToggle"')
        self.assertContains(response, 'aria-controls="clientSidebar"')
        self.assertContains(response, 'id="clientMenuBackdrop"')
        self.assertContains(response, 'id="clientSidebarCollapseToggle"')
        self.assertContains(response, 'client-sidebar-tools')
        self.assertContains(response, 'client-sidebar-brand-initial')
        self.assertContains(response, 'nicolett-client-sidebar-collapsed')
        self.assertContains(response, 'positionCategoryPopover')
        self.assertContains(response, 'menu.submenu.style.left')
        self.assertContains(response, 'clientProductsToggle')
        self.assertRegex(
            response.content.decode(),
            r'<div class="client-sidebar-tools[^"]*">[\s\S]*?id="clientSidebarCollapseToggle"',
        )
        self.assertContains(response, 'data-collapsed="false"')
        self.assertContains(response, 'client-sidebar-label')
        self.assertContains(response, 'client-topbar-actions')
        self.assertContains(response, 'Mis citas')
        self.assertNotContains(response, 'Gestionar citas')
        self.assertContains(response, 'client-sidebar[data-open="true"]')
        self.assertContains(response, 'fa-instagram')
        self.assertContains(response, 'https://wa.me/56982108409')
        self.assertContains(response, 'bg-[#e07a5f]/10')

    def test_client_smart_search_suggests_catalog_and_settings_sections(self):
        categoria = Categoria.objects.create(nombre='Cabello', tipo='Tratamientos')
        servicio = Servicio.objects.create(
            nombre='Tratamiento hidratante',
            categoria=categoria,
            descripcion='Hidratación capilar profunda.',
            duracion_minutos=60,
            precio='18000',
            activo=True,
        )
        producto = Producto.objects.create(
            nombre='Mascarilla nutritiva',
            categoria=categoria,
            descripcion='Nutrición capilar.',
            precio='9900',
            stock=4,
            activo=True,
        )
        self.client.force_login(self.crear_cliente())

        address_response = self.client.get(reverse('cliente_busqueda'), {'q': 'direcciones'})
        services_response = self.client.get(reverse('cliente_busqueda'), {'q': 'hidra'})
        product_response = self.client.get(reverse('cliente_busqueda'), {'q': 'mascar'})
        empty_response = self.client.get(reverse('cliente_busqueda'), {'q': 'noexiste'})

        self.assertContains(self.client.get(reverse('cliente_home')), 'No hay coincidencias existentes para')
        address_results = address_response.json()['results']
        self.assertEqual(
            {result['title'] for result in address_results},
            {'Configuración', 'Direcciones de envío', 'Direcciones de facturación'},
        )
        self.assertIn(
            f'#servicio-{servicio.pk}',
            services_response.json()['results'][0]['url'],
        )
        self.assertIn(
            f'#producto-{producto.pk}',
            product_response.json()['results'][0]['url'],
        )
        self.assertEqual(empty_response.json()['results'], [])

    def test_admin_can_preview_customer_catalog_without_purchase_actions(self):
        admin = self.crear_admin()
        categoria = Categoria.objects.create(nombre='Cabello', tipo='Tratamientos')
        Producto.objects.create(
            nombre='Mascarilla de prueba',
            categoria=categoria,
            descripcion='Producto para la vista previa.',
            precio='9900',
            stock=3,
            activo=True,
        )
        self.client.force_login(admin)

        start_response = self.client.get(reverse('admin_vista_cliente'))
        home_response = self.client.get(reverse('cliente_home'))
        products_response = self.client.get(reverse('cliente_productos'))
        settings_response = self.client.get(reverse('cliente_configuracion'))
        deletion_response = self.client.post(
            reverse('cliente_eliminar_cuenta'),
            {'confirmar': 'eliminar'},
        )

        self.assertRedirects(start_response, reverse('cliente_home'))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, 'Vista previa')
        self.assertContains(home_response, 'Volver a Admin')
        self.assertNotContains(home_response, 'id="cart-summary-toggle"')
        self.assertEqual(products_response.status_code, 200)
        self.assertContains(products_response, 'Mascarilla de prueba')
        self.assertNotContains(products_response, 'Añadir al carrito')
        self.assertNotContains(products_response, 'cliente_carrito_agregar_producto')
        self.assertEqual(settings_response.status_code, 403)
        self.assertEqual(deletion_response.status_code, 403)
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)

        exit_response = self.client.get(reverse('admin_salir_vista_cliente'))
        self.assertRedirects(exit_response, reverse('admin_dashboard'))
        self.assertEqual(self.client.get(reverse('cliente_home')).status_code, 403)

    def test_collaborator_can_preview_catalog_read_only_and_return_to_agenda(self):
        rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
        colaborador = Usuario.objects.create_user(
            email='colaborador@example.com',
            password='Colaborador123!',
            nombre='Alejandra',
            apellido_paterno='Garrido',
            apellido_materno='Fuentes',
            telefono='+56987654321',
            rol=rol_colaborador,
        )
        categoria = Categoria.objects.create(nombre='Cabello', tipo='Tratamientos')
        Producto.objects.create(
            nombre='Mascarilla demostración',
            categoria=categoria,
            descripcion='Producto para mostrar.',
            precio='9900',
            stock=3,
            activo=True,
        )
        self.client.force_login(colaborador)

        start = self.client.get(reverse('admin_vista_cliente'))
        home = self.client.get(reverse('cliente_home'))
        products = self.client.get(reverse('cliente_productos'))
        settings = self.client.get(reverse('cliente_configuracion'))
        booking = self.client.get(reverse('cliente_agendamiento'))
        exit_preview = self.client.get(reverse('admin_salir_vista_cliente'))

        self.assertEqual(start.status_code, 302)
        self.assertEqual(start['Location'], reverse('cliente_home'))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'Vista previa de colaborador')
        self.assertContains(home, 'Volver a Vista colaborador')
        self.assertNotContains(home, 'id="cart-summary-toggle"')
        self.assertEqual(products.status_code, 200)
        self.assertContains(products, 'Mascarilla demostración')
        self.assertNotContains(products, 'Añadir al carrito')
        self.assertEqual(settings.status_code, 403)
        self.assertEqual(booking.status_code, 403)
        self.assertRedirects(exit_preview, reverse('colaborador_mi_agenda'))

    def test_smart_search_and_preview_are_restricted_by_role(self):
        self.client.force_login(self.crear_admin())

        search_response = self.client.get(reverse('cliente_busqueda'), {'q': 'mis citas'})
        preview_response = self.client.get(reverse('admin_vista_cliente'))
        preview_search = self.client.get(reverse('cliente_busqueda'), {'q': 'mis citas'})

        self.assertEqual(search_response.status_code, 403)
        self.assertRedirects(preview_response, reverse('cliente_home'))
        self.assertEqual(preview_search.status_code, 200)
        self.assertEqual(preview_search.json()['results'], [])

    def test_client_profile_fields_are_disabled_with_locked_visual_state(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('cliente_configuracion'))

        self.assertContains(response, 'Datos de contacto')
        self.assertContains(response, 'Direcciones de envío')
        self.assertContains(response, 'Direcciones de facturación')
        self.assertContains(response, 'Aún no tienes direcciones de envío guardadas.')
        self.assertContains(response, 'disabled:cursor-not-allowed')
        self.assertContains(response, 'disabled:bg-gray-100')
        self.assertContains(response, 'field.disabled = true')
        self.assertContains(response, 'field.disabled = false')
        self.assertContains(response, 'id="cancel-client-profile"')
        self.assertContains(response, 'profileForm.reset();')
        self.assertContains(response, 'client-settings-main min-h-[calc(100vh-64px)]')
        self.assertContains(response, '.client-settings-main #datos-contacto')
        self.assertContains(response, '.client-settings-main #eliminar-cuenta')
        self.assertContains(response, '.client-settings-main input')
        self.assertContains(response, 'background: linear-gradient(145deg, #f5dfa0, #e8c66e) !important')
        self.assertContains(response, 'background-color: #fff1c7 !important')

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
        self.assertContains(response, 'Mis citas')
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

    def test_login_header_hides_store_actions_and_registration_cta(self):
        response = self.client.get(reverse('login'))

        self.assertNotContains(response, 'aria-label="Crear cuenta de cliente"')
        self.assertNotContains(response, '$0')
        self.assertNotContains(response, 'fa-chevron-down')
        self.assertNotContains(response, 'fa-bag-shopping')
        self.assertContains(response, 'bg-[#8b5e28]')
        self.assertContains(response, 'text-white')
        self.assertContains(response, 'id="btn-register"')
        self.assertContains(response, 'fa-brands fa-instagram')

    def test_login_uses_ornamental_gold_layout_and_brand_colored_social_icons(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, '.auth-page .auth-form-panel')
        self.assertContains(response, 'background: #f3dfb4 !important')
        self.assertContains(response, 'max-width: 700px !important')
        self.assertContains(
            response,
            'linear-gradient(120deg, #24170f, #49301d 48%, #21150f) !important',
        )
        self.assertContains(response, 'color: #f3dfb4 !important;')
        self.assertContains(response, 'background: linear-gradient(45deg, #833ab4, #e4405f 55%, #fcaf45)')
        self.assertContains(response, 'color: #25d366 !important')
        self.assertNotContains(response, '<span>Instagram</span>')
        self.assertNotContains(response, '<span>WhatsApp</span>')
        self.assertContains(response, 'text-2xl')
        self.assertContains(response, 'text-[#25D366]')
        self.assertContains(response, 'from-[#833AB4] via-[#E4405F] to-[#FCAF45]')

    def test_login_and_registration_forms_share_submit_button_style(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.content.count(b'class="auth-submit-button"'), 2)

    def test_login_query_selects_registration_tab_on_initial_render(self):
        response = self.client.get(reverse('login'), {'tab': 'register'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['mostrar_registro'])
        self.assertContains(response, 'id="section-login" style="display: none;"')
        self.assertContains(response, 'id="section-register" style="display: block;"')
        self.assertContains(response, 'class="auth-form-panel is-register"')
        self.assertContains(response, 'aria-selected="true"')
        self.assertContains(response, '.auth-page #section-register #form-register .form-input {\n            min-height: 48px;')
        self.assertContains(response, 'class="auth-brand registration-brand"')
        self.assertContains(response, '<h1>Nicolett</h1>')
        self.assertContains(response, '<span>Studio Fantasy</span>')
        self.assertNotContains(response, 'auth-page-register')
        self.assertNotContains(response, 'Crea tu cuenta y disfruta de venta de productos')
        self.assertNotContains(response, 'Ingresa con tu cuenta para gestionar tus citas')
        self.assertContains(response, 'border-radius: 22px;')
        self.assertContains(response, 'overflow-y: auto !important;')
        self.assertContains(response, 'margin: 0 auto;')

    def test_login_page_uses_requested_salon_background_without_schedule_overlay(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'class="auth-page')
        self.assertContains(response, 'class="auth-page-layout"')
        self.assertContains(response, 'margin: 0 auto;')
        self.assertContains(response, 'class="auth-form-panel"')
        self.assertContains(response, 'overflow: hidden !important')
        self.assertContains(response, 'img/login/fondo_login.jpg')
        self.assertContains(response, 'flex: 0 0 40% !important;')
        self.assertContains(response, 'background: #fffdf9 !important;')
        self.assertContains(response, 'Ingresa a tu cuenta en')
        self.assertContains(response, 'id="btn-login"')
        self.assertContains(response, 'id="btn-register"')
        self.assertContains(response, 'border-radius: 0 0 18px 18px;')
        self.assertContains(response, 'border-radius: 18px 18px 0 0;')
        self.assertNotContains(response, 'Agenda abierta')

    def test_authenticated_client_header_hides_sign_in_and_registration_buttons(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'fa-bag-shopping')
        self.assertContains(response, 'aria-label="Abrir carrito"')
        self.assertNotContains(
            response,
            'class="px-5 py-2.5 font-medium tracking-widest text-customDark transition hover:text-customAccent">INICIAR SESIÓN</a>',
        )
        self.assertNotContains(response, 'fa-user-plus')

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
            '<summary class="nav-link active" aria-label="Desplegar categorías de servicios" aria-current="page">',
        )
        self.assertContains(
            response,
            f'class="sidebar-catalog-action active" href="{reverse("listar_servicios")}" aria-current="page">Ver todos</a>',
        )
        self.assertContains(response, 'Cambiar vista')
        self.assertContains(response, reverse('admin_vista_cliente'))
        self.assertContains(response, 'dashboard.css?v=20261103-2')

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

        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            EMAIL_HOST_USER='pruebas@example.com',
            EMAIL_HOST_PASSWORD='password-de-prueba',
            DEFAULT_FROM_EMAIL='pruebas@example.com',
        ):
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
            is_active=False,
            deleted_at__isnull=True,
        ).exists())

    def test_customer_payment_history_route_is_removed(self):
        self.client.force_login(self.crear_cliente())

        response = self.client.get('/cliente/historial-pagos/')

        self.assertEqual(response.status_code, 404)
