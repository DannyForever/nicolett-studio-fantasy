from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models, transaction
from django.db.models import Q


class Rol(models.Model):
    nombre = models.CharField(max_length=50, unique=True)  # Admin, Cliente

    class Meta:
        db_table = 'rol'

    def __str__(self):
        return self.nombre


class UsuarioManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('El email es obligatorio')
        if 'rol' not in extra:
            # Corregido de 'Clienta' a 'Cliente' para que coincida con tu base de datos
            extra['rol'], _ = Rol.objects.get_or_create(nombre='Cliente')
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        extra['rol'], _ = Rol.objects.get_or_create(nombre='Admin')
        from .utils import DOMINIO_ACCESO, generar_correo_acceso

        if not (email or '').casefold().endswith(f'@{DOMINIO_ACCESO}'):
            extra.setdefault('correo_contacto', email)
            correo_generado = generar_correo_acceso(
                extra.get('nombre', ''),
                extra.get('apellido_paterno', ''),
                extra.get('apellido_materno', ''),
            )
            if correo_generado:
                email = correo_generado
        return self.create_user(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    nombre = models.CharField(max_length=100)
    segundo_nombre = models.CharField(max_length=100, blank=True)
    apellido_paterno = models.CharField(max_length=100)
    apellido_materno = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    correo_contacto = models.EmailField(blank=True, default='')
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name='usuarios')
    is_active = models.BooleanField('activo', default=True)
    is_staff = models.BooleanField(default=False)
    acepta_terminos_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = UsuarioManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nombre', 'apellido_paterno', 'apellido_materno', 'telefono']

    class Meta:
        db_table = 'usuario'

    def __str__(self):
        return self.email


class DireccionCliente(models.Model):
    TIPO_ENVIO = 'envio'
    TIPO_FACTURACION = 'facturacion'
    TIPOS = [
        (TIPO_ENVIO, 'Envío'),
        (TIPO_FACTURACION, 'Facturación'),
    ]

    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='direcciones',
    )
    tipo = models.CharField(max_length=12, choices=TIPOS)
    nombre = models.CharField(max_length=150)
    rut = models.CharField(max_length=12, blank=True)
    razon_social = models.CharField(max_length=150, blank=True)
    giro = models.CharField(max_length=150, blank=True)
    direccion = models.CharField(max_length=200)
    complemento = models.CharField(max_length=120, blank=True)
    comuna = models.CharField(max_length=100)
    provincia = models.CharField(max_length=100, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100)
    codigo_postal = models.CharField(max_length=12, blank=True)
    telefono = models.CharField(max_length=20)
    instrucciones = models.TextField(blank=True)
    predeterminada = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'direccion_cliente'
        ordering = ['-created_at', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'tipo'],
                condition=Q(predeterminada=True),
                name='uniq_default_address_per_type',
            ),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.nombre} - {self.direccion}'

    def save(self, *args, **kwargs):
        with transaction.atomic():
            direcciones = type(self).objects.filter(
                usuario_id=self.usuario_id,
                tipo=self.tipo,
            ).exclude(pk=self.pk)
            if self.predeterminada:
                direcciones.filter(predeterminada=True).update(predeterminada=False)
            elif not direcciones.filter(predeterminada=True).exists():
                self.predeterminada = True
            super().save(*args, **kwargs)