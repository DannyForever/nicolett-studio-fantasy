from django.conf import settings
from django.db import models

from panel_admin.models import Producto, Servicio


class Venta(models.Model):
    fecha_venta = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(max_length=50, default='Completada')
    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ventas',
    )

    class Meta:
        db_table = 'venta'
        ordering = ['-fecha_venta']

    def __str__(self):
        return f'Venta #{self.pk}'


class DetalleVenta(models.Model):
    cantidad = models.IntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name='detalles',
    )

    class Meta:
        db_table = 'detalle_venta'

    def __str__(self):
        return f'Detalle de venta #{self.venta_id}'