from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models
import django.db.models.deletion


def populate_item_snapshots(apps, schema_editor):
    DetalleVenta = apps.get_model('ventas', 'DetalleVenta')
    alias = schema_editor.connection.alias

    for detalle in DetalleVenta.objects.using(alias).all().iterator():
        catalog_item = detalle.producto or detalle.servicio
        if catalog_item:
            item_nombre = catalog_item.nombre
            item_descripcion = catalog_item.descripcion or ''
            precio_unitario = catalog_item.precio
        else:
            item_nombre = 'Ítem histórico'
            item_descripcion = ''
            quantity = detalle.cantidad or 1
            precio_unitario = (
                Decimal(detalle.subtotal) / quantity
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        DetalleVenta.objects.using(alias).filter(pk=detalle.pk).update(
            item_nombre=item_nombre,
            item_descripcion=item_descripcion,
            precio_unitario=precio_unitario,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0001_initial'),
        ('ventas', '0002_alter_venta_options_alter_detalleventa_producto_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='detalleventa',
            name='item_nombre',
            field=models.CharField(max_length=150, null=True),
        ),
        migrations.AddField(
            model_name='detalleventa',
            name='item_descripcion',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='detalleventa',
            name='precio_unitario',
            field=models.DecimalField(decimal_places=2, max_digits=10, null=True),
        ),
        migrations.RunPython(populate_item_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='detalleventa',
            name='item_nombre',
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name='detalleventa',
            name='item_descripcion',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='detalleventa',
            name='precio_unitario',
            field=models.DecimalField(decimal_places=2, max_digits=10),
        ),
        migrations.AlterField(
            model_name='detalleventa',
            name='producto',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='dashboard.producto',
            ),
        ),
        migrations.AlterField(
            model_name='detalleventa',
            name='servicio',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='dashboard.servicio',
            ),
        ),
    ]
