import logging
import smtplib
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_POST

from config.formatters import formatear_miles_clp

from .forms import (
    AdminPasswordChangeForm,
    AdminProfileForm,
    CategoriaForm,
    ColaboradorPasswordResetForm,
    PersonalForm,
    ProductoForm,
    ServicioForm,
)
from .models import Servicio, Categoria, Producto
from usuarios.models import Rol, Usuario
from usuarios.permissions import es_administrador, es_colaborador
from agenda.models import (
    Disponibilidad,
    ProfesionalCategoria,
    Reserva,
    ServicioDesactivadoPorPersonal,
)
from notificaciones.recordatorios import listar_recordatorios_pendientes
from notificaciones.models import ProgramacionRecordatorio
from pagos.models import Pago
from ventas.models import Venta
from notificaciones.recordatorios import construir_mensaje_recordatorio

logger = logging.getLogger(__name__)

SERVICE_CATEGORY_SCOPE = 'servicio'
PRODUCT_CATEGORY_SCOPE = 'producto'
UNCATEGORIZED_CATEGORY_NAME = 'Sin categoría'


def _formatear_miles_clp(valor):
    return formatear_miles_clp(valor)


def _enlace_whatsapp_recordatorio(tarea):
    reserva = tarea['reserva']
    telefono = reserva.cliente_telefono or (
        reserva.cliente.telefono if reserva.cliente_id else ''
    )
    numero = ''.join(caracter for caracter in telefono if caracter.isdigit())
    if len(numero) == 9 and numero.startswith('9'):
        numero = f'56{numero}'
    if len(numero) != 11 or not numero.startswith('569'):
        return {'numero': '', 'mensaje': ''}

    return {
        'numero': numero,
        'mensaje': construir_mensaje_recordatorio(reserva, tarea['tipo']),
    }


def dashboard_home(request):
    hoy = timezone.localdate()
    citas_hoy = Reserva.objects.select_related(
        'cliente', 'profesional', 'servicio',
    ).filter(fecha_hora__date=hoy).order_by('fecha_hora')
    proximas_citas = Reserva.objects.select_related(
        'cliente', 'profesional', 'servicio',
    ).filter(
        fecha_hora__date__gte=hoy,
    ).exclude(
        estado__in=['cancelada', 'completada'],
    ).order_by('fecha_hora')
    ventas_mes = Venta.objects.filter(
        fecha_venta__year=hoy.year,
        fecha_venta__month=hoy.month,
    ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    return render(request, 'panel_admin/admin_home.html', {
        'proximas_citas': proximas_citas,
        'total_citas_hoy': citas_hoy.count(),
        'ventas_mes': ventas_mes,
        'ventas_mes_formateado': _formatear_miles_clp(ventas_mes),
        'servicios_activos': Servicio.objects.filter(activo=True).count(),
        'productos_activos': Producto.objects.filter(activo=True).count(),
    })


def servicios_semana_admin(request):
    from agenda.views import servicios_con_horarios_disponibles
    from usuarios.views import _agrupar_servicios_galeria

    servicios = Servicio.objects.filter(
        activo=True,
        pk__in=servicios_con_horarios_disponibles(),
    ).select_related('categoria').order_by('nombre')
    return render(
        request,
        'usuarios/cliente_seccion.html',
        {
            'titulo': 'Servicios',
            'descripcion': 'Aquí podrás conocer los servicios disponibles.',
            'servicios': servicios,
            'servicios_galeria': _agrupar_servicios_galeria(servicios),
            'base_template': 'panel_admin/base_dashboard.html',
            'vista_admin': True,
        },
    )


def listar_servicios(request):
    servicios = Servicio.objects.select_related('categoria').all()
    categorias_panel = Categoria.objects.filter(
        tipo=SERVICE_CATEGORY_SCOPE,
        activa=True,
    ).exclude(
        nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
    ).order_by('nombre').annotate(
        total_items=Count('servicio'),
    )
    categoria_sin_categoria = get_object_or_404(
        Categoria,
        tipo=SERVICE_CATEGORY_SCOPE,
        nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
    )
    categoria_sin_categoria.total_items = Servicio.objects.filter(
        categoria=categoria_sin_categoria,
    ).count()
    categoria_id = request.GET.get('categoria')
    categoria_seleccionada = (
        get_object_or_404(
            Categoria.objects.filter(tipo=SERVICE_CATEGORY_SCOPE),
            pk=categoria_id,
        )
        if categoria_id
        else None
    )
    mostrar_listado = categoria_seleccionada is not None or request.GET.get('todos') == '1'
    if categoria_seleccionada:
        servicios = servicios.filter(categoria_id=categoria_seleccionada.pk)

    from agenda.services import reservas_activas_futuras
    for servicio in servicios:
        servicio.citas_pendientes = reservas_activas_futuras(servicio.pk).count()
    categorias = Categoria.objects.filter(
        tipo=SERVICE_CATEGORY_SCOPE,
        activa=True,
    ).exclude(
        nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
    ).order_by('nombre')
    todos_servicios = Servicio.objects.all()
    total_activos = todos_servicios.filter(activo=True).count()
    total_inactivos = todos_servicios.filter(activo=False).count()
    
    context = {
        'servicios': servicios,
        'categorias': categorias,
        'categorias_panel': categorias_panel,
        'categoria_sin_categoria': categoria_sin_categoria,
        'categoria_seleccionada': categoria_seleccionada,
        'mostrar_listado': mostrar_listado,
        'total_servicios': total_activos + total_inactivos,
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
    form = ServicioForm(
        request.POST,
        request.FILES,
        category_scope=SERVICE_CATEGORY_SCOPE,
    )
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
    form = ServicioForm(
        request.POST,
        request.FILES,
        instance=servicio,
        category_scope=SERVICE_CATEGORY_SCOPE,
    )
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
    if form.cleaned_data['activo'] != estaba_activo:
        ServicioDesactivadoPorPersonal.objects.filter(servicio_id=servicio.pk).delete()
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
    ServicioDesactivadoPorPersonal.objects.filter(servicio_id=servicio.pk).delete()
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
    categoria = get_object_or_404(
        Categoria,
        id=categoria_id,
        tipo=request.POST.get('tipo', ''),
    )
    if categoria.nombre.casefold() == UNCATEGORIZED_CATEGORY_NAME.casefold():
        return JsonResponse({'errors': ['La categoría "Sin categoría" está reservada.']}, status=400)
    return _guardar_categoria(request, categoria)

def _guardar_categoria(request, categoria=None):
    tipo = request.POST.get('tipo', '')
    if tipo not in (SERVICE_CATEGORY_SCOPE, PRODUCT_CATEGORY_SCOPE):
        return JsonResponse({'errors': ['Selecciona el catálogo de la categoría.']}, status=400)
    if categoria and categoria.tipo != tipo:
        return JsonResponse({'errors': ['La categoría no pertenece a este catálogo.']}, status=400)

    form = CategoriaForm(request.POST, instance=categoria)
    if not form.is_valid():
        errors = [error for field_errors in form.errors.values() for error in field_errors]
        return JsonResponse({'errors': errors}, status=400)

    nombre = form.cleaned_data['nombre']
    duplicada = Categoria.objects.filter(
        nombre__iexact=nombre,
        tipo=tipo,
    )
    if categoria:
        duplicada = duplicada.exclude(pk=categoria.pk)
    if duplicada.exists():
        return JsonResponse({'errors': ['Ya existe una categoría con ese nombre en este catálogo.']}, status=400)

    if nombre.casefold() == UNCATEGORIZED_CATEGORY_NAME.casefold():
        return JsonResponse({'errors': ['Ese nombre está reservado para la categoría automática.']}, status=400)

    categoria = form.save()
    categoria.tipo = tipo
    categoria.save(update_fields=['tipo'])
    return JsonResponse({
        'id': categoria.pk,
        'nombre': categoria.nombre,
        'tipo': categoria.tipo,
        'url': reverse(
            'listar_servicios' if tipo == SERVICE_CATEGORY_SCOPE else 'admin_productos',
        ) + f'?categoria={categoria.pk}',
        'message': 'Categoría guardada correctamente.',
    })

@require_POST
def eliminar_categoria(request, categoria_id):
    tipo = request.POST.get('tipo', '')
    if tipo not in (SERVICE_CATEGORY_SCOPE, PRODUCT_CATEGORY_SCOPE):
        return JsonResponse({'errors': ['Selecciona el catálogo de la categoría.']}, status=400)
    categoria = get_object_or_404(Categoria, id=categoria_id, tipo=tipo)
    if categoria.nombre.casefold() == UNCATEGORIZED_CATEGORY_NAME.casefold():
        return JsonResponse({'errors': ['No se puede eliminar la categoría "Sin categoría".']}, status=400)

    registros = (
        Servicio.objects.filter(categoria=categoria)
        if tipo == SERVICE_CATEGORY_SCOPE
        else Producto.objects.filter(categoria=categoria)
    )
    total_registros = registros.count()
    if total_registros and request.POST.get('confirmar') != '1':
        return JsonResponse(
            {
                'errors': [
                    f'Esta categoría tiene {total_registros} registro(s). Si continúas, se moverán a "Sin categoría".'
                ],
                'requires_confirmation': True,
                'count': total_registros,
            },
            status=409,
        )

    with transaction.atomic():
        ProfesionalCategoria.objects.filter(categoria_id=categoria.pk).delete()
        if total_registros:
            sin_categoria = get_object_or_404(
                Categoria,
                tipo=tipo,
                nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
            )
            registros.update(categoria=sin_categoria)
        categoria.delete()
    return JsonResponse({
        'id': categoria_id,
        'message': (
            f'Categoría eliminada; {total_registros} registro(s) se movieron a "Sin categoría".'
            if total_registros
            else 'Categoría eliminada correctamente.'
        ),
    })

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
    ServicioDesactivadoPorPersonal.objects.filter(servicio_id=servicio.pk).delete()
    estado = 'activado' if servicio.activo else 'desactivado'
    messages.success(request, f'El servicio quedó {estado} correctamente.')
    return redirect('listar_servicios')

# Funciones temporales para el resto de módulos (las iremos detallando una a una)
def lista_productos(request):
    productos = Producto.objects.select_related('categoria').all()
    categorias_panel = Categoria.objects.filter(
        tipo=PRODUCT_CATEGORY_SCOPE,
        activa=True,
    ).exclude(
        nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
    ).order_by('nombre').annotate(
        total_items=Count('productos'),
    )
    categoria_sin_categoria = get_object_or_404(
        Categoria,
        tipo=PRODUCT_CATEGORY_SCOPE,
        nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
    )
    categoria_sin_categoria.total_items = Producto.objects.filter(
        categoria=categoria_sin_categoria,
    ).count()
    categoria_id = request.GET.get('categoria')
    categoria_seleccionada = (
        get_object_or_404(
            Categoria.objects.filter(tipo=PRODUCT_CATEGORY_SCOPE),
            pk=categoria_id,
        )
        if categoria_id
        else None
    )
    mostrar_listado = categoria_seleccionada is not None or request.GET.get('todos') == '1'
    if categoria_seleccionada:
        productos = productos.filter(categoria_id=categoria_seleccionada.pk)

    todos_productos = Producto.objects.all()
    context = {
        'productos': productos,
        'categorias': Categoria.objects.filter(
            tipo=PRODUCT_CATEGORY_SCOPE,
            activa=True,
        ).exclude(
            nombre__iexact=UNCATEGORIZED_CATEGORY_NAME,
        ).order_by('nombre'),
        'categorias_panel': categorias_panel,
        'categoria_sin_categoria': categoria_sin_categoria,
        'categoria_seleccionada': categoria_seleccionada,
        'mostrar_listado': mostrar_listado,
        'categorias_admin': Categoria.objects.filter(
            tipo=PRODUCT_CATEGORY_SCOPE,
            activa=True,
        ).order_by('nombre'),
        'total_activos': todos_productos.filter(activo=True).count(),
        'total_inactivos': todos_productos.filter(activo=False).count(),
    }
    context['total_productos'] = context['total_activos'] + context['total_inactivos']
    return render(request, 'panel_admin/productos_lista.html', context)


@login_required(login_url='login')
def configuracion_admin(request):
    es_colaborador_actual = es_colaborador(request.user)
    if not es_administrador(request.user) and not es_colaborador_actual:
        return HttpResponseForbidden()
    ruta_configuracion = (
        'colaborador_configuracion' if es_colaborador_actual else 'admin_configuracion'
    )

    perfil_form = AdminProfileForm(instance=request.user)
    password_form = AdminPasswordChangeForm(request.user)
    perfil_editando = False
    if request.method == 'POST':
        if request.POST.get('form_type') == 'password':
            password_form = AdminPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                request.user.set_password(password_form.cleaned_data['nueva'])
                request.user.save(update_fields=['password'])
                update_session_auth_hash(request, request.user)
                messages.success(request, 'La contraseña se actualizó correctamente.')
                return redirect(ruta_configuracion)
        elif request.POST.get('form_type') == 'profile' and request.POST.get('profile_edit') == '1':
            perfil_editando = True
            perfil_form = AdminProfileForm(request.POST, instance=request.user)
            if perfil_form.is_valid():
                perfil_form.save()
                messages.success(request, 'Los datos personales se actualizaron correctamente.')
                return redirect(ruta_configuracion)
        elif request.POST.get('form_type') == 'profile':
            messages.error(request, 'Activa la edición antes de guardar los datos personales.')
            return redirect(ruta_configuracion)

    for field in perfil_form.fields.values():
        attrs = field.widget.attrs
        classes = attrs.get('class', '')
        if perfil_editando:
            attrs.pop('readonly', None)
            attrs['class'] = ' '.join(
                clase for clase in classes.split() if clase not in {'bg-light', 'text-muted'}
            )
        else:
            attrs['readonly'] = True
            attrs['class'] = f'{classes} bg-light text-muted'.strip()

    return render(
        request,
        'panel_admin/configuracion_admin.html',
        {
            'perfil_form': perfil_form,
            'password_form': password_form,
            'perfil_editando': perfil_editando,
            'es_colaborador': es_colaborador_actual,
        },
    )


@require_POST
def crear_producto(request):
    form = ProductoForm(
        request.POST,
        request.FILES,
        category_scope=PRODUCT_CATEGORY_SCOPE,
    )
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
    form = ProductoForm(
        request.POST,
        request.FILES,
        instance=producto,
        category_scope=PRODUCT_CATEGORY_SCOPE,
    )
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

def configurar_google_calendar(request): return render(request, 'panel_admin/base_dashboard.html')
def gestionar_disponibilidad_horaria(request): pass


def lista_ventas(request):
    busqueda = request.GET.get('q', '').strip()
    estado_venta = request.GET.get('estado_venta', '').strip()
    estado_pago = request.GET.get('estado_pago', '').strip()

    ventas = Venta.objects.select_related('cliente').prefetch_related('pagos').order_by('-fecha_venta')
    if estado_venta:
        ventas = ventas.filter(estado__iexact=estado_venta)
    if busqueda:
        criterio = (
            Q(cliente__nombre__icontains=busqueda)
            | Q(cliente__apellido_paterno__icontains=busqueda)
            | Q(cliente__apellido_materno__icontains=busqueda)
            | Q(cliente__email__icontains=busqueda)
        )
        if busqueda.isdecimal():
            criterio |= Q(pk=int(busqueda))
        ventas = ventas.filter(criterio)

    for venta in ventas:
        venta.total_pagado = sum(
            (
                pago.monto for pago in venta.pagos.all()
                if pago.estado_pago.casefold() == 'aprobado'
            ),
            Decimal('0.00'),
        )
        venta.saldo_pendiente = max(venta.total - venta.total_pagado, Decimal('0.00'))
        venta.estado_mostrado = 'Completada' if venta.saldo_pendiente == 0 else venta.estado

    pagos = Pago.objects.select_related('venta', 'venta__cliente').order_by('-fecha_pago')
    if estado_pago:
        pagos = pagos.filter(estado_pago__iexact=estado_pago)
    if busqueda:
        criterio_pago = (
            Q(venta__cliente__nombre__icontains=busqueda)
            | Q(venta__cliente__apellido_paterno__icontains=busqueda)
            | Q(venta__cliente__apellido_materno__icontains=busqueda)
            | Q(venta__cliente__email__icontains=busqueda)
            | Q(metodo_pago__icontains=busqueda)
            | Q(transaccion_id__icontains=busqueda)
        )
        if busqueda.isdecimal():
            criterio_pago |= Q(venta_id=int(busqueda))
        pagos = pagos.filter(criterio_pago)

    hoy = timezone.localdate()
    ventas_mes = Venta.objects.filter(
        fecha_venta__year=hoy.year,
        fecha_venta__month=hoy.month,
    ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    pagos_aprobados_mes = Pago.objects.filter(
        fecha_pago__year=hoy.year,
        fecha_pago__month=hoy.month,
        estado_pago__iexact='Aprobado',
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    return render(request, 'panel_admin/ventas_lista.html', {
        'ventas': ventas,
        'pagos': pagos,
        'busqueda': busqueda,
        'estado_venta': estado_venta,
        'estado_pago': estado_pago,
        'estados_venta': Venta.objects.order_by().values_list('estado', flat=True).distinct(),
        'estados_pago': Pago.objects.order_by().values_list('estado_pago', flat=True).distinct(),
        'total_ventas': Venta.objects.count(),
        'total_pagos': Pago.objects.count(),
        'ventas_mes': ventas_mes,
        'ventas_mes_formateado': _formatear_miles_clp(ventas_mes),
        'pagos_aprobados_mes': pagos_aprobados_mes,
        'pagos_aprobados_mes_formateado': _formatear_miles_clp(pagos_aprobados_mes),
    })


@login_required(login_url='login')
@require_POST
def registrar_pago_saldo_venta(request, pk):
    if not es_administrador(request.user):
        return HttpResponseForbidden()

    metodos_pago = {
        'efectivo': 'Efectivo presencial',
        'transferencia': 'Transferencia',
        'tarjeta': 'Tarjeta presencial',
        'otro': 'Otro medio presencial',
    }
    metodo_seleccionado = request.POST.get('metodo_pago', '')
    if metodo_seleccionado not in metodos_pago:
        messages.error(request, 'Selecciona un método de pago válido.')
        return redirect('admin_ventas')

    with transaction.atomic():
        venta = get_object_or_404(
            Venta.objects.select_for_update().select_related('cliente').prefetch_related('pagos'),
            pk=pk,
        )
        total_pagado = sum(
            (
                pago.monto for pago in venta.pagos.all()
                if pago.estado_pago.casefold() == 'aprobado'
            ),
            Decimal('0.00'),
        )
        saldo_pendiente = max(venta.total - total_pagado, Decimal('0.00'))
        if saldo_pendiente == 0:
            messages.info(request, 'Esta venta ya está completamente pagada.')
            return redirect('admin_ventas')

        Pago.objects.create(
            venta=venta,
            monto=saldo_pendiente,
            metodo_pago=metodos_pago[metodo_seleccionado],
            estado_pago='Aprobado',
            transaccion_id=f'PRESENCIAL-{uuid4()}',
        )
        venta.estado = 'Completada'
        venta.save(update_fields=['estado'])

    messages.success(
        request,
        f'Pago de {formatear_miles_clp(saldo_pendiente)} registrado. '
        f'El folio #{venta.pk} quedó completado.',
    )
    return redirect('admin_ventas')


def detalle_venta(request, pk):
    venta = get_object_or_404(
        Venta.objects.select_related('cliente').prefetch_related(
            'detalles__producto',
            'detalles__servicio',
            'pagos',
        ),
        pk=pk,
    )
    venta.total_pagado = sum(
        (
            pago.monto for pago in venta.pagos.all()
            if pago.estado_pago.casefold() == 'aprobado'
        ),
        Decimal('0.00'),
    )
    venta.saldo_pendiente = max(venta.total - venta.total_pagado, Decimal('0.00'))
    return render(request, 'panel_admin/venta_detalle.html', {'venta': venta})


@login_required(login_url='login')
def gestion_recordatorios(request):
    es_colaborador_actual = es_colaborador(request.user)
    if not es_administrador(request.user) and not es_colaborador_actual:
        return HttpResponseForbidden()
    if request.method != 'GET':
        return HttpResponseForbidden()
    busqueda = request.GET.get('q', '').strip()
    tareas = listar_recordatorios_pendientes()
    if es_colaborador_actual:
        tareas = [
            tarea for tarea in tareas
            if tarea['reserva'].profesional_id == request.user.pk
        ]
    if busqueda:
        busqueda_normalizada = busqueda.casefold()
        tareas = [
            tarea for tarea in tareas
            if busqueda_normalizada in ' '.join((
                tarea['reserva'].nombre_cliente,
                tarea['reserva'].correo_cliente,
                tarea['reserva'].correo_cliente,
                tarea['reserva'].cliente_telefono,
                tarea['reserva'].servicio_nombre,
                str(tarea['reserva'].servicio or ''),
                str(tarea['reserva'].profesional or ''),
            )).casefold()
        ]
    fecha_cita = request.GET.get('fecha_cita', '').strip()
    fecha_seguimiento = request.GET.get('fecha_seguimiento', '').strip()
    try:
        fecha_cita_filtro = date.fromisoformat(fecha_cita) if fecha_cita else None
    except ValueError:
        fecha_cita_filtro = None
        messages.error(request, 'La fecha de búsqueda de citas no es válida.')
    try:
        fecha_seguimiento_filtro = (
            date.fromisoformat(fecha_seguimiento) if fecha_seguimiento else None
        )
    except ValueError:
        fecha_seguimiento_filtro = None
        messages.error(request, 'La fecha de búsqueda de seguimiento no es válida.')

    recordatorios_cita = [tarea for tarea in tareas if tarea['tipo'] == 'cita']
    recordatorios_seguimiento = [tarea for tarea in tareas if tarea['tipo'] == 'seguimiento']
    if fecha_cita_filtro:
        recordatorios_cita = [
            tarea for tarea in recordatorios_cita
            if timezone.localtime(tarea['reserva'].fecha_hora).date() == fecha_cita_filtro
        ]
    if fecha_seguimiento_filtro:
        recordatorios_seguimiento = [
            tarea for tarea in recordatorios_seguimiento
            if timezone.localtime(tarea['reserva'].fecha_hora).date()
            == fecha_seguimiento_filtro
        ]

    for tarea in recordatorios_cita + recordatorios_seguimiento:
        datos_whatsapp = _enlace_whatsapp_recordatorio(tarea)
        tarea['whatsapp_numero'] = datos_whatsapp['numero']
        tarea['whatsapp_mensaje'] = datos_whatsapp['mensaje']
        tarea['usar_whatsapp'] = (
            tarea['tipo'] == 'cita' or not tarea['reserva'].correo_cliente
        )
        tarea['programado_input'] = timezone.localtime(
            tarea['programado'],
        ).strftime('%Y-%m-%dT%H:%M')
        tarea['limite_cita_input'] = timezone.localtime(
            tarea['reserva'].fecha_hora,
        ).strftime('%Y-%m-%dT%H:%M')
        tarea['fin_atencion_input'] = timezone.localtime(
            tarea['reserva'].fecha_hora
            + timedelta(minutes=tarea['reserva'].duracion_minutos),
        ).strftime('%Y-%m-%dT%H:%M')

    return render(request, 'panel_admin/recordatorios_lista.html', {
        'recordatorios_cita': recordatorios_cita,
        'recordatorios_seguimiento': recordatorios_seguimiento,
        'busqueda': busqueda,
        'fecha_cita': fecha_cita,
        'fecha_seguimiento': fecha_seguimiento,
        'es_colaborador': es_colaborador_actual,
    })


@login_required(login_url='login')
@require_POST
def programar_recordatorio(request, reserva_id):
    es_colaborador_actual = es_colaborador(request.user)
    if not es_administrador(request.user) and not es_colaborador_actual:
        return HttpResponseForbidden()
    tipo = request.POST.get('tipo', '')
    if tipo not in {'cita', 'seguimiento'}:
        messages.error(request, 'El tipo de recordatorio indicado no es válido.')
        return redirect('admin_recordatorios')
    try:
        desfase = int(request.POST.get('desfase', ''))
    except ValueError:
        messages.error(request, 'El intervalo del recordatorio no es válido.')
        return redirect('admin_recordatorios')
    tarea = next((
        item for item in listar_recordatorios_pendientes()
        if item['reserva'].pk == reserva_id
        and (
            not es_colaborador_actual
            or item['reserva'].profesional_id == request.user.pk
        )
        and item['tipo'] == tipo
        and item['desfase'] == desfase
    ), None)
    if tarea is None:
        messages.error(request, 'Este aviso ya fue enviado o la cita ya no está vigente.')
        return redirect('admin_recordatorios')
    if not tarea['reserva'].correo_cliente:
        messages.error(request, 'La cita no tiene un correo electrónico registrado.')
        return redirect('admin_recordatorios')
    try:
        programado_naive = datetime.fromisoformat(
            request.POST.get('programado_para', '').strip(),
        )
    except ValueError:
        messages.error(request, 'Indica una fecha y hora válida para el recordatorio.')
        return redirect('admin_recordatorios')
    programado = (
        timezone.make_aware(programado_naive)
        if timezone.is_naive(programado_naive)
        else programado_naive
    )
    reserva = tarea['reserva']
    if tipo == 'cita' and programado >= reserva.fecha_hora:
        messages.error(request, 'El recordatorio de cita debe programarse antes de la hora de atención.')
        return redirect('admin_recordatorios')
    fin_atencion = reserva.fecha_hora + timedelta(minutes=reserva.duracion_minutos)
    if tipo == 'seguimiento' and programado < fin_atencion:
        messages.error(request, 'El seguimiento debe programarse después de finalizar la atención.')
        return redirect('admin_recordatorios')

    programacion, _ = ProgramacionRecordatorio.objects.update_or_create(
        reserva=reserva,
        tipo=tipo,
        desfase=desfase,
        fecha_hora_cita=reserva.fecha_hora,
        defaults={
            'programado_para': programado,
            'enviado_en': None,
        },
    )
    messages.success(
        request,
        f'El {("recordatorio" if tipo == "cita" else "seguimiento")} para '
        f'{reserva.nombre_cliente or "el cliente"} quedó programado para '
        f'{timezone.localtime(programacion.programado_para):%d-%m-%Y %H:%M}.',
    )
    return redirect('admin_recordatorios')


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
    reservas_por_personal = dict(
        Reserva.objects.filter(
            profesional__in=personal,
            fecha_hora__gte=timezone.now(),
        ).exclude(
            estado__in=['cancelada', 'completada'],
        ).values(
            'profesional_id',
        ).annotate(
            cantidad=Count('pk'),
        ).values_list('profesional_id', 'cantidad')
    )
    for colaborador in personal:
        colaborador.citas_futuras_count = reservas_por_personal.get(colaborador.pk, 0)
    personal_form = personal_form or PersonalForm()
    context = {
        'personal': personal,
        'categorias': Categoria.objects.filter(activa=True).order_by('nombre'),
        'total_activos': personal.filter(is_active=True).count(),
        'total_inactivos': personal.filter(is_active=False).count(),
        'personal_form': personal_form,
        'form_action': form_action or reverse('crear_personal'),
        'form_is_edit': form_is_edit,
        'form_has_errors': bool(personal_form.errors),
        'password_reset_form': ColaboradorPasswordResetForm(None),
        'password_reset_target': None,
    }
    context['total_personal'] = context['total_activos'] + context['total_inactivos']
    return context


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


def _citas_futuras_personal(colaborador):
    return Reserva.objects.filter(
        profesional=colaborador,
        fecha_hora__gte=timezone.now(),
    ).exclude(estado__in=['cancelada', 'completada'])


def _desactivar_recursos_personal(colaborador, categorias_ids):
    Disponibilidad.objects.filter(
        profesional=colaborador,
        activo=True,
        fecha_especifica__gte=timezone.localdate(),
    ).update(activo=False, desactivado_por_personal=True)

    for categoria_id in categorias_ids:
        hay_otro_profesional = Usuario.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
            rol__nombre__iexact='Colaborador',
            especialidades__categoria_id=categoria_id,
        ).exclude(pk=colaborador.pk).exists()
        if hay_otro_profesional:
            continue

        servicios_activos = Servicio.objects.filter(
            categoria_id=categoria_id,
            activo=True,
        )
        for servicio_id in servicios_activos.values_list('pk', flat=True):
            ServicioDesactivadoPorPersonal.objects.get_or_create(
                servicio_id=servicio_id,
                defaults={'categoria_id': categoria_id},
            )
        servicios_activos.update(activo=False)


def _reactivar_recursos_personal(colaborador, categorias_ids):
    Disponibilidad.objects.filter(
        profesional=colaborador,
        desactivado_por_personal=True,
        fecha_especifica__lt=timezone.localdate(),
    ).update(desactivado_por_personal=False)
    Disponibilidad.objects.filter(
        profesional=colaborador,
        desactivado_por_personal=True,
        fecha_especifica__gte=timezone.localdate(),
    ).update(activo=True, desactivado_por_personal=False)

    servicios_pendientes = ServicioDesactivadoPorPersonal.objects.filter(
        categoria_id__in=categorias_ids,
    )
    servicio_ids = list(servicios_pendientes.values_list('servicio_id', flat=True))
    Servicio.objects.filter(pk__in=servicio_ids, activo=False).update(activo=True)
    servicios_pendientes.delete()


def _notificar_clientes_personal(colaborador, mensaje_personalizado):
    citas = _citas_futuras_personal(colaborador).filter(
        cliente__isnull=False,
    ).select_related('cliente').order_by('cliente_id', 'fecha_hora')
    citas_por_cliente = {}
    for cita in citas:
        citas_por_cliente.setdefault(cita.cliente, []).append(cita)

    enviados = 0
    sin_correo = 0
    fallidos = 0
    for cliente, citas_cliente in citas_por_cliente.items():
        if not cliente.email:
            sin_correo += 1
            continue
        detalles = '\n'.join(
            f'- {cita.servicio_nombre or "Servicio"}: '
            f'{timezone.localtime(cita.fecha_hora):%d-%m-%Y a las %H:%M}'
            for cita in citas_cliente
        )
        try:
            send_mail(
                'Información sobre tu próxima cita - Nicolett Studio',
                (
                    f'Hola {cliente.nombre},\n\n{mensaje_personalizado.strip()}\n\n'
                    f'Tus citas próximas:\n{detalles}\n\n'
                    'Si necesitas ayuda, contáctanos para coordinar una alternativa.'
                ),
                getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
                [cliente.email],
                fail_silently=False,
            )
            enviados += 1
        except (OSError, smtplib.SMTPException):
            logger.exception(
                'No se pudo notificar al cliente %s por la inactivación del colaborador %s.',
                cliente.pk,
                colaborador.pk,
            )
            fallidos += 1
    return enviados, sin_correo, fallidos


def _validar_confirmacion_personal(request, colaborador):
    cantidad_citas = _citas_futuras_personal(colaborador).count()
    if cantidad_citas and request.POST.get('confirmar_agenda') != '1':
        messages.warning(
            request,
            f'Hay {cantidad_citas} cita(s) futura(s) con este colaborador. '
            'Confirma nuevamente para continuar.',
        )
        return False
    if request.POST.get('notificar_clientes') == '1':
        mensaje = request.POST.get('mensaje_clientes', '').strip()
        if not mensaje:
            messages.error(request, 'Escribe el mensaje personalizado que recibirán los clientes.')
            return False
        if len(mensaje) > 1000:
            messages.error(request, 'El mensaje personalizado no puede superar los 1000 caracteres.')
            return False
        texto_normalizado = ''.join(
            caracter
            for caracter in unicodedata.normalize('NFKD', mensaje.casefold())
            if not unicodedata.combining(caracter)
        )
        frases_no_permitidas = (
            'ya no esta trabajando',
            'ya no trabaja',
            'no trabaja en el salon',
            'dejo de trabajar',
            'ha dejado de trabajar',
            'no trabaja mas',
            'no trabajara mas',
            'no volvera a trabajar',
            'ya no forma parte',
            'ya no pertenece al salon',
            'dejo de pertenecer',
            'se retiro del salon',
            'dejo el salon',
            'se fue del salon',
        )
        if any(frase in texto_normalizado for frase in frases_no_permitidas):
            messages.error(
                request,
                'El mensaje no puede indicar que el colaborador dejó de trabajar en el salón.',
            )
            return False
    return True


def _mostrar_resultado_notificaciones(request, resultado):
    enviados, sin_correo, fallidos = resultado
    if not enviados and not sin_correo and not fallidos:
        messages.info(
            request,
            'No había clientes con cuenta y citas futuras para notificar.',
        )
        return
    messages.info(
        request,
        f'Avisos a clientes: {enviados} enviados, {sin_correo} sin email de cuenta, '
        f'{fallidos} fallidos.',
    )


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
        colaborador.is_staff = False
        colaborador.is_superuser = False
        colaborador.acepta_terminos_at = timezone.now()
        colaborador.deleted_at = None
        colaborador.set_password(form.cleaned_data['password'])
        colaborador.save()
        _guardar_especializaciones(
            colaborador,
            form.cleaned_data['especializaciones'],
        )
        _reactivar_recursos_personal(
            colaborador,
            [categoria.pk for categoria in form.cleaned_data['especializaciones']],
        )
    messages.success(
        request,
        'El colaborador y sus credenciales de acceso se crearon correctamente.',
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
        colaborador = form.save(commit=False)
        password = form.cleaned_data.get('password')
        if password:
            colaborador.set_password(password)
        colaborador.save()
        _guardar_especializaciones(
            colaborador,
            form.cleaned_data['especializaciones'],
        )
        if colaborador.is_active:
            _reactivar_recursos_personal(
                colaborador,
                [categoria.pk for categoria in form.cleaned_data['especializaciones']],
            )
    messages.success(request, 'Los datos del colaborador se actualizaron correctamente.')
    return redirect('admin_personal')


@require_POST
def restablecer_contrasena_personal(request, pk):
    colaborador = get_object_or_404(
        Usuario,
        pk=pk,
        rol__nombre__iexact='Colaborador',
        deleted_at__isnull=True,
    )
    form = ColaboradorPasswordResetForm(colaborador, request.POST)
    if not form.is_valid():
        context = _contexto_personal()
        context.update({
            'password_reset_form': form,
            'password_reset_target': colaborador,
        })
        return render(request, 'panel_admin/personal_lista.html', context)

    colaborador.set_password(form.cleaned_data['password'])
    colaborador.save(update_fields=['password'])
    messages.success(request, f'La contraseña de {colaborador.nombre} se restableció correctamente.')
    return redirect('admin_personal')


@login_required(login_url='login')
def colaborador_mi_agenda(request):
    if not es_colaborador(request.user):
        return HttpResponseForbidden()

    from agenda.views import _construir_calendario

    hoy = timezone.localdate()
    mes_param = request.GET.get('mes', '').strip()
    try:
        mes_seleccionado = date.fromisoformat(f'{mes_param}-01') if mes_param else hoy
    except ValueError:
        mes_seleccionado = hoy
    citas = Reserva.objects.select_related('cliente', 'servicio').filter(
        profesional=request.user,
        fecha_hora__gte=timezone.now(),
    ).exclude(
        estado__in=['cancelada', 'completada'],
    ).order_by('fecha_hora')
    return render(request, 'panel_admin/colaborador_agenda.html', {
        'citas': citas,
        'hoy': hoy,
        'calendario_mes': _construir_calendario(
            hoy,
            mes_seleccionado,
            mes_seleccionado.replace(day=1),
            profesional_id=request.user.pk,
        ),
        'dia_labels': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
    })


@require_POST
def eliminar_personal(request, pk):
    colaborador = get_object_or_404(
        Usuario,
        pk=pk,
        rol__nombre__iexact='Colaborador',
        deleted_at__isnull=True,
    )
    if not _validar_confirmacion_personal(request, colaborador):
        return redirect('admin_personal')

    categorias_ids = list(
        ProfesionalCategoria.objects.filter(
            profesional=colaborador,
        ).values_list('categoria_id', flat=True)
    )
    tiene_historial = Reserva.objects.filter(profesional=colaborador).exists()
    with transaction.atomic():
        if colaborador.is_active:
            colaborador.is_active = False
            colaborador.save(update_fields=['is_active'])
            _desactivar_recursos_personal(colaborador, categorias_ids)
        if tiene_historial:
            colaborador.deleted_at = timezone.now()
            colaborador.save(update_fields=['deleted_at'])
        else:
            colaborador.delete()
    if request.POST.get('notificar_clientes') == '1':
        _mostrar_resultado_notificaciones(
            request,
            _notificar_clientes_personal(
                colaborador,
                request.POST['mensaje_clientes'],
            ),
        )
    messages.success(request, 'El colaborador se eliminó correctamente.')
    return redirect('admin_personal')


@require_POST
def desactivar_personal(request, pk):
    colaborador = get_object_or_404(Usuario, pk=pk, rol__nombre__iexact='Colaborador')
    if colaborador.is_active:
        if not _validar_confirmacion_personal(request, colaborador):
            return redirect('admin_personal')
        categorias_ids = list(
            ProfesionalCategoria.objects.filter(
                profesional=colaborador,
            ).values_list('categoria_id', flat=True)
        )
        with transaction.atomic():
            colaborador.is_active = False
            colaborador.save(update_fields=['is_active'])
            _desactivar_recursos_personal(colaborador, categorias_ids)
        if request.POST.get('notificar_clientes') == '1':
            _mostrar_resultado_notificaciones(
                request,
                _notificar_clientes_personal(
                    colaborador,
                    request.POST['mensaje_clientes'],
                ),
            )
        messages.success(request, 'El colaborador quedó desactivado.')
    else:
        categorias_ids = list(
            ProfesionalCategoria.objects.filter(
                profesional=colaborador,
            ).values_list('categoria_id', flat=True)
        )
        with transaction.atomic():
            colaborador.is_active = True
            colaborador.save(update_fields=['is_active'])
            _reactivar_recursos_personal(colaborador, categorias_ids)
        messages.success(
            request,
            'El colaborador quedó activado; se recuperaron sus bloques futuros '
            'que se habían desactivado automáticamente.',
        )
    return redirect('admin_personal')