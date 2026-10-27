from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from django.urls import reverse


class LandingPageNavigationTests(TestCase):
    def test_landing_gallery_uses_the_golden_composition_with_clickable_instagram_links(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<section id="galeria" class="landing-gallery-section"')
        self.assertContains(response, 'img/galeria-completa-dorada.png')
        self.assertContains(response, 'class="landing-gallery-poster"')
        self.assertEqual(response.content.count(b'class="landing-gallery-link landing-gallery-post'), 8)
        self.assertContains(response, 'aria-label="Ver más publicaciones en Instagram"')
        self.assertNotContains(response, 'DbiomKORWY7')
        self.assertNotContains(response, 'DbioRK0R5ze')
        self.assertContains(response, 'https://www.instagram.com/reel/DYNLW_xRXgW/')
        self.assertContains(response, 'https://www.instagram.com/reel/DYNKxxLR-c2/')
        self.assertEqual(response.content.count(b'https://www.instagram.com/embed.js'), 0)

    def test_landing_reviews_navigation_targets_google_reviews_section(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="#resenas"')
        self.assertContains(response, '<section id="resenas" class="landing-reviews-section"')
        self.assertContains(response, 'img/resenas-completas-dorado.png')
        self.assertEqual(response.content.count(b'class="landing-reviews-link landing-reviews-link-'), 3)
        self.assertContains(response, 'aria-label="Leer la reseña de María N. en Google Maps"')
        self.assertContains(response, 'aria-label="Leer la reseña de Betsabe V. en Google Maps"')
        self.assertContains(response, 'aria-label="Leer la reseña de Krishna T. en Google Maps"')
        self.assertContains(response, 'https://maps.app.goo.gl/o64JrZsmmMyn3hDNA')
        self.assertContains(response, 'https://maps.app.goo.gl/LT6kGLR7xncssqS19')
        self.assertContains(response, 'https://maps.app.goo.gl/Hhd1TDNqLEfaotAp7')
        self.assertContains(response, '.landing-gallery-section {\n            scroll-margin-top: 85px;\n            padding: 0;\n            background: #fae9cf;')

    def test_full_width_hero_precedes_about_and_services_posters(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'class="landing-poster-page')
        self.assertContains(response, '.landing-poster {\n            position: relative;\n            width: 100%;\n            overflow: hidden;')
        self.assertContains(response, '.landing-poster {\n            position: relative;\n            width: 100%;\n            overflow: hidden;\n            padding: 88px 0 20px;')
        self.assertContains(response, '.landing-poster-artwork {\n            position: relative;\n            width: min(92%, 1400px);\n            aspect-ratio: 1024 / 415;')
        self.assertContains(response, '#inicio,\n        #servicios {\n            display: block;\n            width: 100%;\n            margin: 0;\n        }\n        #inicio {\n            padding: 88px 0 20px;')
        self.assertContains(response, 'landing-poster-contact-cta')
        content = response.content.decode()
        self.assertLess(content.index('id="inicio"'), content.index('id="nosotras"'))
        self.assertLess(content.index('id="nosotras"'), content.index('id="servicios"'))
        self.assertLess(content.index('id="inicio"'), content.index('id="servicios"'))

    def test_landing_hero_hides_scrollbar_and_keeps_navigation_functional(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, '<html lang="es" class="scroll-smooth landing-poster-document">')
        self.assertContains(response, '.landing-poster-document,\n        .landing-poster-page {\n            scrollbar-width: none !important;')
        self.assertContains(response, 'html::-webkit-scrollbar,\n        body::-webkit-scrollbar {\n            display: none !important;\n            width: 0 !important;\n            height: 0 !important;')
        self.assertContains(response, 'overflow-x: hidden;')
        self.assertContains(response, 'href="#servicios" class="text-customDark transition hover:text-customAccent"')
        self.assertContains(response, 'href="#galeria" class="text-customDark transition hover:text-customAccent"')
        self.assertContains(response, 'aria-label="Ingresar a clientes"')

    def test_golden_navigation_bar_stays_fixed_over_all_page_images(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            '.landing-poster-page > header {\n            display: grid;\n            position: fixed;\n            top: 0;\n            right: 0;\n            left: 0;\n            z-index: 100;',
        )
        self.assertContains(response, 'font-size: 1.5rem;\n            line-height: 1.1;\n            white-space: nowrap;')
        self.assertContains(response, '#nosotras,\n        #servicios,\n        #galeria,\n        #resenas,\n        #contacto {\n            scroll-margin-top: 85px;')
        self.assertContains(response, 'scroll-margin-top: 76px;')
        self.assertContains(response, 'scroll-margin-top: 88px;')
        content = response.content.decode()
        self.assertLess(content.index('<header'), content.index('id="inicio"'))

    def test_navigation_links_follow_page_section_order(self):
        response = self.client.get(reverse('home'))
        content = response.content.decode()

        menu_order = [
            content.index(f'href="#{section}" class="text-customDark transition hover:text-customAccent"')
            for section in ('servicios', 'nosotras', 'galeria', 'resenas')
        ]
        menu_order.append(
            content.index('href="#contacto" class="flex items-center gap-2 text-customDark transition hover:text-customAccent"')
        )
        self.assertEqual(menu_order, sorted(menu_order))
        self.assertLess(content.index('id="servicios"'), content.index('id="galeria"'))
        self.assertLess(content.index('id="galeria"'), content.index('id="resenas"'))
        self.assertLess(content.index('id="resenas"'), content.index('id="contacto"'))

    def test_landing_hero_uses_the_requested_design_with_a_functional_contact_link(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'img/portada-hero-dorado.png')
        self.assertContains(
            response,
            'alt="Portada dorada de Nicolett Studio Fantasy con el logo, una imagen del salón y botón para contactar"',
        )
        self.assertContains(
            response,
            'href="#contacto" class="landing-poster-link landing-poster-contact-cta" aria-label="Contactar al salón"',
        )
        self.assertNotContains(response, 'img/portada-completa-dorada.png')
        self.assertNotContains(response, 'landing-poster-services"')

    def test_landing_services_use_the_golden_ornamental_design(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'id="servicios" class="w-full overflow-hidden"')
        self.assertContains(response, 'img/servicios-contenido-dorado.png')
        self.assertContains(
            response,
            'alt="Sección completa de servicios de Nicolett Studio Fantasy con diseño ornamental dorado"',
        )
        self.assertNotContains(response, 'class="service-card')

    def test_services_poster_does_not_repeat_the_fixed_navigation_bar(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'class="landing-services-poster"')
        self.assertNotContains(response, 'class="landing-services-link')
        for section in ('servicios', 'nosotras', 'galeria', 'resenas', 'contacto'):
            self.assertContains(response, f'href="#{section}"')

    def test_landing_services_uses_full_image_without_live_card_content(self):
        response = self.client.get(reverse('home'))

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
            self.assertNotContains(response, image_name)

    def test_landing_about_section_uses_the_requested_full_golden_design(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, '<section id="nosotras" class="w-full overflow-hidden" aria-label="Nuestra historia">')
        self.assertContains(response, 'img/nosotras-completo-dorado.png')
        self.assertContains(response, 'alt="Nuestra historia en Nicolett Studio Fantasy: creamos belleza con propósito, con diseño ornamental de mármol y marco dorado"')
        self.assertNotContains(response, 'images.unsplash.com/photo-1629397685944-7073f5589754')

    def test_contact_section_has_a_functional_form_and_full_embedded_map(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            '<section id="contacto" class="landing-contact-section" aria-label="Contacto de Nicolett Studio Fantasy">',
        )
        self.assertContains(response, '<form method="POST" class="landing-contact-form space-y-5">')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="mensaje"')
        self.assertContains(response, '<button type="submit"')
        self.assertContains(response, 'class="landing-contact-map"')
        self.assertContains(response, 'height: 340px;')
        self.assertContains(response, 'title="Ubicación de Nicolett Studio Fantasy en Google Maps"')
        self.assertContains(response, 'aria-label="Abrir la ubicación de Nicolett Studio Fantasy en Google Maps"')
        self.assertContains(response, 'https://www.google.com/maps/search/?api=1&amp;query=Av.+Bernardo+O%27Higgins+979%2C+Buin%2C+Santiago')
        self.assertContains(response, 'www.google.com/maps/embed')
        self.assertNotContains(response, 'img/contacto-completo-dorado.png')

    def test_landing_keeps_existing_backgrounds_outside_services_section(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            '<section id="inicio" class="landing-poster" aria-label="Portada de Nicolett Studio Fantasy">',
        )
        self.assertContains(
            response,
            '<form method="POST" class="landing-contact-form space-y-5">',
        )
        self.assertContains(response, 'class="landing-reviews-poster"')
        self.assertContains(response, 'class="landing-reviews-link landing-reviews-link-1"')
        self.assertNotContains(response, 'class="p-8 bg-white rounded-lg shadow-md')
        self.assertContains(response, '.bg-white {\n            background-color: #ffffff !important;')
        self.assertContains(response, 'linear-gradient(to bottom, #fae9cf 0, #fffaf5 88px, #fffaf5 100%)')

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
        self.assertContains(login_response, 'href="/#servicios"')

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

    def test_contact_section_keeps_live_registration_and_message_controls(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            f'href="{reverse("login")}?tab=register" class="inline-block',
        )
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="mensaje"')
