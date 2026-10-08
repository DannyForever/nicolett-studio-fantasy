from django.contrib import admin
from panel_admin.models import Categoria, Servicio

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'tipo', 'activa')
    list_filter = ('tipo', 'activa')
    search_fields = ('nombre',)

@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'categoria', 'precio', 'duracion_minutos', 'activo')
    list_filter = ('activo', 'categoria')
    search_fields = ('nombre', 'descripcion')