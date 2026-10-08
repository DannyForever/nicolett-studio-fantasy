import logging

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CategoriaForm, PersonalForm, ProductoForm, ServicioForm
from .models import Servicio, Categoria, Producto
from usuarios.models import Rol, Usuario
from agenda.models import ProfesionalCategoria, Reserva

logger = logging.getLogger(__name__)


def dashboard_home(request):
    return render(request, 'panel_admin/admin_home.html')

def listar_servicios(request):
    servicios = Servicio.objects.select_related('categoria').all()
    from agenda.services import reservas_activas_futuras
    for servicio in servicios:
        servicio.citas_pendientes = reservas_activas_futuras(servicio.pk).count()
    categorias = Categoria.objects.all().order_by('nombre')
    total_activos = servicios.filter(activo=True).count()
    total_inactivos = servicios.filter(activo=False).count()
    
    context = {
        'servicios': servicios,
        'categorias': categorias,
        'total_activos': total_activos,
        'total_inactivos': total_inactivos,
    }
    return render(request, 'panel_admin/servicios_lista.html', context)

def _form_error_text(form):
    return ' '.join(
        error
        for errors in form.errors.values()
        for error in errors
    )


def _delete_unused_service_image(image_name):
    if image_name and not Servicio.objects.filter(imagen_url=image_name).exists():
        Servicio._meta.get_field('imagen_url').storage.delete(image_name)


def _delete_unused_product_image(image_name):
    if image_name and not Producto.objects.filter(imagen_url=image_name).exists():
        Producto._meta.get_field('imagen_url').storage.delete(image_name)


@require_POST
def crear_servicio(request):
    form = ServicioForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, _form_error_text(form))
        return redirect('listar_servicios')

    form.save()
    messages.success(request, 'El servicio se guardó correctamente.')
    return redirect('listar_servicios')

@require_POST
def editar_servicio(request, servicio_id):
    servicio = get_object_or_404(Servicio, id=servicio_id)
    estaba_activo = servicio.activo
    imagen_anterior = servicio.imagen_url.name
    form = ServicioForm(request.POST, request.FILES, instance=servicio)
    if not form.is_valid():
        messages.error(request, _form_error_text(form))
        return redirect('listar_servicios')

    desactivar = estaba_activo and not form.cleaned_data['activo']
    if desactivar:
        from agenda.services import reservas_activas_futuras
        citas_pendientes = reservas_activas_futuras(servicio.pk).count()
        if citas_pendientes and request.POST.get('confirmar_agenda') != '1':
            messages.warning(
                request,
                f'Hay {citas_pendientes} cita(s) futura(s) de este servicio. Confirma nuevamente para cancelar las citas y enviar aviso a los clientes.',
            )
            return redirect('listar_servicios')
    form.save()
    if desactivar:
        from agenda.services import desactivar_servicio_y_cancelar_citas
        citas_canceladas, correos, sin_correo, fallidos = desactivar_servicio_y_cancelar_citas(
            servicio.pk,
            'El servicio fue desactivado por la administración.',
        )
        if citas_canceladas:
            messages.warning(
                request,
                f'Se cancelaron {citas_canceladas} cita(s); correos enviados: {correos}, '
                f'sin email: {sin_correo}, fallidos: {fallidos}.',
            )
    imagen_nueva = servicio.imagen_url.name
    if imagen_anterior and imagen_anterior != imagen_nueva:
        try:
            _delete_unused_service_image(imagen_anterior)
        except OSError:
            logger.exception('No se pudo eliminar la imagen antigua del servicio %s.', servicio.pk)
            messages.warning(
                request,
                'El servicio se actualizó, pero no se pudo eliminar su imagen anterior del almacenamiento.',
            )
    messages.success(request, 'El servicio se actualizó correctamente.')
    return redirect('listar_servicios')

@require_POST
def eliminar_servicio(request, servicio_id):
    servicio = get_object_or_404(Servicio, id=servicio_id)
    from agenda.services import desactivar_servicio_y_cancelar_citas, reservas_activas_futuras
    citas_pendientes = reservas_activas_futuras(servicio.pk).count()
    if citas_pendientes and request.POST.get('confirmar_agenda') != '1':
        messages.warning(
            request,
            f'Hay {citas_pendientes} cita(s) futura(s) de este servicio. Confirma nuevamente para cancelarlas, notificar a los clientes y eliminarlo.',
        )
        return redirect('listar_servicios')
    imagen = servicio.imagen_url.name
    citas_canceladas, correos, sin_correo, fallidos = desactivar_servicio_y_cancelar_citas(
        servicio.pk,
        'El servicio será eliminado del catálogo.',
    )
    from agenda.models import Reserva
    Reserva.objects.filter(servicio_id=servicio.pk).update(servicio=None)
    from agenda.models import ProfesionalServicio
    ProfesionalServicio.objects.filter(servicio_id=servicio.pk).delete()
    servicio.delete()
    if imagen:
        try:
            _delete_unused_service_image(imagen)
        except OSError:
            logger.exception('No se pudo eliminar la imagen del servicio %s.', servicio_id)
            messages.warning(
                request,
                'El servicio se eliminó, pero no se pudo borrar su imagen del almacenamiento.',
            )
    if citas_canceladas:
        messages.warning(
            request,
            f'El servicio se eliminó; se cancelaron {citas_canceladas} cita(s); correos enviados: {correos}, '
            f'sin email: {sin_correo}, fallidos: {fallidos}.',
        )
    else:
        messages.success(request, 'El servicio se eliminó correctamente.')
    return redirect('listar_servicios')

@require_POST
def crear_categoria(request):
    return _guardar_categoria(request)

@require_POST
def editar_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
    return _guardar_categoria(request, categoria)

def _guardar_categoria(request, categoria=None):
    form = CategoriaForm(request.POST, instance=categoria)
    if not form.is_valid():
        errors = [error for field_errors in form.errors.values() for error in field_errors]
        return JsonResponse({'errors': errors}, status=400)

    categoria = form.save()
    return JsonResponse({
        'id': categoria.pk,
        'nombre': categoria.nombre,
        'tipo': categoria.tipo,
        'message': 'Categoría guardada correctamente.',
    })

@require_POST
def eliminar_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
    if (
        Servicio.objects.filter(categoria=categoria).exists()
        or Producto.objects.filter(categoria=categoria).exists()
    ):
        return JsonResponse(
            {'errors': ['No se puede eliminar esta categoría porque tiene servicios o productos asociados.']},
            status=409,
        )

    with transaction.atomic():
        ProfesionalCategoria.objects.filter(categoria_id=categoria.pk).delete()
        categoria.delete()
    return JsonResponse({'id': categoria_id, 'message': 'Categoría eliminada correctamente.'})

@require_POST
def cambiar_estado_servicio(request, servicio_id):
    servicio = get_object_or_404(Servicio, id=servicio_id)
    if servicio.activo:
        from agenda.services import desactivar_servicio_y_cancelar_citas, reservas_activas_futuras
        citas_pendientes = reservas_activas_futuras(servicio.pk).count()
        if citas_pendientes and request.POST.get('confirmar_agenda') != '1':
            messages.warning(
                request,
                f'Hay {citas_pendientes} cita(s) futura(s) de este servicio. Confirma nuevamente para cancelarlas y avisar a sus clientes.',
            )
            return redirect('listar_servicios')
        citas_canceladas, correos, sin_correo, fallidos = desactivar_servicio_y_cancelar_citas(
            servicio.pk,
            'El servicio fue desactivado por la administración.',
        )
        if citas_canceladas:
            messages.warning(
                request,
                f'Se cancelaron {citas_canceladas} cita(s); correos enviados: {correos}, '
                f'sin email: {sin_correo}, fallidos: {fallidos}.',
            )
    servicio.activo = False if servicio.activo else True
    servicio.save(update_fields=['activo'])
    estado = 'activado' if servicio.activo else 'desactivado'
    messages.success(request, f'El servicio quedó {estado} correctamente.')
    return redirect('listar_servicios')

# Funciones temporales para el resto de módulos (las iremos detallando una a una)
def lista_productos(request):
    productos = Producto.objects.select_related('categoria').all()
    context = {
        'productos': productos,
        'categorias': Categoria.objects.filter(activa=True).order_by('nombre'),
        'total_activos': productos.filter(activo=True).count(),
        'total_inactivos': productos.filter(activo=False).count(),
    }
    return render(request, 'panel_admin/productos_lista.html', context)


@require_POST
def crear_producto(request):
    form = ProductoForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, _form_error_text(form))
        return redirect('admin_productos')

    form.save()
    messages.success(request, 'El producto se guardó correctamente.')
    return redirect('admin_productos')


@require_POST
def editar_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    imagen_anterior = producto.imagen_url.name
    form = ProductoForm(request.POST, request.FILES, instance=producto)
    if not form.is_valid():
        messages.error(request, _form_error_text(form))
        return redirect('admin_productos')

    form.save()
    imagen_nueva = producto.imagen_url.name
    if imagen_anterior and imagen_anterior != imagen_nueva:
        try:
            _delete_unused_product_image(imagen_anterior)
        except OSError:
            logger.exception('No se pudo eliminar la imagen antigua del producto %s.', producto.pk)
            messages.warning(
                request,
                'El producto se actualizó, pero no se pudo eliminar su imagen anterior del almacenamiento.',
            )
    messages.success(request, 'El producto se actualizó correctamente.')
    return redirect('admin_productos')


@require_POST
def eliminar_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    imagen = producto.imagen_url.name
    producto.delete()
    if imagen:
        try:
            _delete_unused_product_image(imagen)
        except OSError:
            logger.exception('No se pudo eliminar la imagen del producto %s.', pk)
            messages.warning(
                request,
                'El producto se eliminó, pero no se pudo borrar su imagen del almacenamiento.',
            )
    messages.success(request, 'El producto se eliminó correctamente.')
    return redirect('admin_productos')


@require_POST
def cambiar_estado_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    producto.activo = not producto.activo
    producto.save(update_fields=['activo'])
    estado = 'activado' if producto.activo else 'desactivado'
    messages.success(request, f'El producto quedó {estado} correctamente.')
    return redirect('admin_productos')

def lista_fichas_clientes(request): pass
def detalle_ficha_cliente(request, pk): pass

def configurar_google_calendar(request): return render(request, 'panel_admin/base_dashboard.html')
def gestionar_disponibilidad_horaria(request): pass

def lista_ventas(request): return render(request, 'panel_admin/base_dashboard.html')
def detalle_venta(request, pk): pass

def gestion_recordatorios(request): return render(request, 'panel_admin/base_dashboard.html')

def _contexto_personal(personal_form=None, form_action=None, form_is_edit=False):
    personal = Usuario.objects.filter(
        rol__nombre__iexact='Colaborador',
        deleted_at__isnull=True,
    ).prefetch_related('especialidades__categoria').order_by(
        'nombre',
        'apellido_paterno',
        'apellido_materno',
    )
    for colaborador in personal:
        colaborador.especializacion_ids = [
            str(especialidad.categoria_id)
            for especialidad in colaborador.especialidades.all()
        ]
    personal_form = personal_form or PersonalForm()
    return {
        'personal': personal,
        'total_activos': personal.filter(is_active=True).count(),
        'total_inactivos': personal.filter(is_active=False).count(),
        'personal_form': personal_form,
        'form_action': form_action or reverse('crear_personal'),
        'form_is_edit': form_is_edit,
        'form_has_errors': bool(personal_form.errors),
    }


def lista_personal(request):
    return render(
        request,
        'panel_admin/personal_lista.html',
        _contexto_personal(),
    )


def _guardar_especializaciones(colaborador, categorias):
    ProfesionalCategoria.objects.filter(profesional=colaborador).delete()
    ProfesionalCategoria.objects.bulk_create([
        ProfesionalCategoria(
            profesional=colaborador,
            categoria_id=categoria.pk,
        )
        for categoria in categorias
    ])


@require_POST
def crear_personal(request):
    form = PersonalForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            'panel_admin/personal_lista.html',
            _contexto_personal(personal_form=form),
        )

    rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
    with transaction.atomic():
        colaborador = form.save(commit=False)
        colaborador.rol = rol_colaborador
        colaborador.is_active = True
        colaborador.is_staff = True
        colaborador.is_superuser = False
        colaborador.acepta_terminos_at = timezone.now()
        colaborador.deleted_at = None
        colaborador.set_unusable_password()
        colaborador.save()
        _guardar_especializaciones(
            colaborador,
            form.cleaned_data['especializaciones'],
        )
    messages.success(
        request,
        'El colaborador se agregó correctamente. No se creó una contraseña ni acceso al sistema.',
    )
    return redirect('admin_personal')


@require_POST
def editar_personal(request, pk):
    colaborador = get_object_or_404(Usuario, pk=pk, rol__nombre__iexact='Colaborador')
    form = PersonalForm(request.POST, instance=colaborador)
    if not form.is_valid():
        return render(
            request,
            'panel_admin/personal_lista.html',
            _contexto_personal(
                personal_form=form,
                form_action=reverse('editar_personal', args=[colaborador.pk]),
                form_is_edit=True,
            ),
        )

    with transaction.atomic():
        colaborador = form.save()
        _guardar_especializaciones(
            colaborador,
            form.cleaned_data['especializaciones'],
        )
    messages.success(request, 'Los datos del colaborador se actualizaron correctamente.')
    return redirect('admin_personal')


@require_POST
def eliminar_personal(request, pk):
    colaborador = get_object_or_404(
        Usuario,
        pk=pk,
        rol__nombre__iexact='Colaborador',
        deleted_at__isnull=True,
    )
    if Reserva.objects.filter(profesional=colaborador).exists():
        colaborador.is_active = False
        colaborador.deleted_at = timezone.now()
        colaborador.save(update_fields=['is_active', 'deleted_at'])
        messages.warning(
            request,
            'El colaborador se retiró del personal y ya no estará disponible para nuevas citas. '
            'Se conservó el registro para mantener el historial de agendamientos.',
        )
    else:
        colaborador.delete()
        messages.success(request, 'El colaborador se eliminó correctamente.')
    return redirect('admin_personal')


@require_POST
def desactivar_personal(request, pk):
    colaborador = get_object_or_404(Usuario, pk=pk, rol__nombre__iexact='Colaborador')
    colaborador.is_active = not colaborador.is_active
    colaborador.save(update_fields=['is_active'])
    estado = 'activado' if colaborador.is_active else 'desactivado'
    messages.success(request, f'El colaborador quedó {estado}.')
    return redirect('admin_personal')