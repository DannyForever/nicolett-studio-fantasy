from django.contrib import admin
from .models import Notificacion, Configuracion, Auditoria

@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'tipo', 'leida', 'fecha_creacion')
    list_filter = ('tipo', 'leida')
    search_fields = ('usuario__email', 'mensaje')

@admin.register(Configuracion)
class ConfiguracionAdmin(admin.ModelAdmin):
    list_display = ('id', 'clave', 'valor')
    search_fields = ('clave',)

@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'accion', 'tabla_afectada', 'registro_id', 'fecha_hora')
    list_filter = ('tabla_afectada', 'fecha_hora')
    search_fields = ('usuario__email', 'accion')