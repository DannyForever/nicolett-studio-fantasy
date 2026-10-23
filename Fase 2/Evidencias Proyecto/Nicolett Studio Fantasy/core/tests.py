from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from django.urls import reverse


class LandingPageNavigationTests(TestCase):
    def test_landing_gallery_renders_all_instagram_posts_with_one_embed_script(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b'class="instagram-media"'), 8)
        self.assertNotContains(response, 'DbiomKORWY7')
        self.assertNotContains(response, 'DbioRK0R5ze')
        self.assertContains(response, 'https://www.instagram.com/reel/DYNLW_xRXgW/')
        self.assertContains(response, 'https://www.instagram.com/reel/DYNKxxLR-c2/')
        self.assertContains(response, 'grid-template-columns: repeat(4, minmax(0, 1fr))')
        self.assertEqual(response.content.count(b'https://www.instagram.com/embed.js'), 1)

    def test_landing_reviews_navigation_targets_google_reviews_section(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/#resenas"')
        self.assertContains(response, '<section id="resenas"')
        self.assertContains(response, 'Lo que dicen en Google Maps')
        self.assertContains(response, 'bg-[#49372b] text-customBg')
        self.assertContains(response, 'text-[#e0bd7c] uppercase mb-3')
        self.assertContains(
            response,
            'linear-gradient(to bottom, #fffaf5 0, #fae9cf 88px, #fae9cf calc(100% - 180px), #49372b 100%)',
        )

    def test_landing_services_section_is_pushed_below_the_extended_hero(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'lg:pb-64')
        self.assertContains(response, '<section id="servicios"')

    def test_landing_services_keeps_the_existing_service_photos_without_promotions(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'Nuestros servicios')
        self.assertNotContains(response, 'Servicios hasta 30% OFF')
        self.assertNotContains(response, 'El cupón se enviará')
        for image_name in (
            'colorimetria.jpg',
            'corte_estilo.jpg',
            'tratamientos.jpg',
            'manicure_pedicure.jpg',
            'maquillaje.jpg',
            'depilacion.jpg',
        ):
            self.assertContains(response, image_name)
        self.assertContains(response, 'alt="Colorimetría en Nicolett Studio"')
        self.assertContains(response, 'src="/static/img/corte_estilo.jpg" alt="Colorimetría en Nicolett Studio"')
        self.assertContains(response, 'src="/static/img/tratamientos.jpg" alt="Corte y estilo en Nicolett Studio"')
        self.assertContains(response, 'src="/static/img/depilacion.jpg" alt="Tratamientos en Nicolett Studio"')
        self.assertContains(response, 'src="/static/img/colorimetria.jpg" alt="Depilación en Nicolett Studio"')

    def test_highlighted_landing_sections_use_warm_white_backgrounds(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            '<section id="inicio" class="grid grid-cols-1 lg:grid-cols-2 pt-10 pb-24 lg:pt-16 lg:pb-64 items-start bg-white">',
        )
        self.assertContains(
            response,
            '<form method="POST" class="space-y-5 bg-white p-9 border border-customBorder shadow-sm">',
        )
        self.assertContains(response, 'class="p-8 bg-white rounded-lg shadow-md')
        self.assertContains(response, '.bg-white {\n            background-color: #ffffff !important;')
        self.assertContains(
            response,
            'linear-gradient(to bottom, #ffffff 0, #fffaf5 28px, #fae9cf 88px, #fae9cf 100%)',
        )

    def test_shared_header_routes_clients_to_login_and_registration_options(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'bg-customBg')
        self.assertContains(response, 'grid-cols-[1fr_auto_1fr]')
        self.assertContains(response, 'text-customDark transition hover:text-customAccent')
        self.assertContains(response, 'CLIENTES')
        self.assertContains(
            response,
            f'href="{reverse("login")}" aria-label="Ingresar a clientes"',
        )
        self.assertNotContains(response, 'aria-label="Crear cuenta de cliente"')
        self.assertNotContains(response, 'CREAR CUENTA')
        self.assertNotContains(response, 'fa-user-plus')
        self.assertContains(response, 'bg-[#8b5e28]')
        self.assertContains(response, 'text-white')
        self.assertEqual(response.content.count(b'sm:h-11 sm:w-40'), 1)
        self.assertNotContains(response, '$0')
        self.assertNotContains(response, 'fa-bag-shopping')
        self.assertContains(response, 'Contáctanos')
        self.assertNotContains(response, '>INICIO</a>')
        self.assertContains(response, 'CONTÁCTANOS')
        self.assertNotContains(response, 'fa-chevron-down')
        self.assertContains(response, 'fa-brands fa-instagram')
        self.assertContains(response, f'href="{reverse("home")}" aria-label="Ir al inicio"')

        login_response = self.client.get(reverse('login'))
        self.assertContains(login_response, 'id="btn-login"')
        self.assertContains(login_response, 'id="btn-register"')

    def test_shared_header_has_accessible_mobile_navigation_toggle(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'id="publicMenuToggle"')
        self.assertContains(response, 'aria-controls="publicMobileNav"')
        self.assertContains(response, 'id="publicMobileNav"')
        self.assertContains(response, 'aria-label="Navegación móvil"')
        self.assertContains(response, 'grid-cols-[1fr_auto]')
        self.assertContains(response, 'w-10 items-center justify-center gap-2 bg-[#8b5e28]')
        self.assertContains(response, 'hidden sm:inline">CLIENTES</span>')
        for section in ('Servicios', 'Nosotras', 'Galería', 'Reseñas', 'Contáctanos'):
            self.assertContains(response, section)

    def test_footer_social_links_use_icons_and_whatsapp_prefills_general_message(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Visitar Instagram de Nicolett Studio Fantasy"')
        self.assertContains(response, 'fa-brands fa-instagram')
        self.assertContains(response, 'aria-label="Escribir a Nicolett Studio Fantasy por WhatsApp"')
        self.assertContains(response, 'fa-brands fa-whatsapp')
        self.assertContains(response, 'href="https://wa.me/56982108409?text=')
        self.assertContains(response, 'target="_blank"')
        mensaje = parse_qs(urlparse(response.context['whatsapp_url']).query)['text'][0]
        self.assertIn('consulta general sobre Nicolett Studio Fantasy', mensaje)
        self.assertIn('servicios, productos, horarios o disponibilidad', mensaje)
        self.assertIn('Mi consulta es:', mensaje)
        self.assertNotContains(response, '<span>Instagram</span>')
        self.assertNotContains(response, '<span>WhatsApp</span>')
        self.assertContains(response, 'text-2xl')
        self.assertContains(response, 'text-[#25D366]')
        self.assertContains(response, 'from-[#833AB4] via-[#E4405F] to-[#FCAF45]')

    def test_contact_registration_cta_requests_registration_tab(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            f'href="{reverse("login")}?tab=register" class="inline-block',
        )
