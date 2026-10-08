from django.shortcuts import render
from .models import Servicio

# Create your views here.
def servicios_lista_view(request):
    servicios = Servicio.objects.select_related('categoria').all()
    
    context = {
        'servicios': servicios,
    }
    
    # Asegúrate de que coincida con la ruta exacta de tu explorador de archivos:
    # Si 'servicios.html' está directamente dentro de 'templates/panel_admin/', usa esto:
    return render(request, 'panel_admin/servicios.html', context)