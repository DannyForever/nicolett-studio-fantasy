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