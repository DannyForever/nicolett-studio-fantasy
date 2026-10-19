from django.urls import path
from . import views
from agenda import views as agenda_views
from carrito import views as carrito_views
from fichas import views as fichas_views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path(
        'confirmar-correo/<uidb64>/<token>/',
        views.verificar_correo_view,
        name='verify_email',
    ),
    path('recuperar-contrasena/', views.solicitar_recuperacion_contrasena, name='password_recovery'),
    path(
        'restablecer-contrasena/<uidb64>/<token>/',
        views.restablecer_contrasena,
        name='password_reset_confirm_custom',
    ),
    path('terminos-y-privacidad/', views.terminos_privacidad_view, name='terminos_privacidad'),
    path('cliente/', views.cliente_home_view, name='cliente_home'),
    path('cliente/sobre-nosotros/', views.cliente_sobre_nosotros_view, name='cliente_sobre_nosotros'),
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
        'cliente/agendamiento/calendario/',
        agenda_views.cliente_calendario_disponibilidad_json,
        name='cliente_calendario_disponibilidad',
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
    path('cliente/ficha-tecnica/', fichas_views.ficha_tecnica_cliente_pdf, name='cliente_ficha_tecnica_pdf'),
    path('cliente/historial-pagos/', views.cliente_historial_pagos_view, name='cliente_historial_pagos'),
    path('cliente/configuracion/', views.cliente_configuracion_view, name='cliente_configuracion'),
    path('cliente/configuracion/eliminar-cuenta/', views.cliente_eliminar_cuenta_view, name='cliente_eliminar_cuenta'),
    path('cliente/cancelar-cita/', views.cliente_cancelar_cita_view, name='cliente_cancelar_cita'),
    path('logout/', views.logout_view, name='logout'),
]