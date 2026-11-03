from .models import Categoria


SERVICE_CATEGORY_SCOPE = 'servicio'
PRODUCT_CATEGORY_SCOPE = 'producto'
UNCATEGORIZED_NAME = 'Sin categoría'


def categorias_servicios(request):
    service_categories = Categoria.objects.filter(
        tipo=SERVICE_CATEGORY_SCOPE,
        activa=True,
    ).exclude(
        nombre__iexact=UNCATEGORIZED_NAME,
    ).order_by('nombre')
    product_categories = Categoria.objects.filter(
        tipo=PRODUCT_CATEGORY_SCOPE,
        activa=True,
    ).exclude(
        nombre__iexact=UNCATEGORIZED_NAME,
    ).order_by('nombre')
    context = {
        'categorias_servicios': Categoria.objects.filter(activa=True).order_by('nombre'),
        'categorias_cliente_servicios': service_categories,
        'categorias_cliente_productos': product_categories,
    }
    usuario = request.user
    rol = getattr(getattr(usuario, 'rol', None), 'nombre', None)
    if usuario.is_authenticated and (usuario.is_superuser or rol == 'Admin'):
        context.update({
            'admin_service_categories': service_categories,
            'admin_product_categories': product_categories,
        })
    return context
