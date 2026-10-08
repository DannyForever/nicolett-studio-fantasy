from django.test import TestCase
from django.urls import reverse


class LandingPageNavigationTests(TestCase):
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

    def test_shared_header_uses_light_aligned_theme_and_registration_link(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'bg-customBg')
        self.assertContains(response, 'grid-cols-[1fr_auto_1fr]')
        self.assertContains(response, 'text-customDark transition hover:text-customAccent')
        self.assertContains(
            response,
            f'href="{reverse("login")}?tab=register" class="bg-customDark',
        )
        self.assertNotContains(response, '>INICIO</a>')
        self.assertContains(response, f'href="{reverse("home")}" aria-label="Ir al inicio"')

    def test_contact_registration_cta_requests_registration_tab(self):
        response = self.client.get(reverse('home'))

        self.assertContains(
            response,
            f'href="{reverse("login")}?tab=register" class="inline-block',
        )
