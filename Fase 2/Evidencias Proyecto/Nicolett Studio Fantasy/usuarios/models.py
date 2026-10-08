from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


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
        return self.create_user(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    nombre = models.CharField(max_length=100)
    segundo_nombre = models.CharField(max_length=100, blank=True)
    apellido_paterno = models.CharField(max_length=100)
    apellido_materno = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
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