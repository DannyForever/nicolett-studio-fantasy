from django.db import models


class Categoria(models.Model):
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50)
    activa = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'categoria'

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    imagen_url = models.CharField(blank=True, max_length=255, null=True)
    precio = models.DecimalField(decimal_places=2, max_digits=10)
    stock = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name='productos',
    )

    class Meta:
        managed = False
        db_table = 'producto'

    def __str__(self):
        return self.nombre


class Servicio(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    imagen_url = models.CharField(blank=True, max_length=255, null=True)
    duracion_minutos = models.IntegerField()
    precio = models.DecimalField(decimal_places=2, max_digits=10)
    activo = models.BooleanField(default=True)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name='servicios',
    )

    class Meta:
        managed = False
        db_table = 'servicio'

    def __str__(self):
        return self.nombre
