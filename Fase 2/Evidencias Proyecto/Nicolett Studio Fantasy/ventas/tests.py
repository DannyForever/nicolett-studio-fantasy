from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DetalleVentaSnapshotMigrationTests(TransactionTestCase):
    reset_sequences = True

    def test_existing_sale_details_are_backfilled_before_catalog_links_can_be_deleted(self):
        migration_target = ('ventas', '0002_alter_venta_options_alter_detalleventa_producto_and_more')
        latest_migration = ('ventas', '0003_detalleventa_item_snapshot')
        executor = MigrationExecutor(connection)
        executor.migrate([migration_target])
        old_apps = executor.loader.project_state([migration_target]).apps

        try:
            Categoria = old_apps.get_model('dashboard', 'Categoria')
            Producto = old_apps.get_model('dashboard', 'Producto')
            Venta = old_apps.get_model('ventas', 'Venta')
            DetalleVenta = old_apps.get_model('ventas', 'DetalleVenta')
            Usuario = get_user_model()

            customer = Usuario.objects.create_superuser(
                email='snapshot.migration@example.com',
                password='Admin123!Test',
                nombre='Historial',
                apellido_paterno='Ventas',
                apellido_materno='',
                telefono='+56912345678',
            )
            category = Categoria.objects.create(nombre='Cuidado', tipo='producto')
            product = Producto.objects.create(
                nombre='Crema antes de borrar',
                descripcion='Descripción del artículo en el catálogo',
                imagen_url='',
                precio='7900.00',
                stock=3,
                activo=True,
                categoria=category,
            )
            sale = Venta.objects.create(cliente_id=customer.pk, total='15800.00')
            detail = DetalleVenta.objects.create(
                venta=sale,
                producto=product,
                cantidad=2,
                subtotal='15800.00',
            )

            MigrationExecutor(connection).migrate([latest_migration])
            current_apps = MigrationExecutor(connection).loader.project_state([latest_migration]).apps
            current_detail = current_apps.get_model('ventas', 'DetalleVenta').objects.get(pk=detail.pk)

            self.assertEqual(current_detail.item_nombre, 'Crema antes de borrar')
            self.assertEqual(current_detail.item_descripcion, 'Descripción del artículo en el catálogo')
            self.assertEqual(str(current_detail.precio_unitario), '7900.00')
        finally:
            MigrationExecutor(connection).migrate([latest_migration])

# Create your tests here.
