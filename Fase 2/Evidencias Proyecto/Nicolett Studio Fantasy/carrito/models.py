from django.conf import settings
from django.db import models


class Pedido(models.Model):
    ESTADOS = [
        ('pagado', 'Pagado'),
        ('abono', 'Pagado parcialmente'),
    ]

    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='pedidos_carrito',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    monto_pagado = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(max_length=20, choices=ESTADOS)

    class Meta:
        ordering = ['-creado_en']

    @property
    def saldo_pendiente(self):
        return self.total - self.monto_pagado


class DetallePedido(models.Model):
    TIPOS = [
        ('producto', 'Producto'),
        ('servicio', 'Servicio'),
    ]
    PAGOS_SERVICIO = [
        ('completo', 'Pago completo'),
        ('abono', 'Abono de $5.000'),
        ('no_aplica', 'No aplica'),
    ]

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name='detalles',
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    producto_id_catalogo = models.PositiveBigIntegerField(null=True, blank=True)
    servicio_id_catalogo = models.PositiveBigIntegerField(null=True, blank=True)
    nombre = models.CharField(max_length=150)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2)
    modalidad_pago = models.CharField(max_length=20, choices=PAGOS_SERVICIO)
    reserva = models.ForeignKey(
        'agenda.Reserva',
        on_delete=models.PROTECT,
        related_name='detalles_pedido',
        null=True,
        blank=True,
    )

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad

    @property
    def saldo_pendiente(self):
        return self.subtotal - self.monto_pagado


class PagoSimulado(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.PROTECT,
        related_name='pagos_simulados',
    )
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    metodo = models.CharField(max_length=40, default='Pago ficticio')
    estado = models.CharField(max_length=20, default='aprobado')
    transaccion_id = models.CharField(max_length=36, unique=True)
    creado_en = models.DateTimeField(auto_now_add=True)


class ReservaProductoCarrito(models.Model):
    session_key = models.CharField(max_length=40)
    producto_id = models.PositiveBigIntegerField()
    cantidad = models.PositiveIntegerField()
    vence_en = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session_key', 'producto_id'],
                name='uniq_reserva_producto_carrito',
            ),
        ]
        indexes = [
            models.Index(fields=['vence_en'], name='carrito_reserva_vence_idx'),
        ]
