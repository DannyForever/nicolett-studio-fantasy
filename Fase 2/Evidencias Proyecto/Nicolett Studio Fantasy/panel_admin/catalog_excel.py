from io import BytesIO
from unicodedata import combining, normalize as unicode_normalize
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from .forms import ProductoForm, ServicioForm
from .models import Categoria, Producto, Servicio


MAX_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_DATA_ROWS = 1000
UNCATEGORIZED_NAME = 'Sin categoría'

CATALOGS = {
    'servicio': {
        'model': Servicio,
        'form': ServicioForm,
        'category_scope': 'servicio',
        'headers': ('ID (no editar)', 'Nombre', 'Categoría', 'Descripción', 'Precio', 'Duración (minutos)', 'Activo'),
        'filename': 'servicios',
    },
    'producto': {
        'model': Producto,
        'form': ProductoForm,
        'category_scope': 'producto',
        'headers': ('ID (no editar)', 'Nombre', 'Categoría', 'Descripción', 'Precio', 'Stock', 'Activo'),
        'filename': 'productos',
    },
}


class CatalogExcelError(ValueError):
    pass


def _header_key(value):
    text = unicode_normalize('NFKD', str(value or ''))
    return ''.join(char for char in text if not combining(char)).strip().casefold()


def _safe_excel_text(value):
    text = str(value or '')
    if text.startswith(('=', '+', '-', '@')):
        return f"'{text}"
    return text


def build_catalog_workbook(catalog_type, records=()):
    spec = CATALOGS[catalog_type]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = spec['filename'].title()
    worksheet.append(spec['headers'])

    for record in records:
        values = [
            record.pk,
            record.nombre,
            record.categoria.nombre if record.categoria_id else '',
            record.descripcion,
            record.precio,
        ]
        if catalog_type == 'servicio':
            values.append(record.duracion_minutos)
        else:
            values.append(record.stock)
        values.append('Activo' if record.activo else 'Desactivado')
        worksheet.append([
            _safe_excel_text(value) if isinstance(value, str) else value
            for value in values
        ])

    worksheet.freeze_panes = 'A2'
    worksheet.auto_filter.ref = f'A1:{get_column_letter(len(spec["headers"]))}{worksheet.max_row}'
    for column_index, header in enumerate(spec['headers'], start=1):
        worksheet.column_dimensions[get_column_letter(column_index)].width = min(
            max(len(header) + 4, 18),
            38,
        )
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output


def _cell_text(value):
    if value is None:
        return ''
    return str(value).strip()


def _active_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    normalized = _header_key(value)
    if normalized in {'true', '1', 'si', 'activo', 'activa', 'yes'}:
        return 'true'
    if normalized in {'false', '0', 'no', 'desactivado', 'inactivo', 'inactiva'}:
        return 'false'
    raise CatalogExcelError('La columna “Activo” solo acepta Sí/No o Activo/Desactivado.')


def import_catalog_workbook(uploaded_file, catalog_type, selected_category=None):
    if catalog_type not in CATALOGS:
        raise CatalogExcelError('El tipo de catálogo no es válido.')
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise CatalogExcelError('El archivo supera el límite de 5 MB.')
    if not uploaded_file.name.lower().endswith('.xlsx'):
        raise CatalogExcelError('Selecciona un archivo Excel con formato .xlsx.')

    try:
        workbook = load_workbook(uploaded_file, read_only=True, data_only=False)
    except (BadZipFile, InvalidFileException, OSError, ParseError, ValueError) as error:
        raise CatalogExcelError('No se pudo leer el archivo. Verifica que sea un Excel .xlsx válido.') from error

    spec = CATALOGS[catalog_type]
    category_type = spec['category_scope']
    if selected_category and (
        selected_category.tipo != category_type
        or not selected_category.activa
        or selected_category.nombre.casefold() == UNCATEGORIZED_NAME.casefold()
    ):
        workbook.close()
        raise CatalogExcelError('Selecciona una categoría activa para importar los registros.')

    errors = []
    forms = []
    seen = set()
    try:
        if not workbook.worksheets:
            raise CatalogExcelError('El archivo no contiene una hoja de cálculo.')
        worksheet = workbook.active
        if worksheet.max_row is not None and worksheet.max_row > MAX_DATA_ROWS + 1:
            raise CatalogExcelError(f'El archivo puede contener hasta {MAX_DATA_ROWS} registros.')
        if worksheet.max_column is not None and worksheet.max_column > len(spec['headers']):
            raise CatalogExcelError('El archivo contiene columnas adicionales al formato esperado.')

        header_cells = next(worksheet.iter_rows(min_row=1, max_row=1), ())
        if any(cell.data_type == 'f' for cell in header_cells):
            raise CatalogExcelError('Los encabezados del archivo deben ser texto, no fórmulas.')
        header_aliases = {_header_key('Estado'): _header_key('Activo')}
        normalized_headers = []
        for cell in header_cells:
            key = _header_key(cell.value)
            normalized_headers.append(header_aliases.get(key, key))
        if len(normalized_headers) != len(set(filter(None, normalized_headers))):
            raise CatalogExcelError('El archivo contiene encabezados duplicados.')
        header_indexes = {
            key: index
            for index, key in enumerate(normalized_headers)
            if key
        }
        expected_headers = {
            _header_key(header)
            for header in spec['headers']
            if header != 'ID (no editar)'
        }
        missing_headers = expected_headers - set(header_indexes)
        if missing_headers:
            raise CatalogExcelError(
                'Faltan columnas requeridas: '
                + ', '.join(
                    header
                    for header in spec['headers']
                    if _header_key(header) in missing_headers
                )
                + '.'
            )

        category_cache = {}
        categories = Categoria.objects.filter(
            tipo=category_type,
            activa=True,
        ).exclude(nombre__iexact=UNCATEGORIZED_NAME)
        for row_number, cells in enumerate(worksheet.iter_rows(min_row=2), start=2):
            if row_number > MAX_DATA_ROWS + 1:
                raise CatalogExcelError(f'El archivo puede contener hasta {MAX_DATA_ROWS} registros.')
            if all(cell.value in (None, '') for cell in cells):
                continue
            if any(cell.data_type == 'f' for cell in cells):
                errors.append(f'Fila {row_number}: no se permiten fórmulas.')
                continue

            row = {
                header: _cell_text(cells[header_indexes[_header_key(header)]].value)
                for header in spec['headers']
                if _header_key(header) in header_indexes
            }
            record = None
            record_id = row.get('ID (no editar)', '')
            if record_id:
                try:
                    record_id = int(record_id)
                except (TypeError, ValueError):
                    errors.append(f'Fila {row_number}: el ID debe ser un número entero o quedar vacío.')
                    continue
                record = spec['model'].objects.filter(
                    pk=record_id,
                    categoria__tipo=category_type,
                ).select_related('categoria').first()
                if record is None:
                    errors.append(f'Fila {row_number}: el ID {record_id} no corresponde a un registro de este catálogo.')
                    continue
                if selected_category and record.categoria_id != selected_category.pk:
                    errors.append(f'Fila {row_number}: el ID {record_id} no pertenece a la categoría seleccionada.')
                    continue
            if 'Nombre' not in row:
                errors.append(f'Fila {row_number}: falta la columna “Nombre”.')
                continue
            if 'Categoría' not in row:
                errors.append(f'Fila {row_number}: falta la columna “Categoría”.')
                continue
            for optional_header in ('Descripción',):
                row.setdefault(optional_header, '')
            category_name = row['Categoría']
            if selected_category:
                if category_name and category_name.casefold() != selected_category.nombre.casefold():
                    errors.append(
                        f'Fila {row_number}: la categoría debe ser “{selected_category.nombre}”.'
                    )
                    continue
                category = selected_category
            else:
                category_key = _header_key(category_name)
                if category_key not in category_cache:
                    category_cache[category_key] = categories.filter(
                        nombre__iexact=category_name,
                    ).first()
                category = category_cache[category_key]
                if not category:
                    errors.append(
                        f'Fila {row_number}: la categoría “{category_name}” no existe o no está activa.'
                    )
                    continue

            try:
                active = _active_value(row['Activo'])
            except CatalogExcelError as error:
                errors.append(f'Fila {row_number}: {error}')
                continue
            form_data = {
                'nombre': row['Nombre'],
                'categoria': str(category.pk),
                'descripcion': row['Descripción'],
                'precio': row['Precio'],
                'activo': active,
            }
            numeric_field = 'duracion_minutos' if catalog_type == 'servicio' else 'stock'
            source_field = 'Duración (minutos)' if catalog_type == 'servicio' else 'Stock'
            form_data[numeric_field] = row[source_field]
            form = spec['form'](
                data=form_data,
                instance=record,
                category_scope=category_type,
            )
            if not form.is_valid():
                errors.append(
                    f'Fila {row_number}: '
                    + ' '.join(
                        message
                        for field_errors in form.errors.values()
                        for message in field_errors
                    )
                )
                continue

            cleaned = form.cleaned_data
            duplicate_key = (
                category.pk,
                _header_key(cleaned['nombre']),
                _header_key(cleaned.get('descripcion')),
                cleaned['precio'],
            )
            if duplicate_key in seen:
                errors.append(
                    f'Fila {row_number}: el registro está duplicado en el archivo. '
                    'Debe diferir en nombre, descripción o precio.'
                )
                continue
            seen.add(duplicate_key)
            forms.append((form, record_id or None))
            if len(forms) > MAX_DATA_ROWS:
                raise CatalogExcelError(f'El archivo puede contener hasta {MAX_DATA_ROWS} registros.')

        if errors:
            raise CatalogExcelError(' '.join(errors[:20]))
        if not forms:
            raise CatalogExcelError('El archivo no contiene registros para importar.')
        identifiers = [identifier for _, identifier in forms if identifier]
        if len(identifiers) != len(set(identifiers)):
            raise CatalogExcelError('El archivo repite un ID en más de una fila.')

        updated_count = 0
        created_count = 0
        with transaction.atomic():
            for form, identifier in forms:
                if identifier:
                    locked_record = spec['model'].objects.select_for_update().filter(
                        pk=identifier,
                        categoria__tipo=category_type,
                    ).first()
                    if locked_record is None:
                        raise CatalogExcelError(
                            f'El registro con ID {identifier} ya no existe. No se importó ningún cambio.'
                        )
                    update_fields = (
                        'nombre',
                        'categoria',
                        'descripcion',
                        'precio',
                        numeric_field,
                        'activo',
                    )
                    for field_name in update_fields:
                        setattr(locked_record, field_name, form.cleaned_data[field_name])
                    locked_record.save(update_fields=update_fields)
                else:
                    form.save()
                if identifier:
                    updated_count += 1
                else:
                    created_count += 1
        return created_count, updated_count
    finally:
        workbook.close()
