from django.test import TestCase
from django.urls import reverse


class LandingPageNavigationTests(TestCase):
    def test_landing_gallery_renders_all_instagram_posts_with_one_embed_script(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b'class="instagram-media"'), 6)
        self.assertNotContains(response, 'DbiomKORWY7')
        self.assertNotContains(response, 'DbioRK0R5ze')
        self.assertEqual(response.content.count(b'https://www.instagram.com/embed.js'), 1)

    def test_landing_reviews_navigation_targets_google_reviews_section(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/#resenas"')
        self.assertContains(response, '<section id="resenas"')
        self.assertContains(response, 'Lo que dicen en Google Maps')

    def test_landing_services_section_is_pushed_below_the_extended_hero(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'lg:pb-64')
        self.assertContains(response, '<section id="servicios"')

    def test_shared_header_routes_clients_to_login_and_registration_options(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'bg-customBg')
        self.assertContains(response, 'grid-cols-[1fr_auto_1fr]')
        self.assertContains(response, 'text-customDark transition hover:text-customAccent')
        self.assertContains(response, 'CLIENTES')
        self.assertContains(
            response,
            f'href="{reverse("login")}" aria-label="Ingresar o crear cuenta de cliente"',
        )
        self.assertContains(response, 'fa-bag-shopping')
        self.assertContains(response, 'Contáctanos')
        self.assertContains(response, 'href="/login/" aria-label="Ingresar para abrir el carrito"')
        self.assertNotContains(response, '>CREAR CUENTA</a>')
        self.assertNotContains(response, '>INICIO</a>')
        self.assertContains(response, 'CONTÁCTANOS')
        self.assertContains(response, 'aria-label="Visitar Instagram de Nicolett Studio Fantasy"')
        self.assertContains(response, 'https://www.instagram.com/nicolettstudiofantasy/')
        self.assertContains(response, f'href="{reverse("home")}" aria-label="Ir al inicio"')

        login_response = self.client.get(reverse('login'))
        self.assertContains(login_response, 'id="btn-login"')
        self.assertContains(login_response, 'id="btn-register"')

    def test_footer_social_links_use_icons_and_whatsapp_prefills_welcome_message(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Visitar Instagram de Nicolett Studio Fantasy"')
        self.assertContains(response, 'fa-brands fa-instagram')
        self.assertContains(response, 'aria-label="Escribir a Nicolett Studio Fantasy por WhatsApp"')
        self.assertContains(response, 'fa-brands fa-whatsapp')
        self.assertContains(response, 'href="https://wa.me/56982108409?text=')
        self.assertContains(response, 'Bienvenida%20a%20Nicolett%20Studio%20Fantasy')
        self.assertContains(response, 'Te%20responderemos%20lo%20antes%20posible')
        self.assertNotContains(response, '>Instagram</a>')
        self.assertNotContains(response, '>WhatsApp</a>')

    def test_contact_registration_cta_requests_registration_tab(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            f'href="{reverse("login")}?tab=register" class="inline-block',
        )
