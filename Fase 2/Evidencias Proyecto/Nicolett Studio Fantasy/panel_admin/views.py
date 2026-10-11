import logging
import smtplib
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AdminPasswordChangeForm,
    AdminProfileForm,
    CategoriaForm,
    ConfiguracionRecordatoriosForm,
    PersonalForm,
    ProductoForm,
    ServicioForm,
)
from .models import Servicio, Categoria, Producto
from usuarios.models import Rol, Usuario
from usuarios.permissions import es_administrador
from agenda.models import ProfesionalCategoria, Reserva
from notificaciones.recordatorios import (
    enviar_recordatorio as enviar_recordatorio_email,
    listar_recordatorios_pendientes,
    obtener_configuracion_recordatorios,
    guardar_configuracion_recordatorios as guardar_intervalos_recordatorios,
)
from pagos.models import Pago
from ventas.models import Venta

logger = logging.getLogger(__name__)


def dashboard_home(request):
    hoy = timezone.localdate()
    citas_hoy = Reserva.objects.select_related(
        'cliente', 'profesional', 'servicio',
    ).filter(fecha_hora__date=hoy).order_by('fecha_hora')
    ventas_mes = Venta.objects.filter(
        fecha_venta__year=hoy.year,
        fecha_venta__month=hoy.month,
    ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    return render(request, 'panel_admin/admin_home.html', {
        'citas_hoy': citas_hoy,
        'total_citas_hoy': citas_hoy.count(),
        'ventas_mes': ventas_mes,
        'servicios_activos': Servicio.objects.filter(activo=True).count(),
        'productos_activos': Producto.objects.filter(activo=True).count(),
    })

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
        'categorias_admin': Categoria.objects.all().order_by('nombre'),
        'total_activos': productos.filter(activo=True).count(),
        'total_inactivos': productos.filter(activo=False).count(),
    }
    context['total_productos'] = context['total_activos'] + context['total_inactivos']
    return render(request, 'panel_admin/productos_lista.html', context)


@login_required(login_url='login')
def configuracion_admin(request):
    if not es_administrador(request.user):
        return HttpResponseForbidden()

    perfil_form = AdminProfileForm(instance=request.user)
    password_form = AdminPasswordChangeForm(request.user)
    if request.method == 'POST':
        if request.POST.get('form_type') == 'password':
            password_form = AdminPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                request.user.set_password(password_form.cleaned_data['nueva'])
                request.user.save(update_fields=['password'])
                update_session_auth_hash(request, request.user)
                messages.success(request, 'La contraseña se actualizó correctamente.')
                return redirect('admin_configuracion')
        else:
            perfil_form = AdminProfileForm(request.POST, instance=request.user)
            if perfil_form.is_valid():
                perfil_form.save()
                messages.success(request, 'Los datos personales se actualizaron correctamente.')
                return redirect('admin_configuracion')

    return render(
        request,
        'panel_admin/configuracion_admin.html',
        {
            'perfil_form': perfil_form,
            'password_form': password_form,
        },
    )


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
        'ventas_mes': Venta.objects.filter(
            fecha_venta__year=hoy.year,
            fecha_venta__month=hoy.month,
        ).aggregate(total=Sum('total'))['total'] or Decimal('0.00'),
        'pagos_aprobados_mes': Pago.objects.filter(
            fecha_pago__year=hoy.year,
            fecha_pago__month=hoy.month,
            estado_pago__iexact='Aprobado',
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00'),
    })


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


def gestion_recordatorios(request):
    horas_cita, dias_seguimiento = obtener_configuracion_recordatorios()
    if request.method == 'POST':
        form = ConfiguracionRecordatoriosForm(request.POST)
        if form.is_valid():
            guardar_intervalos_recordatorios(
                form.cleaned_data['horas_cita'],
                form.cleaned_data['dias_seguimiento'],
            )
            messages.success(request, 'La programación de recordatorios quedó actualizada.')
            return redirect('admin_recordatorios')
    else:
        form = ConfiguracionRecordatoriosForm(initial={
            'horas_cita': ', '.join(map(str, horas_cita)),
            'dias_seguimiento': ', '.join(map(str, dias_seguimiento)),
        })

    busqueda = request.GET.get('q', '').strip()
    tareas = listar_recordatorios_pendientes()
    if busqueda:
        busqueda_normalizada = busqueda.casefold()
        tareas = [
            tarea for tarea in tareas
            if busqueda_normalizada in ' '.join((
                tarea['reserva'].nombre_cliente,
                tarea['reserva'].correo_cliente,
                tarea['reserva'].servicio_nombre,
                str(tarea['reserva'].servicio or ''),
            )).casefold()
        ]

    return render(request, 'panel_admin/recordatorios_lista.html', {
        'recordatorios_cita': [tarea for tarea in tareas if tarea['tipo'] == 'cita'],
        'recordatorios_seguimiento': [tarea for tarea in tareas if tarea['tipo'] == 'seguimiento'],
        'form_recordatorios': form,
        'busqueda': busqueda,
    })


@require_POST
def enviar_recordatorio(request, reserva_id):
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
        and item['tipo'] == tipo
        and item['desfase'] == desfase
    ), None)
    if tarea is None:
        messages.error(request, 'Este recordatorio ya se envió o no está dentro de su período de envío.')
        return redirect('admin_recordatorios')
    if not tarea['vencido']:
        messages.info(request, 'Este recordatorio todavía no vence; se enviará cuando llegue la fecha programada.')
        return redirect('admin_recordatorios')

    try:
        enviado = enviar_recordatorio_email(tarea)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect('admin_recordatorios')
    except (OSError, smtplib.SMTPException, RuntimeError):
        logger.exception(
            'No se pudo enviar el recordatorio %s de la reserva %s.',
            tipo,
            reserva_id,
        )
        messages.error(request, 'No se pudo enviar el correo. Revisa la configuración de correo e inténtalo otra vez.')
        return redirect('admin_recordatorios')

    if enviado:
        messages.success(
            request,
            f'El recordatorio se envió a {tarea["reserva"].correo_cliente}.',
        )
    else:
        messages.info(request, 'Este recordatorio ya se había enviado.')
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