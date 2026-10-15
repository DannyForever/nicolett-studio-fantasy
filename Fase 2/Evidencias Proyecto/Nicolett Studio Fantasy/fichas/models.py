from django.db import models
from usuarios.models import Usuario

class FichaCliente(models.Model):
    cliente = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='ficha')
    alergias_condiciones = models.TextField(blank=True, null=True)
    observaciones_generales = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ficha_cliente'

    def __str__(self):
        return f"Ficha de {self.cliente.email}"

class HistorialAtencion(models.Model):
    ficha = models.ForeignKey(FichaCliente, on_delete=models.CASCADE, related_name='historiales')
    fecha_atencion = models.DateTimeField()
    notas_sesion = models.TextField()
    tratamiento_recomendado = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'historial_atencion'

class MaterialCambiosCito(models.Model):
    ficha = models.ForeignKey(FichaCliente, on_delete=models.CASCADE, related_name='cambios_citos')
    descripcion = models.TextField()
    fecha_cambio = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'material_cambios_cito'

class AlertaSeguimiento(models.Model):
    ficha = models.ForeignKey(FichaCliente, on_delete=models.CASCADE, related_name='alertas')
    mensaje = models.TextField()
    fecha_programada = models.DateTimeField()
    atendida = models.BooleanField(default=False)

    class Meta:
        db_table = 'alerta_seguimiento'


class ClientaSeguimiento(models.Model):
    nombre = models.CharField(max_length=200)
    telefono = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fichas_clienta_seguimiento'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class AtencionSeguimiento(models.Model):
    clienta = models.ForeignKey(
        ClientaSeguimiento,
        on_delete=models.CASCADE,
        related_name='atenciones',
    )
    servicio = models.CharField(max_length=150)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_atencion = models.DateField()
    proximo_recordatorio = models.DateField(null=True, blank=True)
    recordatorio_enviado = models.BooleanField(default=False)
    recordatorio_enviado_en = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fichas_atencion_seguimiento'
        ordering = ['proximo_recordatorio', '-fecha_atencion']