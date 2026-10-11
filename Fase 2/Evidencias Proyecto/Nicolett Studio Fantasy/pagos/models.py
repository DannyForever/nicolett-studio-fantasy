from django.db import models

from ventas.models import Venta


class Pago(models.Model):
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    metodo_pago = models.CharField(max_length=50)
    estado_pago = models.CharField(max_length=50, default='Aprobado')
    transaccion_id = models.CharField(max_length=150, blank=True, null=True)
    fecha_pago = models.DateTimeField(auto_now_add=True)
    venta = models.ForeignKey(
        Venta,
        on_delete=models.PROTECT,
        related_name='pagos',
    )

    class Meta:
        db_table = 'pago'

    def __str__(self):
        return f'Pago #{self.pk} de venta #{self.venta_id}'