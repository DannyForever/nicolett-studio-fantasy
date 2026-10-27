from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from django.urls import reverse


class LandingPageNavigationTests(TestCase):
    def test_landing_gallery_shows_three_image_carousel_with_instagram_profile_link(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<section id="galeria" class="landing-gallery-section"')
        self.assertContains(response, 'class="landing-gallery-poster"')
        self.assertContains(response, '<p class="landing-gallery-kicker">Nuestro trabajo</p>')
        self.assertContains(response, '<h2>Galería</h2>')
        self.assertContains(response, "img/pag_principal/galeria/fondo_galeria.jpg")
        self.assertContains(response, 'data-gallery-carousel role="region" aria-label="Trabajos recientes" tabindex="0"')
        self.assertContains(response, 'data-gallery-track')
        self.assertEqual(response.content.count(b'data-gallery-slide aria-label="Ver trabajo'), 6)
        self.assertContains(response, 'flex: 0 0 var(--gallery-slide-width, 32%);')
        self.assertContains(response, 'align-items: flex-start;')
        self.assertContains(response, 'bottom: 14%;')
        self.assertContains(response, 'border-radius: 0;')
        self.assertContains(response, 'box-shadow: none;')
        self.assertNotContains(response, 'data-gallery-previous')
        self.assertNotContains(response, 'data-gallery-next')
        self.assertContains(response, 'href="https://www.instagram.com/nicolettstudiofantasy"')
        self.assertContains(response, 'Ver más en Instagram')
        works = (
            ('trabajo_01.jpg', 'Dc0yoC7RNZ6'),
            ('trabajo_02.jpg', 'DYNKxxLR-c2'),
            ('trabajo_03.jpg', 'DXt7KGakUtx'),
            ('trabajo_04.jpg', 'C8bEEJUO_5d'),
            ('trabajo_05.jpg', 'DHWlL0ZyEOl'),
            ('trabajo_06.jpg', 'DXt5W3nEdZa'),
        )
        for image, reel in works:
            self.assertContains(response, f'img/pag_principal/galeria/{image}')
            self.assertContains(response, f'https://www.instagram.com/reels/{reel}/')
        self.assertNotContains(response, 'img/galeria-completa-dorada.png')
        self.assertEqual(response.content.count(b'https://www.instagram.com/embed.js'), 0)

    def test_landing_reviews_navigation_targets_google_reviews_section(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="#resenas"')
        self.assertContains(response, '<section id="resenas" class="landing-reviews-section"')
        self.assertContains(response, 'linear-gradient(125deg, #e8cc8f, #f8ebc9 48%, #d8b66e)')
        self.assertNotContains(response, 'img/pag_principal/resenas/fondo_resenas.jpg')
        self.assertContains(response, 'img/pag_principal/resenas/marco_resena.png')
        self.assertNotContains(response, 'resenas_marcos.jpg')
        self.assertEqual(response.content.count(b'class="landing-review-card landing-review-card-'), 3)
        self.assertEqual(response.content.count(b'img/pag_principal/resenas/marco_resena.png'), 3)
        self.assertEqual(response.content.count(b'class="landing-review-google-g"'), 3)
        self.assertNotContains(response, 'Ver reseña en Google Maps')
        self.assertContains(response, 'Lo que dicen en Google Maps')
        self.assertContains(response, 'padding: clamp(34px, 5vw, 64px) 0 clamp(36px, 5vw, 64px);')
        self.assertContains(response, 'font-size: clamp(1.05rem, 1.6vw, 1.4rem);')
        self.assertContains(response, 'font-size: 1.15rem;')
        self.assertContains(response, 'Nuestras clientas')
        self.assertContains(response, 'servicio es 10/10')
        self.assertContains(response, 'Leer en Google Maps la reseña de María N.')
        self.assertContains(response, 'Leer en Google Maps la reseña de Betsabe V.')
        self.assertContains(response, 'Leer en Google Maps la reseña de Krishna T.')
        self.assertContains(response, 'https://maps.app.goo.gl/o64JrZsmmMyn3hDNA')
        self.assertContains(response, 'https://maps.app.goo.gl/LT6kGLR7xncssqS19')
        self.assertContains(response, 'https://maps.app.goo.gl/Hhd1TDNqLEfaotAp7')
        self.assertContains(
            response,
            '.landing-gallery-section {\n            scroll-margin-top: 85px;\n            padding: clamp(14px, 2vw, 24px);\n            background: #f7f3ed;',
        )

    def test_full_width_hero_precedes_about_and_services_posters(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'class="landing-poster-page')
        self.assertContains(
            response,
            '#inicio,\n        #nosotras,\n        #servicios,\n        #galeria,\n        #resenas,\n        #contacto {\n            width: min(96%, 1480px);\n            max-width: 1480px;\n            margin: clamp(14px, 2vw, 24px) auto;',
        )
        self.assertContains(response, 'width: min(96%, 1480px);')
        self.assertContains(response, '.landing-poster-page > footer {\n            width: min(96%, 1480px);\n            max-width: 1480px;\n            margin: 0 auto;')
        self.assertContains(response, 'border-radius: 22px;')
        self.assertContains(response, 'background-image: url("/static/img/pag_principal/inicio/fondo_inicio.jpg")')
        content = response.content.decode()
        self.assertLess(content.index('id="inicio"'), content.index('id="nosotras"'))
        self.assertLess(content.index('id="nosotras"'), content.index('id="servicios"'))
        self.assertLess(content.index('id="inicio"'), content.index('id="servicios"'))

    def test_login_content_uses_centered_width_without_constraining_header_or_footer(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="es" class="auth-page-document">')
        self.assertContains(response, 'class="auth-page-layout"')
        self.assertContains(response, 'width: min(100%, 1480px);')
        self.assertContains(response, 'background: #fffaf5 !important;')
        self.assertContains(response, 'top: 0;')
        self.assertContains(response, 'margin: 0 auto;')
        self.assertContains(response, 'linear-gradient(120deg, #24170f, #49301d 48%, #21150f)')
        self.assertContains(response, 'color: #f3dfb4 !important;')
        self.assertContains(response, 'radial-gradient(ellipse at 50% 0%, rgb(116 75 36 / 36%), transparent 62%)')
        self.assertContains(response, 'height: auto;')
        self.assertContains(response, 'flex-direction: column;')
        self.assertContains(response, 'margin-left: auto;')
        self.assertContains(response, 'margin-right: auto;')
        self.assertContains(response, 'body.auth-page > header {')
        self.assertContains(response, 'body.auth-page > footer {')
        self.assertContains(response, 'class="accessibility-widget"')

    def test_landing_hero_uses_saloon_colored_scrollbar_and_keeps_navigation_functional(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, '<html lang="es" class="scroll-smooth landing-poster-document">')
        self.assertContains(response, 'scrollbar-color: #9a6a26 #f5e9d0;')
        self.assertContains(response, 'scrollbar-width: thin;')
        self.assertContains(response, '.landing-poster-document::-webkit-scrollbar-thumb,\n        .landing-poster-page::-webkit-scrollbar-thumb {')
        self.assertNotContains(response, 'display: none !important;\n            width: 0 !important;\n            height: 0 !important;')
        self.assertContains(response, 'overflow-x: hidden;')
        self.assertContains(response, 'href="#servicios" class="text-customDark transition hover:text-customAccent"')
        self.assertContains(response, 'href="#galeria" class="text-customDark transition hover:text-customAccent"')
        self.assertContains(response, 'aria-label="Ingresar a clientes"')

    def test_golden_navigation_bar_stays_fixed_over_all_page_images(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            '.landing-poster-page > header {\n            display: grid;\n            position: fixed;\n            top: 0;\n            right: 0;\n            left: 50%;\n            z-index: 100;',
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

    def test_landing_hero_uses_selectable_copy_and_requested_images(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'img/pag_principal/inicio/fondo_inicio.jpg')
        self.assertContains(response, 'img/pag_principal/inicio/boton_contacto.png')
        self.assertContains(response, 'img/pag_principal/inicio/marco_inicio.png')
        self.assertContains(response, 'img/pag_principal/inicio/salon_portada.jpg')
        self.assertContains(response, 'img/pag_principal/inicio/cartel_agenda.png')
        self.assertContains(response, 'top: 20%;\n            left: 17%;\n            width: 66%;\n            height: 60%;')
        self.assertContains(response, '.landing-hero-salon-photo {\n            z-index: 2;')
        self.assertContains(response, '.landing-hero-salon-frame {\n            z-index: 1;')
        self.assertContains(response, '.landing-hero-schedule {\n            position: absolute;\n            z-index: 3;')
        self.assertContains(response, 'width: min(100%, 360px);\n            min-height: 120px;')
        self.assertContains(response, 'align-self: start;')
        self.assertContains(response, 'El arte de <em>hacerte sentir hermosa</em>')
        self.assertContains(response, 'href="#contacto" class="landing-hero-contact" aria-label="Contactar a Nicolett Studio Fantasy"')
        self.assertContains(response, '<span>Contactar</span>')
        self.assertContains(response, 'Agenda abierta<small>Lun - Sáb 9:00 - 20:00</small>')
        self.assertContains(response, 'user-select: text;')
        self.assertNotContains(response, 'img/portada-hero-dorado.png')
        self.assertNotContains(response, 'img/portada-completa-dorada.png')
        self.assertNotContains(response, 'landing-poster-services"')

    def test_landing_services_use_a_responsive_manual_and_automatic_carousel(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'id="servicios" class="landing-services-section"')
        self.assertContains(response, 'background-image: url("/static/img/pag_principal/servicios/fondo_servicios.jpg")')
        self.assertContains(response, '<p class="landing-services-eyebrow">Lo que ofrecemos</p>')
        self.assertContains(response, 'Nuestros servicios')
        self.assertEqual(response.content.decode().count('class="landing-service-card"'), 6)
        self.assertEqual(response.content.decode().count('aria-roledescription="diapositiva"'), 6)
        self.assertContains(response, 'data-service-carousel role="region" aria-roledescription="carrusel"')
        self.assertContains(response, 'max-width: 1180px;')
        self.assertContains(response, 'grid-template-columns: repeat(2, minmax(0, 1fr));')
        self.assertContains(response, 'grid-template-columns: minmax(0, 1fr);')
        self.assertContains(response, 'height: clamp(460px, 40vw, 520px);')
        self.assertContains(response, '-webkit-line-clamp: 6;')
        self.assertContains(response, '-webkit-line-clamp: 4;')
        self.assertContains(response, 'data-service-previous aria-label="Servicio anterior"')
        self.assertContains(response, 'data-service-next aria-label="Servicio siguiente"')
        self.assertContains(response, 'data-service-toggle')
        self.assertContains(response, '}, 10000);')
        self.assertNotContains(response, 'img/pag_principal/servicios/marco_servicio.png')
        self.assertEqual(response.content.decode().count('class="landing-service-detail"'), 12)
        for value in (
            'Desde $35.000',
            'Desde $10.000',
            'Desde $20.000',
            'Desde $15.000',
            'Desde $3.000',
            'Desde $22.000',
        ):
            self.assertContains(response, value)
        self.assertContains(response, 'Los precios y tiempos son referenciales.')

    def test_services_grid_coexists_with_shared_navigation(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'class="landing-services-carousel"')
        self.assertNotContains(response, 'class="landing-services-link')
        for section in ('servicios', 'nosotras', 'galeria', 'resenas', 'contacto'):
            self.assertContains(response, f'href="#{section}"')

    def test_landing_services_show_images_names_and_descriptions_in_requested_order(self):
        response = self.client.get(reverse('home'))

        self.assertNotContains(response, 'Servicios hasta 30% OFF')
        self.assertNotContains(response, 'El cupón se enviará')
        content = response.content.decode()
        names = (
            'Colorimetría',
            'Corte &amp; estilo',
            'Tratamientos',
            'Manicure &amp; pedicure',
            'Depilación',
            'Maquillaje',
        )
        images = (
            'colorimetria.jpg',
            'corte_estilo.jpg',
            'tratamientos.jpg',
            'manicure_pedicure.jpg',
            'depilacion.jpg',
            'maquillaje.jpg',
        )
        positions = [content.index(f'<h3>{name}</h3>') for name in names]
        self.assertEqual(positions, sorted(positions))
        for image in images:
            self.assertContains(response, f'img/pag_principal/servicios/{image}')
        self.assertEqual(content.count('<div class="landing-service-copy">'), 6)
        self.assertContains(response, 'Una evaluación personalizada de tu tono de piel')
        self.assertContains(response, 'Tratamientos orientados a las necesidades de tu cabello')
        self.assertContains(response, 'Maquillaje social adaptado a tu ocasión')

    def test_landing_about_section_uses_selectable_copy_and_requested_images(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, '<section id="nosotras" class="landing-about-section" aria-labelledby="landing-about-title">')
        self.assertContains(response, 'background-image: url("/static/img/pag_principal/nosotras/fondo_nosotras.jpg")')
        self.assertContains(response, 'img/pag_principal/nosotras/nosotras.jpg')
        self.assertContains(response, 'img/pag_principal/nosotras/marco_nosotras.png')
        self.assertContains(response, 'width: min(100%, 760px);')
        self.assertContains(response, 'padding: clamp(24px, 3vw, 48px) clamp(18px, 5vw, 72px);')
        self.assertContains(response, 'grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);')
        self.assertContains(response, 'Creamos belleza <em>con propósito</em>')
        self.assertContains(response, 'Productos 100% libres de parabenos')
        self.assertContains(response, 'user-select: text;')
        self.assertNotContains(response, 'img/nosotras-completo-dorado.png')
        self.assertNotContains(response, 'images.unsplash.com/photo-1629397685944-7073f5589754')

    def test_contact_section_uses_a_rounded_split_layout_and_keeps_its_functional_form(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            '<section id="contacto" class="landing-contact-section" aria-label="Contacto de Nicolett Studio Fantasy">',
        )
        self.assertContains(response, '<form method="POST" class="landing-contact-form space-y-5">')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="mensaje"')
        self.assertContains(response, 'name="nombre"')
        self.assertContains(response, 'name="apellido"')
        self.assertContains(response, 'name="telefono"')
        self.assertContains(response, 'name="asunto"')
        self.assertContains(response, '<button type="submit"')
        self.assertContains(response, 'grid-template-columns: repeat(2, minmax(0, 1fr));')
        self.assertContains(response, 'class="landing-contact-info"')
        self.assertContains(response, 'class="landing-contact-map"')
        self.assertContains(response, 'class="landing-contact-account"')
        self.assertContains(response, 'www.google.com/maps/embed')
        self.assertContains(response, 'border-radius: inherit;')
        self.assertContains(response, 'border-radius: 20px;')
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
        self.assertContains(response, 'class="landing-review-card landing-review-card-1"')
        self.assertNotContains(response, 'class="p-8 bg-white rounded-lg shadow-md')
        self.assertContains(response, '.bg-white {\n            background-color: #ffffff !important;')
        self.assertContains(response, 'background-image: url("/static/img/pag_principal/nosotras/fondo_nosotras.jpg")')

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

    def test_contact_section_keeps_form_controls_and_restored_panels(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="mensaje"')
        self.assertContains(response, '<div class="landing-contact-map">')
        self.assertContains(response, '<div class="landing-contact-account">')
        self.assertContains(response, f'href="{reverse("login")}?tab=register"')
