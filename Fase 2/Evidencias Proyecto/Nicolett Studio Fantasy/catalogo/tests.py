from django.test import TestCase

from .models import Categoria, Servicio


SERVICE_CATEGORIES = {
    'Cortes & estilos',
    'Tratamientos capilares',
    'Nail care & beauty',
    'Pedicure',
    'Depilación',
    'Peinados',
    'Colorimetría',
    'Podología',
    'Lash & brow',
    'Maquillaje',
}


class ServiceCategoryScopeTests(TestCase):
    def test_only_requested_service_categories_are_active_in_the_menu(self):
        categories = set(
            Categoria.objects.filter(
                tipo='servicio',
                activa=True,
            ).exclude(
                nombre__iexact='Sin categoría',
            ).values_list('nombre', flat=True),
        )

        self.assertEqual(categories, SERVICE_CATEGORIES)

    def test_each_catalog_has_an_independent_uncategorized_category(self):
        service_category = Categoria.objects.get(
            tipo='servicio',
            nombre__iexact='Sin categoría',
        )
        product_category = Categoria.objects.get(
            tipo='producto',
            nombre__iexact='Sin categoría',
        )

        self.assertNotEqual(service_category.pk, product_category.pk)
        self.assertTrue(service_category.activa)
        self.assertTrue(product_category.activa)

    def test_legacy_service_categories_are_inactive_after_reclassification(self):
        legacy_names = {
            'Depilación Trilaser',
            'Lash & Brow',
            'Nails',
            'Peluquería',
            'Tratamientos Faciales',
        }
        active_legacy_names = set(
            Categoria.objects.filter(
                nombre__in=legacy_names,
                activa=True,
            ).values_list('nombre', flat=True),
        )

        self.assertEqual(active_legacy_names, set())

    def test_seeded_services_use_the_new_service_category_names(self):
        self.assertEqual(
            Servicio.objects.get(nombre='Rostro completo').categoria.nombre,
            'Depilación',
        )
        self.assertEqual(
            Servicio.objects.get(nombre='Laminado de cejas').categoria.nombre,
            'Lash & brow',
        )
