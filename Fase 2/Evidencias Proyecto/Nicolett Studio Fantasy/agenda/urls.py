from django.urls import path

from . import views

urlpatterns = [
    path('', views.gestion_agenda_citas, name='admin_agenda'),
    path('horas-disponibles/', views.horas_disponibles_json, name='agenda_horas_disponibles'),
    path('profesionales-por-servicio/', views.profesionales_por_servicio_json, name='agenda_profesionales_por_servicio'),
    path('crear/', views.crear_reserva_manual, name='crear_reserva_manual'),
    path('disponibilidad/dia/guardar/', views.guardar_disponibilidad_dia, name='guardar_disponibilidad_dia'),
    path('disponibilidad/dia/editar/', views.editar_disponibilidad_dia, name='editar_disponibilidad_dia'),
    path('disponibilidad/grupo/eliminar/', views.eliminar_disponibilidad_grupo, name='eliminar_disponibilidad_grupo'),
    path('cerrar-dia/', views.cerrar_dia, name='cerrar_dia'),
    path('abrir-dia/<int:pk>/', views.abrir_dia, name='abrir_dia'),
    path('<int:pk>/reagendar/', views.reagendar_cita, name='reagendar_cita'),
    path('<int:pk>/cancelar/', views.cancelar_cita, name='cancelar_cita'),
    path('respuesta-suspension/<str:token>/', views.responder_suspension, name='responder_suspension'),
    path('respuesta-suspension/<str:token>/guardar/', views.guardar_respuesta_suspension, name='guardar_respuesta_suspension'),
]
