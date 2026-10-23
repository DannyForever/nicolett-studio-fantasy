from datetime import datetime, timedelta, time
from urllib.parse import parse_qs, urlparse

import re
from urllib.parse import urlparse

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
                self.assertContains(response, 'https://www.instagram.com/nicolettstudiofantasy/')
                self.assertContains(response, 'https://wa.me/56982108409')
                self.assertContains(response, 'method="post" class="mt-auto px-5 pb-2 pt-6"')
                self.assertContains(response, 'w-[min(82vw,280px)]')
                self.assertContains(response, 'lg:w-[240px]')
                self.assertContains(response, 'transition-[width] duration-200')
                self.assertContains(response, 'px-5 py-3 text-sm no-underline transition-colors')
                self.assertContains(response, 'w-5 text-center text-base text-[#bd8c43]')
                self.assertContains(response, 'border border-[#e07a5f]/35 bg-[#e07a5f]/10')
                self.assertNotContains(response, 'id="client-services-category-panel"')
                self.assertContains(response, 'Lunes a sábado')
                self.assertContains(response, 'Cortes de Cabello')
                self.assertContains(response, 'Tratamientos Capilares')
                self.assertContains(response, 'Manos y Pies')
                self.assertContains(response, 'Depilación/Facial')
                self.assertContains(response, 'Peinados')
                self.assertContains(response, 'Ver todo')
                self.assertNotContains(
                    response,
                    f'href="{reverse("cliente_servicios")}#catalog-grid"',
                )
                self.assertContains(
                    response,
                    f'href="{reverse("cliente_servicios")}?categoria=corte#servicios-semana"',
                )
                active_link_name = 'cliente_home' if name == 'cliente_sobre_nosotros' else name
                active_link = reverse(active_link_name)
                if name == 'cliente_servicios':
                    active_link += '#servicios-semana'
                self.assertContains(response, f'href="{active_link}"')
                self.assertContains(response, 'aria-current="page"')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertContains(response, 'lg:sticky lg:top-16')
                self.assertNotContains(response, 'Todos los derechos reservados')
                self.assertContains(
                    response,
                    f'<a href="{reverse("cliente_home")}" aria-label="Ir a Nosotras"',
                )
                self.assertNotContains(response, '> Inicio</a>')
        self.assertNotContains(self.client.get(reverse('cliente_gestionar_citas')), 'fa-clock-rotate-left')
        legacy_history = self.client.get(reverse('cliente_historial'))
        self.assertRedirects(legacy_history, f"{reverse('cliente_gestionar_citas')}?tab=historial")
        self.assertEqual(self.client.get(reverse('cliente_cancelar_cita')).status_code, 200)

    def test_customers_only_see_active_services_and_products(self):
        cliente = self.crear_cliente()
        self.client.force_login(cliente)
        categoria = Categoria.objects.create(nombre='Cabello', tipo='Tratamientos')
        categoria_depilacion, _ = Categoria.objects.get_or_create(
            nombre='Depilación Trilaser',
            defaults={'tipo': 'Depilación Trilaser'},
        )
        depilacion_facial, _ = Servicio.objects.get_or_create(
            nombre='Depilación facial',
            categoria=categoria_depilacion,
            defaults={
                'descripcion': 'Depilación facial con cera.',
                'precio': 10000,
                'duracion_minutos': 30,
                'activo': True,
            },
        )
        categoria_peluqueria = Categoria.objects.get(nombre='Peluquería')
        peinado_sencillo, _ = Servicio.objects.get_or_create(
            nombre='Peinado sencillo',
            categoria=categoria_peluqueria,
            defaults={
                'descripcion': 'Peinado sencillo para una ocasión especial.',
                'precio': 10000,
                'duracion_minutos': 60,
                'activo': True,
            },
        )
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
        ProfesionalCategoria.objects.get_or_create(
            profesional=profesional,
            categoria_id=depilacion_facial.categoria_id,
        )
        ProfesionalCategoria.objects.get_or_create(
            profesional=profesional,
            categoria_id=peinado_sencillo.categoria_id,
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
        Disponibilidad.objects.create(
            dia_semana=str(fecha.weekday()),
            hora_inicio=time(9, 0),
            hora_fin=time(9, 30),
            activo=True,
            profesional=profesional,
            servicio_id=depilacion_facial.pk,
            fecha_especifica=fecha,
            intervalo_minutos=30,
        )
        Disponibilidad.objects.create(
            dia_semana=str(fecha.weekday()),
            hora_inicio=time(11, 0),
            hora_fin=time(12, 0),
            activo=True,
            profesional=profesional,
            servicio_id=peinado_sencillo.pk,
            fecha_especifica=fecha,
            intervalo_minutos=60,
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

        self.assertNotContains(servicios, 'Corte de prueba')
        self.assertNotContains(servicios, 'Servicio oculto')
        self.assertNotContains(servicios, 'Servicio sin horarios')
        self.assertContains(agendamiento, 'Corte de prueba')
        self.assertNotContains(agendamiento, 'Servicio sin horarios')
        self.assertNotContains(servicios, 'id="catalog-search"')
        self.assertNotContains(servicios, 'id="catalog-sort"')
        self.assertNotContains(servicios, 'id="catalog-results"')
        self.assertContains(servicios, 'id="servicios-semana"')
        self.assertContains(servicios, 'data-services-intro')
        self.assertContains(servicios, 'data-service-gallery-grid')
        self.assertContains(servicios, 'w-full text-center')
        self.assertContains(servicios, 'service-gallery-all lg:grid-cols-3')
        self.assertContains(servicios, 'aspect-ratio: 1 / 1;')
        self.assertContains(servicios, 'data-service-category-filters')
        self.assertContains(servicios, 'aria-label="Filtrar servicios por categoría"')
        self.assertContains(servicios, 'Todos los servicios')
        self.assertContains(servicios, 'bg-[#5a3e27]')
        self.assertContains(servicios, 'data-service-gallery="all tratamientos"')
        self.assertContains(servicios, 'data-service-gallery="all manos"')
        self.assertContains(servicios, 'data-service-gallery="all depilaciones"')
        self.assertContains(servicios, 'src="/static/img/depilacion_facial_galeria.png"')
        self.assertContains(servicios, 'class="h-40 w-full object-cover object-center sm:h-48"')
        self.assertNotContains(servicios, 'Depilación facial')
        self.assertNotContains(servicios, 'Desde $10.000')
        self.assertContains(servicios, 'data-service-gallery="all peinados"')
        self.assertContains(servicios, 'src="/static/img/peinados_galeria.png"')
        self.assertNotContains(servicios, 'Peinado sencillo')
        self.assertContains(servicios, 'data-service-gallery="all coloracion"')
        self.assertContains(servicios, 'data-service-gallery="all podologia"')
        self.assertNotContains(servicios, 'data-service-gallery="all corte" hidden')
        self.assertContains(servicios, 'Atención de lunes a sábado')
        self.assertContains(servicios, 'servicesIntro.hidden = !showIntro')
        self.assertContains(servicios, "galleryGrid.classList.toggle('sm:grid-cols-1', !showIntro)")
        self.assertContains(servicios, 'categoryFilters.hidden = !showIntro')
        tratamientos = self.client.get(
            reverse('cliente_servicios'),
            {'categoria': 'tratamientos'},
        )
        self.assertContains(tratamientos, 'data-service-category-filters hidden')
        self.assertContains(
            tratamientos,
            'class="hidden mt-6 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"',
        )
        self.assertContains(tratamientos, 'data-service-gallery="all tratamientos"')
        self.assertContains(tratamientos, 'data-service-gallery="all corte" hidden')
        cortes = self.client.get(reverse('cliente_servicios'), {'categoria': 'corte'})
        self.assertContains(cortes, 'data-service-category-filters hidden')
        self.assertContains(cortes, 'data-service-gallery="all corte"')
        self.assertContains(cortes, 'class="haircut-photos h-auto w-full object-contain"')
        self.assertContains(cortes, 'data-service-gallery="all tratamientos" hidden')
        self.assertContains(servicios, 'src="/static/img/cortes_estilos_galeria.png"')
        self.assertContains(servicios, 'alt="Cuatro estilos de cortes de cabello"')
        self.assertContains(cortes, 'sm:col-span-2')
        self.assertContains(cortes, 'class="haircut-photos h-auto w-full object-contain"')
        self.assertContains(servicios, 'class="px-2 pb-1 pt-1 text-xs leading-4 text-[#6b5643]"')
        self.assertContains(
            servicios,
            'Cortes modernos y clásicos adaptados a tu tipo de rostro, con secado y peinado incluido.',
        )
        self.assertEqual(
            servicios.content.count(
                'Cortes modernos y clásicos adaptados a tu tipo de rostro, con secado y peinado incluido.'.encode(),
            ),
            1,
        )
        self.assertEqual(
            servicios.content.count(b'src="/static/img/depilacion_facial_galeria.png"'),
            1,
        )
        self.assertContains(servicios, 'src="/static/img/podologia_pies.png"')
        self.assertContains(servicios, 'src="/static/img/manicure_pedicure_galeria.png"')
        self.assertContains(servicios, 'class="h-48 w-full object-cover object-center sm:h-56"')
        self.assertNotContains(servicios, 'src="/static/img/manicure_pedicure.jpg" alt="Podología"')
        self.assertContains(servicios, 'src="/static/img/colorimetria_servicio.png"')
        self.assertContains(servicios, 'src="/static/img/tratamientos_capilares_galeria.png"')
        self.assertContains(servicios, 'Tratamientos capilares</h2>')
        self.assertContains(servicios, 'src="/static/img/peinados_galeria.png"')
        self.assertContains(servicios, 'Peinados con estilo para realzar tu belleza en cada ocasión.')
        self.assertContains(servicios, 'Cuidado experto para consentir tus pies y mantenerlos saludables.')
        self.assertContains(servicios, 'alt="Depilación corporal y facial"')
        self.assertNotContains(servicios, 'Añadir al carrito')
        self.assertContains(cortes, 'Corte de prueba')
        self.assertContains(cortes, 'Servicio de prueba para clientes.')
        self.assertContains(cortes, '$15.000')
        self.assertContains(
            cortes,
            f'action="{reverse("cliente_carrito_agregar_servicio", args=[servicio.pk])}"',
        )
        servicio_catalogo = next(
            item for item in cortes.context['servicios'] if item.pk == servicio.pk
        )
        self.assertContains(
            cortes,
            f'href="{servicio_catalogo.whatsapp_url}" target="_blank" rel="noopener noreferrer"',
        )
        mensaje_servicio = parse_qs(
            urlparse(servicio_catalogo.whatsapp_url).query,
        )['text'][0]
        self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_servicio)
        self.assertIn('CORTE DE PRUEBA', mensaje_servicio)
        depilaciones = self.client.get(
            reverse('cliente_servicios'),
            {'categoria': 'depilaciones'},
        )
        self.assertContains(depilaciones, 'Depilación facial')
        self.assertContains(depilaciones, 'Desde $10.000')
        self.assertContains(
            depilaciones,
            f'action="{reverse("cliente_carrito_agregar_servicio", args=[depilacion_facial.pk])}"',
        )
        peinados = self.client.get(
            reverse('cliente_servicios'),
            {'categoria': 'peinados'},
        )
        self.assertContains(peinados, 'Peinado sencillo')
        self.assertContains(peinados, 'Desde $10.000')
        self.assertContains(
            peinados,
            f'action="{reverse("cliente_carrito_agregar_servicio", args=[peinado_sencillo.pk])}"',
        )
        self.assertContains(servicios, 'Depilación')
        self.assertContains(servicios, 'data-service-gallery="all corte"')
        self.assertContains(servicios, 'Diagnóstico personalizado de color, tinte, balayage y decoloración con productos de alta gama.')
        self.assertNotContains(servicios, 'descuento')
        self.assertNotContains(servicios, 'OFF')
        self.assertContains(servicios, 'data-gallery-filter="corte"')
        self.assertContains(servicios, 'Podología</h2>')
        self.assertContains(servicios, 'function showServiceGallery(category)')
        self.assertContains(servicios, 'gallery.dataset.serviceGallery.split(/\\s+/).includes(')
        self.assertContains(servicios, "showServiceGallery(initialCategory || 'todos')")
        self.assertNotContains(servicios, 'Barbería')
        self.assertContains(servicios, 'border-[#ead7bc]')
        self.assertNotContains(servicios, 'Añadir al carrito')
        self.assertEqual(servicios.content.count('Añadir al carrito'.encode()), 0)
        self.assertNotContains(
            servicios,
            f'action="{reverse("cliente_carrito_agregar_servicio", args=[servicio.pk])}"',
        )
        respuesta_carrito = self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[servicio.pk]),
            {'return_to': reverse('cliente_servicios')},
        )
        self.assertRedirects(respuesta_carrito, reverse('cliente_servicios'))
        respuesta_carrito_depilacion = self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[depilacion_facial.pk]),
            {'return_to': reverse('cliente_servicios')},
        )
        self.assertRedirects(respuesta_carrito_depilacion, reverse('cliente_servicios'))
        respuesta_carrito_peinado = self.client.post(
            reverse('cliente_carrito_agregar_servicio', args=[peinado_sencillo.pk]),
            {'return_to': reverse('cliente_servicios')},
        )
        self.assertRedirects(respuesta_carrito_peinado, reverse('cliente_servicios'))
        self.assertEqual(
            {
                item['id']
                for item in self.client.session['carrito_compra']['servicios']
            },
            {servicio.pk, depilacion_facial.pk, peinado_sencillo.pk},
        )
        self.assertNotContains(
            servicios,
            'mt-auto flex items-center justify-between border-t border-[#ead7bc] pt-4 text-sm',
        )
        self.assertNotContains(servicios, 'id="catalog-grid"')
        self.assertContains(servicios, 'aria-label="Servicios"')
        self.assertNotContains(servicios, 'Buscar servicios')
        self.assertNotContains(servicios, 'resultados')
        ordenados = self.client.get(reverse('cliente_servicios'), {'orden': 'precio_desc'})
        self.assertEqual(
            list(ordenados.context['servicios']),
            [
                servicio_caro,
                servicio,
                servicio_sin_horarios,
                depilacion_facial,
                peinado_sencillo,
            ],
        )
        self.assertNotContains(servicios, 'Aquí podrás conocer los servicios disponibles.')
        self.assertNotContains(servicios, 'border-b border-[#ead7bc] p-6 sm:p-8')
        self.assertContains(servicios, 'href="{}#servicios-semana"'.format(reverse('cliente_servicios')))
        self.assertContains(productos, 'Shampoo de prueba')
        self.assertContains(productos, '$9.900')
        self.assertNotContains(productos, 'Producto oculto')
        self.assertNotContains(productos, 'Producto sin stock')
        self.assertContains(productos, 'id="catalog-search"')
        self.assertContains(productos, 'data-category-filter="Cabello"')
        self.assertNotContains(productos, 'data-category-filter="Tratamientos"')
        self.assertContains(productos, 'border-[#ead7bc]')
        self.assertContains(productos, 'Producto de prueba para clientes.')
        self.assertContains(productos, 'data-image-zoom-action="in"')
        self.assertContains(productos, 'data-zoomable-image')
        self.assertNotContains(
            productos,
            'mt-auto flex items-center justify-between border-t border-[#ead7bc] pt-4 text-sm',
        )
        self.assertContains(productos, 'data-catalog-item')
        self.assertNotContains(productos, 'Al añadir un producto, su stock se reserva')
        self.assertContains(productos, 'aria-label="Productos"')
        self.assertContains(productos, 'Nombre: Z-A')
        self.assertNotContains(productos, 'Aquí podrás revisar los productos del estudio.')
        self.assertNotContains(productos, 'border-b border-[#ead7bc] p-6 sm:p-8')
        self.assertNotContains(productos, 'overflow-auto bg-[#fae9cf]')
        self.assertContains(
            productos,
            f'action="{reverse("cliente_carrito_agregar_producto", args=[producto.pk])}"',
        )
        producto_catalogo = productos.context['productos'][0]
        self.assertContains(
            productos,
            f'href="{producto_catalogo.whatsapp_url}" target="_blank" rel="noopener noreferrer"',
        )
        mensaje_producto = parse_qs(
            urlparse(producto_catalogo.whatsapp_url).query,
        )['text'][0]
        self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_producto)
        self.assertIn('SHAMPOO DE PRUEBA', mensaje_producto)

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
        ):
            mensaje_categoria = parse_qs(
                urlparse(categorias[categoria]).query,
            )['text'][0]
            self.assertIn(nombre.upper(), mensaje_categoria)
            self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_categoria)
            self.assertContains(
                response,
                f'href="{categorias[categoria]}" target="_blank" rel="noopener noreferrer"',
            )
        for label in (
            'Corte y Estilo',
            'Tratamientos capilares',
            'Manicure y Pedicure',
            'Depilación',
            'Peinados',
            'Colorimetría',
            'Podología',
        ):
            self.assertContains(
                response,
                f'aria-label="Consultar por WhatsApp sobre {label}"',
            )

        productos = self.client.get(reverse('cliente_productos'))
        mensaje_productos = parse_qs(
            urlparse(productos.context['whatsapp_url']).query,
        )['text'][0]
        self.assertIn('Hola, soy CLIENTE PRUEBA PRUEBA.', mensaje_productos)
        self.assertIn('servicios y productos', mensaje_productos)

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

        self.assertContains(response, 'h-16')
        self.assertContains(response, 'id="clientMenuToggle"')
        self.assertContains(response, 'aria-controls="clientSidebar"')
        self.assertContains(response, 'id="clientMenuBackdrop"')
        self.assertContains(response, 'id="clientSidebarCollapseToggle"')
        self.assertContains(response, 'client-sidebar-home-row')
        self.assertContains(response, 'data-collapsed="false"')
        self.assertContains(response, 'client-sidebar-label')
        self.assertContains(response, 'client-sidebar[data-open="true"]')
        self.assertContains(response, 'fa-instagram')
        self.assertContains(response, 'https://wa.me/56982108409')
        self.assertContains(response, 'bg-[#e07a5f]/10')

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

    def test_login_footer_shows_brand_colored_social_icons_on_dark_background(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'bg-[#281b14]')
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

    def test_login_page_uses_requested_salon_background_without_schedule_overlay(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'class="auth-page')
        self.assertContains(response, 'class="auth-page-layout"')
        self.assertContains(response, 'class="auth-form-panel"')
        self.assertContains(response, 'overflow: hidden !important')
        self.assertContains(response, 'img/login-salon.jpg')
        self.assertContains(response, 'Ingresa a tu cuenta en')
        self.assertContains(response, 'id="btn-login"')
        self.assertContains(response, 'id="btn-register"')
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
            'href="{}" title="Servicios" aria-label="Servicios" class="nav-link active"'.format(reverse('listar_servicios')),
        )
        self.assertContains(response, 'dashboard.css?v=20261022-1')

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
