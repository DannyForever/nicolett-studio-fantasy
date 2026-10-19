from .models import Categoria


def categorias_servicios(request):
    return {
        'categorias_servicios': Categoria.objects.filter(activa=True).order_by('nombre'),
    }
