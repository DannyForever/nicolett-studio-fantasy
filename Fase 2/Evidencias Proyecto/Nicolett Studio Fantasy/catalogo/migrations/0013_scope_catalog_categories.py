import unicodedata

from django.db import migrations


SERVICE_CATEGORIES = (
    'Cortes & estilos',
    'Tratamientos capilares',
    'Nail care & beauty',
    'Pedicure',
    'Depilación',
    'Peinados',
    'Colorimetría',
    'Podología',
    'Lash & brow',
    'Maquillaje',
    'Sin categoría',
)


def _normalize(value):
    value = unicodedata.normalize('NFKD', value or '')
    return ''.join(char for char in value if not unicodedata.combining(char)).casefold()


def _service_category(source_name, service_name):
    source = _normalize(source_name)
    name = _normalize(service_name)
    combined = f'{source} {name}'
    if 'depil' in combined or 'laser' in combined:
        return 'Depilación'
    if 'podolog' in combined:
        return 'Podología'
    if any(term in combined for term in ('lash', 'brow', 'pestana', 'pestanas', 'ceja', 'mirada')):
        return 'Lash & brow'
    if 'pedicure' in combined or 'pedicura' in combined:
        return 'Pedicure'
    if any(term in combined for term in ('manicure', 'manicura', 'nail', 'unas')):
        return 'Nail care & beauty'
    if any(term in name for term in ('peinado', 'ondas', 'trenza', 'brushing')):
        return 'Peinados'
    if any(term in combined for term in ('colorimetr', 'tintura', 'tinte', 'balayage', 'color')):
        return 'Colorimetría'
    if any(term in combined for term in ('tratamiento', 'capilar', 'cabello')):
        return 'Tratamientos capilares'
    if any(term in combined for term in ('peluquer', 'corte')):
        return 'Cortes & estilos'
    if any(term in combined for term in ('maquillaje', 'rostro', 'facial', 'skincare')):
        return 'Maquillaje'
    return 'Sin categoría'


def scope_catalog_categories(apps, schema_editor):
    Categoria = apps.get_model('catalogo', 'Categoria')
    Producto = apps.get_model('catalogo', 'Producto')
    Servicio = apps.get_model('catalogo', 'Servicio')
    ProfesionalCategoria = apps.get_model('agenda', 'ProfesionalCategoria')
    alias = schema_editor.connection.alias

    def get_scoped_category(name, scope):
        category = Categoria.objects.using(alias).filter(
            nombre__iexact=name,
            tipo=scope,
        ).first()
        if category is None:
            category = Categoria.objects.using(alias).create(
                nombre=name,
                tipo=scope,
                activa=True,
            )
        return category

    uncategorized_service = get_scoped_category('Sin categoría', 'servicio')
    uncategorized_product = get_scoped_category('Sin categoría', 'producto')

    product_categories = {}
    product_rows = list(
        Producto.objects.using(alias).select_related('categoria').all(),
    )
    for product in product_rows:
        old_category = product.categoria
        name = old_category.nombre.strip() or 'Sin categoría'
        if _normalize(name) == _normalize('Sin categoría'):
            category = uncategorized_product
        else:
            category = product_categories.get(_normalize(name))
            if category is None:
                category = get_scoped_category(name, 'producto')
                product_categories[_normalize(name)] = category
        Producto.objects.using(alias).filter(pk=product.pk).update(categoria_id=category.pk)

    service_categories = {
        name: get_scoped_category(name, 'servicio')
        for name in SERVICE_CATEGORIES
        if name != 'Sin categoría'
    }
    service_rows = list(
        Servicio.objects.using(alias).select_related('categoria').all(),
    )
    service_category_targets = {}
    for service in service_rows:
        source_category_id = service.categoria_id
        category_name = _service_category(service.categoria.nombre, service.nombre)
        category = (
            uncategorized_service
            if category_name == 'Sin categoría'
            else service_categories[category_name]
        )
        Servicio.objects.using(alias).filter(pk=service.pk).update(categoria_id=category.pk)
        service_category_targets.setdefault(source_category_id, set()).add(category.pk)

    for relation in ProfesionalCategoria.objects.using(alias).select_related('categoria').all():
        target_ids = service_category_targets.get(relation.categoria_id, set())
        if not target_ids:
            inferred_name = _service_category(relation.categoria.nombre, '')
            if inferred_name != 'Sin categoría':
                target_ids.add(service_categories[inferred_name].pk)
        if not target_ids:
            ProfesionalCategoria.objects.using(alias).filter(pk=relation.pk).delete()
            continue
        profesional_id = relation.profesional_id
        for category_id in target_ids:
            ProfesionalCategoria.objects.using(alias).get_or_create(
                profesional_id=profesional_id,
                categoria_id=category_id,
            )
        ProfesionalCategoria.objects.using(alias).filter(pk=relation.pk).delete()

    canonical_service_names = {
        _normalize(name)
        for name in (*SERVICE_CATEGORIES, 'Sin categoría')
    }
    for category in Categoria.objects.using(alias).all().iterator():
        is_service_category = (
            category.tipo == 'servicio'
            and _normalize(category.nombre) in canonical_service_names
        )
        if category.tipo == 'producto' or is_service_category:
            Categoria.objects.using(alias).filter(pk=category.pk).update(activa=True)
        else:
            Categoria.objects.using(alias).filter(pk=category.pk).update(activa=False)


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0012_seed_nail_care_menu'),
    ]

    operations = [
        migrations.RunPython(scope_catalog_categories, migrations.RunPython.noop),
    ]
