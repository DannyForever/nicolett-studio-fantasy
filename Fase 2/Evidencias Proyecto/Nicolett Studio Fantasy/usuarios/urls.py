from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('cliente/', views.cliente_home_view, name='cliente_home'),
    path('cliente/servicios/', views.cliente_servicios_view, name='cliente_servicios'),
    path('cliente/productos/', views.cliente_productos_view, name='cliente_productos'),
    path('cliente/agendamiento/', views.cliente_agendamiento_view, name='cliente_agendamiento'),
    path('cliente/historial/', views.cliente_historial_view, name='cliente_historial'),
    path('cliente/cancelar-cita/', views.cliente_cancelar_cita_view, name='cliente_cancelar_cita'),
    path('logout/', views.logout_view, name='logout'),
]