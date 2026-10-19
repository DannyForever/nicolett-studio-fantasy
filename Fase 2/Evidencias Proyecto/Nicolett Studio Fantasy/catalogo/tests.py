from django.test import TestCase

from .models import Categoria


class ServiceCategorySeedTests(TestCase):
    def test_service_categories_are_available_in_the_database(self):
        categories = {
            name: (tipo, active)
            for name, tipo, active in Categoria.objects.filter(
                nombre__in=(
                    'Depilación Trilaser',
                    'Lash & Brow',
                    'Nails',
                    'Peluquería',
                    'Tratamientos Faciales',
                ),
            ).values_list('nombre', 'tipo', 'activa')
        }

        expected = {
            'Depilación Trilaser',
            'Lash & Brow',
            'Nails',
            'Peluquería',
            'Tratamientos Faciales',
        }
        self.assertEqual(set(categories), expected)
        for name in expected:
            with self.subTest(category=name):
                self.assertEqual(categories[name], (name, True))
