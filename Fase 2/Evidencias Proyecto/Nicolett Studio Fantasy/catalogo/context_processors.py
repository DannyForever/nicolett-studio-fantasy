from .models import Categoria


SERVICE_CATEGORY_SCOPE = 'servicio'
PRODUCT_CATEGORY_SCOPE = 'producto'
UNCATEGORIZED_NAME = 'Sin categoría'


def categorias_servicios(request):
    context = {
        'categorias_servicios': Categoria.objects.filter(activa=True).order_by('nombre'),
    }
    usuario = request.user
    rol = getattr(getattr(usuario, 'rol', None), 'nombre', None)
    if usuario.is_authenticated and (usuario.is_superuser or rol == 'Admin'):
        context.update({
            'admin_service_categories': Categoria.objects.filter(
                tipo=SERVICE_CATEGORY_SCOPE,
                activa=True,
            ).exclude(
                nombre__iexact=UNCATEGORIZED_NAME,
            ).order_by('nombre'),
            'admin_product_categories': Categoria.objects.filter(
                tipo=PRODUCT_CATEGORY_SCOPE,
                activa=True,
            ).exclude(
                nombre__iexact=UNCATEGORIZED_NAME,
            ).order_by('nombre'),
        })
    return context
