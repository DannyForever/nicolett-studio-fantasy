from django.db import models
from usuarios.models import Usuario

class Notificacion(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='notificaciones')
    tipo = models.CharField(max_length=50)
    mensaje = models.TextField()
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notificacion'

class Configuracion(models.Model):
    clave = models.CharField(max_length=100, unique=True)
    valor = models.TextField()
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'configuracion'

class Auditoria(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.CharField(max_length=150)
    tabla_afectada = models.CharField(max_length=100)
    registro_id = models.IntegerField()
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'auditoria'


class RecordatorioEnviado(models.Model):
    TIPOS = [
        ('cita', 'Cita próxima'),
        ('seguimiento', 'Seguimiento posterior'),
    ]

    reserva = models.ForeignKey(
        'agenda.Reserva',
        on_delete=models.CASCADE,
        related_name='recordatorios_enviados',
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    desfase = models.PositiveSmallIntegerField(default=0)
    email = models.EmailField()
    enviado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recordatorio_enviado'
        constraints = [
            models.UniqueConstraint(
                fields=['reserva', 'tipo', 'desfase'],
                name='uniq_recordatorio_reserva_tipo_desfase',
            ),
        ]
        ordering = ['-enviado_en']