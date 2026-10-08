from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Rol, Usuario

@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)

@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('email', 'nombre', 'apellido_paterno', 'apellido_materno', 'rol', 'is_active', 'is_staff')
    list_filter = ('rol', 'is_active', 'is_staff')
    search_fields = ('email', 'nombre', 'apellido_paterno', 'telefono')
    ordering = ('email',)
    
    # Configuración de campos para el formulario de edición en el Admin
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Información Personal', {'fields': ('nombre', 'segundo_nombre', 'apellido_paterno', 'apellido_materno', 'telefono', 'rol')}),
        ('Permisos y Estados', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas importantes', {'fields': ('acepta_terminos_at', 'deleted_at', 'last_login')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nombre', 'apellido_paterno', 'apellido_materno', 'telefono', 'rol', 'password1', 'password2'),
        }),
    )