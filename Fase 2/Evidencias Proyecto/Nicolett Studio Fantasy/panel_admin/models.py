from django.db import models

# Create your models here.
class Categoria(models.Model):
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=100)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'categoria'

    def __str__(self):
        return self.nombre


class Servicio(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    imagen_url = models.ImageField(upload_to='servicios/', blank=True, null=True, db_column='imagen_url')
    duracion_minutos = models.IntegerField()
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    activo = models.BooleanField(default=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, db_column='categoria_id')

    class Meta:
        db_table = 'servicio'

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    imagen_url = models.ImageField(
        upload_to='productos/',
        max_length=255,
        blank=True,
        null=True,
        db_column='imagen_url',
    )
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name='productos',
        db_column='categoria_id',
    )

    class Meta:
        db_table = 'producto'

    def __str__(self):
        return self.nombre