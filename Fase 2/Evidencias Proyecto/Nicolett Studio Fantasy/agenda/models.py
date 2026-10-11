from django.conf import settings
from django.db import models


class ServicioAgenda(models.Model):
    nombre = models.CharField(max_length=150)
    duracion_minutos = models.PositiveIntegerField()
    activo = models.BooleanField(default=True)
    categoria_id = models.PositiveBigIntegerField()

    class Meta:
        managed = False
        db_table = 'servicio'

    def __str__(self):
        return self.nombre


class CategoriaAgenda(models.Model):
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=100)
    activa = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'categoria'

    def __str__(self):
        return self.nombre


class ProfesionalCategoria(models.Model):
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='especialidades',
    )
    categoria = models.ForeignKey(
        CategoriaAgenda,
        on_delete=models.CASCADE,
        related_name='profesionales',
    )

    class Meta:
        db_table = 'profesional_categoria'
        constraints = [
            models.UniqueConstraint(
                fields=['profesional', 'categoria'],
                name='uniq_profesional_categoria',
            ),
        ]


class Reserva(models.Model):
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('confirmada', 'Confirmada'),
        ('suspendida', 'Suspendida: esperando respuesta'),
        ('cancelada', 'Cancelada'),
        ('completada', 'Completada'),
    ]
    ORIGENES = [
        ('manual', 'Agendada por administración'),
        ('cliente', 'Agendada por cliente'),
    ]

    fecha_hora = models.DateTimeField()
    estado = models.CharField(max_length=50, choices=ESTADOS, default='pendiente')
    origen = models.CharField(max_length=50, choices=ORIGENES, default='manual', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reservas_cliente',
        null=True,
        blank=True,
    )
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='reservas_creadas',
        null=True,
        blank=True,
    )
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reservas_profesional',
        null=True,
        blank=True,
    )
    servicio = models.ForeignKey(
        ServicioAgenda,
        on_delete=models.SET_NULL,
        related_name='reservas',
        null=True,
        blank=True,
    )
    cliente_nombre = models.CharField(max_length=200, blank=True)
    cliente_email = models.EmailField(blank=True)
    cliente_telefono = models.CharField(max_length=30, blank=True)
    servicio_nombre = models.CharField(max_length=150, blank=True)
    duracion_minutos = models.PositiveIntegerField(default=30)
    motivo_cancelacion = models.TextField(blank=True)
    motivo_suspension = models.TextField(blank=True)
    respuesta_suspension = models.CharField(max_length=20, blank=True)
    cambio_disponibilidad = models.ForeignKey(
        'CambioDisponibilidadPendiente',
        on_delete=models.SET_NULL,
        related_name='reservas',
        null=True,
        blank=True,
    )

    class Meta:
        db_table = 'reserva'
        ordering = ['fecha_hora']

    def __str__(self):
        return f'{self.servicio_nombre} - {self.cliente_nombre} ({self.fecha_hora:%Y-%m-%d %H:%M})'

    @property
    def nombre_cliente(self):
        if self.cliente_id:
            nombre = ' '.join(
                parte for parte in (
                    self.cliente.nombre,
                    self.cliente.segundo_nombre,
                    self.cliente.apellido_paterno,
                    self.cliente.apellido_materno,
                ) if parte
            )
            return nombre or self.cliente.email
        return self.cliente_nombre

    @property
    def correo_cliente(self):
        return self.cliente_email or (self.cliente.email if self.cliente_id else '')


class Disponibilidad(models.Model):
    DIAS_SEMANA = [
        ('0', 'Lunes'),
        ('1', 'Martes'),
        ('2', 'Miércoles'),
        ('3', 'Jueves'),
        ('4', 'Viernes'),
        ('5', 'Sábado'),
        ('6', 'Domingo'),
    ]

    dia_semana = models.CharField(max_length=20, choices=DIAS_SEMANA)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    activo = models.BooleanField(default=True)
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='disponibilidades',
        null=True,
        blank=True,
    )
    servicio = models.ForeignKey(
        ServicioAgenda,
        on_delete=models.CASCADE,
        related_name='disponibilidades',
        null=True,
        blank=True,
    )
    fecha_especifica = models.DateField(null=True, blank=True)
    intervalo_minutos = models.PositiveIntegerField(null=True, blank=True)
    descanso_inicio = models.TimeField(null=True, blank=True)
    descanso_fin = models.TimeField(null=True, blank=True)

    class Meta:
        db_table = 'disponibilidad'
        ordering = ['dia_semana', 'hora_inicio']

    def __str__(self):
        return f'{self.get_dia_semana_display()} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}'


class ProfesionalServicio(models.Model):
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='servicios_profesional',
    )
    servicio = models.ForeignKey(
        ServicioAgenda,
        on_delete=models.CASCADE,
        related_name='profesionales',
    )

    class Meta:
        db_table = 'profesional_servicio'
        unique_together = (('profesional', 'servicio'),)


class DiaCerrado(models.Model):
    fecha = models.DateField(unique=True)
    motivo = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['fecha']
        verbose_name = 'día cerrado'
        verbose_name_plural = 'días cerrados'

    def __str__(self):
        return f'{self.fecha:%d-%m-%Y} - {self.motivo}'


class CambioDisponibilidadPendiente(models.Model):
    fecha = models.DateField()
    bloque_inicio = models.TimeField()
    bloque_fin = models.TimeField()
    servicio = models.ForeignKey(
        ServicioAgenda,
        on_delete=models.CASCADE,
        related_name='cambios_pendientes',
    )
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cambios_disponibilidad_pendientes',
    )
    motivo = models.TextField()
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['fecha', 'servicio', 'profesional', 'bloque_inicio'],
                name='uniq_cambio_disponibilidad_bloque',
            ),
        ]
