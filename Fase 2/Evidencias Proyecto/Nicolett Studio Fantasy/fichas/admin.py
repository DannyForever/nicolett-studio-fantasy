from django.contrib import admin
from .models import FichaCliente, HistorialAtencion, MaterialCambiosCito, AlertaSeguimiento

@admin.register(FichaCliente)
class FichaClienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente', 'created_at', 'updated_at')
    search_fields = ('cliente__email', 'cliente__nombre', 'alergias_condiciones')

@admin.register(HistorialAtencion)
class HistorialAtencionAdmin(admin.ModelAdmin):
    list_display = ('id', 'ficha', 'fecha_atencion')
    list_filter = ('fecha_atencion',)
    search_fields = ('ficha__cliente__email', 'notas_sesion')

@admin.register(MaterialCambiosCito)
class MaterialCambiosCitoAdmin(admin.ModelAdmin):
    list_display = ('id', 'ficha', 'fecha_cambio')
    search_fields = ('descripcion',)

@admin.register(AlertaSeguimiento)
class AlertaSeguimientoAdmin(admin.ModelAdmin):
    list_display = ('id', 'ficha', 'fecha_programada', 'atendida')
    list_filter = ('atendida', 'fecha_programada')
    search_fields = ('mensaje',)