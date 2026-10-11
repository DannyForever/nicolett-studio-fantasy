from django.urls import path
from . import views
from agenda import views as agenda_views
from carrito import views as carrito_views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('cliente/', views.cliente_home_view, name='cliente_home'),
    path('cliente/servicios/', views.cliente_servicios_view, name='cliente_servicios'),
    path('cliente/productos/', views.cliente_productos_view, name='cliente_productos'),
    path('cliente/carrito/', carrito_views.ver_carrito, name='cliente_carrito'),
    path('cliente/carrito/producto/<int:pk>/agregar/', carrito_views.agregar_producto, name='cliente_carrito_agregar_producto'),
    path('cliente/carrito/servicio/<int:pk>/agregar/', carrito_views.agregar_servicio, name='cliente_carrito_agregar_servicio'),
    path('cliente/carrito/actualizar/', carrito_views.actualizar_carrito, name='cliente_carrito_actualizar'),
    path('cliente/carrito/servicio/<str:key>/guardar-cita/', carrito_views.guardar_cita_carrito, name='cliente_carrito_guardar_cita'),
    path('cliente/carrito/pagar/', carrito_views.pagar_carrito, name='cliente_carrito_pagar'),
    path('cliente/carrito/compra/<int:pk>/', carrito_views.resultado_compra, name='cliente_compra_resultado'),
    path('cliente/agendamiento/', views.cliente_agendamiento_view, name='cliente_agendamiento'),
    path(
        'cliente/agendamiento/profesionales/',
        agenda_views.cliente_profesionales_json,
        name='cliente_profesionales_disponibles',
    ),
    path(
        'cliente/agendamiento/horas/',
        agenda_views.cliente_horas_disponibles_json,
        name='cliente_horas_disponibles',
    ),
    path(
        'cliente/agendamiento/crear/',
        agenda_views.crear_reserva_cliente,
        name='cliente_crear_reserva',
    ),
    path(
        'cliente/gestionar-citas/',
        views.cliente_gestionar_citas_view,
        name='cliente_gestionar_citas',
    ),
    path(
        'cliente/gestionar-citas/<int:pk>/cancelar/',
        agenda_views.cancelar_reserva_cliente,
        name='cliente_cancelar_reserva',
    ),
    path(
        'cliente/gestionar-citas/<int:pk>/reagendar/',
        agenda_views.reagendar_reserva_cliente,
        name='cliente_reagendar_reserva',
    ),
    path('cliente/historial/', views.cliente_historial_view, name='cliente_historial'),
    path('cliente/cancelar-cita/', views.cliente_cancelar_cita_view, name='cliente_cancelar_cita'),
    path('logout/', views.logout_view, name='logout'),
]