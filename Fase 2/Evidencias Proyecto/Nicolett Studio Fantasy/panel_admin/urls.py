from django.urls import path
from django.urls import include
from . import views

urlpatterns = [
    # Vista principal / Resumen del panel
    path('', views.dashboard_home, name='admin_dashboard'),

    # 1. CRUD de Servicios
    path('servicios/', views.listar_servicios, name='listar_servicios'),
    path('servicios/crear/', views.crear_servicio, name='crear_servicio'),
    path('servicios/editar/<int:servicio_id>/', views.editar_servicio, name='editar_servicio'),
    path('servicios/eliminar/<int:servicio_id>/', views.eliminar_servicio, name='eliminar_servicio'),
    path('servicios/estado/<int:servicio_id>/', views.cambiar_estado_servicio, name='cambiar_estado_servicio'),

    # 1.5. CRUD de Categorías (para los servicios)
    path('categorias/crear/', views.crear_categoria, name='crear_categoria'),
    path('categorias/editar/<int:categoria_id>/', views.editar_categoria, name='editar_categoria'),
    path('categorias/eliminar/<int:categoria_id>/', views.eliminar_categoria, name='eliminar_categoria'),

    # 2. CRUD de Productos
    path('productos/', views.lista_productos, name='admin_productos'),
    path('productos/crear/', views.crear_producto, name='crear_producto'),
    path('productos/editar/<int:pk>/', views.editar_producto, name='editar_producto'),
    path('productos/eliminar/<int:pk>/', views.eliminar_producto, name='eliminar_producto'),
    path('productos/estado/<int:pk>/', views.cambiar_estado_producto, name='cambiar_estado_producto'),

    # 3. Agenda, Citas e Historial / Fichas de seguimiento de clientes
    path('agenda/', include('agenda.urls')),
    path('clientes/fichas/', views.lista_fichas_clientes, name='admin_fichas'),
    path('clientes/ficha/<int:pk>/', views.detalle_ficha_cliente, name='detalle_ficha_cliente'),

    # 4. Gestión de Ventas (Productos, Servicios y Pagos)
    path('ventas/', views.lista_ventas, name='admin_ventas'),
    path('ventas/detalle/<int:pk>/', views.detalle_venta, name='admin_detalle_venta'),

    # 5. Sistema de Recordatorios Automáticos
    path('recordatorios/', views.gestion_recordatorios, name='admin_recordatorios'),
    path(
        'recordatorios/enviar/<int:reserva_id>/',
        views.enviar_recordatorio,
        name='enviar_recordatorio',
    ),

    # 6. Gestión de cuentas para los trabajadores (Personal)
    path('personal/', views.lista_personal, name='admin_personal'),
    path('personal/crear/', views.crear_personal, name='crear_personal'),
    path('personal/editar/<int:pk>/', views.editar_personal, name='editar_personal'),
    path('personal/eliminar/<int:pk>/', views.eliminar_personal, name='eliminar_personal'),
    path('personal/desactivar/<int:pk>/', views.desactivar_personal, name='desactivar_personal'),

    # Configuración de la cuenta administrativa activa
    path('configuracion/', views.configuracion_admin, name='admin_configuracion'),
]