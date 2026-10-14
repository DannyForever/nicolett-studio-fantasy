from datetime import timedelta

from django.contrib.auth import authenticate, login as auth_login, logout, update_session_auth_hash
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import QuerySet
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from agenda.models import HistorialReserva, Reserva
from agenda.views import servicios_con_horarios_disponibles
from carrito.models import PagoSimulado, Pedido, ReservaProductoCarrito
from panel_admin.models import Producto, Servicio

from .forms import ClienteCambiarContrasenaForm, ClienteConfiguracionForm
from .models import Rol, Usuario
from .permissions import es_administrador, es_cliente


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        usuario = authenticate(request, email=email, password=password)

        if usuario is None:
            return render(
                request,
                'usuarios/login.html',
                {'error': 'Correo electrónico o contraseña incorrectos.'},
            )

        auth_login(request, usuario)
        if es_administrador(usuario):
            return redirect('admin_dashboard')
        if es_cliente(usuario):
            return redirect('cliente_servicios')
        return render(
            request,
            'usuarios/acceso_denegado.html',
            status=403,
        )

    return render(
        request,
        'usuarios/login.html',
        {'mostrar_registro': request.GET.get('tab') == 'register'},
    )


def register_view(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        segundo_nombre = request.POST.get('segundo_nombre', '').strip()
        apellido_paterno = request.POST.get('apellido_paterno', '').strip()
        apellido_materno = request.POST.get('apellido_materno', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        if not all((nombre, apellido_paterno, apellido_materno, telefono, email, password)):
            return render(
                request,
                'usuarios/login.html',
                {'error': 'Completa todos los campos obligatorios.'},
            )
        if password != password_confirm:
            return render(
                request,
                'usuarios/login.html',
                {'error': 'Las contraseñas no coinciden.'},
            )

        rol_cliente, _ = Rol.objects.get_or_create(nombre='Cliente')
        try:
            Usuario.objects.create_user(
                email=email,
                password=password,
                nombre=nombre,
                segundo_nombre=segundo_nombre,
                apellido_paterno=apellido_paterno,
                apellido_materno=apellido_materno,
                telefono=telefono,
                rol=rol_cliente,
                is_active=True,
                is_staff=False,
                is_superuser=False,
                acepta_terminos_at=timezone.now(),
            )
        except IntegrityError:
            return render(
                request,
                'usuarios/login.html',
                {'error': 'El correo electrónico ya se encuentra registrado.'},
            )

        return render(
            request,
            'usuarios/login.html',
            {'exito': '¡Cuenta creada con éxito! Ya puedes iniciar sesión con tus credenciales.'},
        )

    return render(request, 'usuarios/login.html')


def _vista_cliente(request, template, context=None):
    if not request.user.is_authenticated:
        return redirect('login')
    if not request.user.is_active or not es_cliente(request.user):
        return render(
            request,
            'usuarios/acceso_denegado.html',
            status=403,
        )
    from carrito.views import _liberar_reservas_vencidas, resumen_carrito

    _liberar_reservas_vencidas(request)
    contexto = context.copy() if context else {}
    contexto['resumen_carrito'], contexto['total_resumen_carrito'] = resumen_carrito(request)
    contexto['cantidad_articulos_carrito'] = sum(
        item['cantidad'] for item in contexto['resumen_carrito']
    )
    return render(request, template, contexto)


@never_cache
def cliente_home_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if not request.user.is_active or not es_cliente(request.user):
        return render(
            request,
            'usuarios/acceso_denegado.html',
            status=403,
        )
    return redirect('cliente_servicios')


@never_cache
def cliente_sobre_nosotros_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_sobre_nosotros.html',
    )


@never_cache
def cliente_servicios_view(request):
    orden = request.GET.get('orden', 'nombre_asc')
    ordenes = {
        'nombre_asc': ('nombre',),
        'nombre_desc': ('-nombre',),
        'precio_asc': ('precio', 'nombre'),
        'precio_desc': ('-precio', 'nombre'),
    }
    if orden not in ordenes:
        orden = 'nombre_asc'
    servicios = Servicio.objects.filter(
        activo=True,
        pk__in=servicios_con_horarios_disponibles(),
    ).select_related('categoria').order_by(*ordenes[orden])
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {
            'titulo': 'Servicios',
            'descripcion': 'Aquí podrás conocer los servicios disponibles.',
            'servicios': servicios,
            'filtros_categoria': _filtros_catalogo(servicios),
            'orden_catalogo': orden,
        },
    )


@never_cache
def cliente_productos_view(request):
    orden = request.GET.get('orden', 'nombre_asc')
    ordenes = {
        'nombre_asc': ('nombre',),
        'nombre_desc': ('-nombre',),
        'precio_asc': ('precio', 'nombre'),
        'precio_desc': ('-precio', 'nombre'),
    }
    if orden not in ordenes:
        orden = 'nombre_asc'
    productos = Producto.objects.filter(
        activo=True,
        stock__gt=0,
    ).select_related('categoria').order_by(*ordenes[orden])
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {
            'titulo': 'Productos',
            'descripcion': 'Aquí podrás revisar los productos del estudio.',
            'productos': productos,
            'filtros_categoria': _filtros_catalogo(productos),
            'orden_catalogo': orden,
        },
    )


def _filtros_catalogo(items: QuerySet) -> list[str]:
    filtros = {
        nombre.strip().casefold(): nombre.strip()
        for nombre in items.values_list('categoria__nombre', flat=True).distinct()
        if nombre and nombre.strip()
    }
    return sorted(filtros.values(), key=str.casefold)


@never_cache
def cliente_agendamiento_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_agendamiento.html',
        {
            'servicios': Servicio.objects.filter(
                activo=True,
                pk__in=servicios_con_horarios_disponibles(),
            ).select_related('categoria').order_by('nombre'),
            'hoy': timezone.localdate().isoformat(),
            'cliente_profesionales_url': reverse('cliente_profesionales_disponibles'),
            'cliente_horas_url': reverse('cliente_horas_disponibles'),
            'cliente_calendario_url': reverse('cliente_calendario_disponibilidad'),
        },
    )


@never_cache
def cliente_historial_view(request):
    return redirect(f"{reverse('cliente_gestionar_citas')}?tab=historial")


@never_cache
def cliente_gestionar_citas_view(request):
    reservas = list(
        Reserva.objects.filter(
            cliente=request.user,
        ).select_related(
            'servicio',
            'profesional',
        ).prefetch_related(
            'historial',
        ).order_by('-fecha_hora')
    )
    ahora = timezone.now()
    historial_completo = []
    for reserva in reservas:
        fin = reserva.fecha_hora + timedelta(minutes=reserva.duracion_minutos)
        reserva.puede_gestionar = (
            reserva.fecha_hora > ahora + timedelta(hours=48)
            and reserva.estado in ['pendiente', 'confirmada', 'suspendida']
        )
        if reserva.estado == 'cancelada':
            reserva.estado_cliente = 'Cancelado'
        elif reserva.estado == 'completada':
            reserva.estado_cliente = 'Finalizado'
        elif reserva.estado == 'suspendida':
            reserva.estado_cliente = 'Modificado'
        elif reserva.fecha_hora <= ahora < fin:
            reserva.estado_cliente = 'En curso'
        else:
            reserva.estado_cliente = 'Solicitado'
        profesional_nombre = ' '.join(part for part in (
            reserva.profesional.nombre if reserva.profesional else '',
            reserva.profesional.segundo_nombre if reserva.profesional else '',
            reserva.profesional.apellido_paterno if reserva.profesional else '',
            reserva.profesional.apellido_materno if reserva.profesional else '',
        ) if part) if reserva.profesional else 'Sin profesional asignado'
        historial_completo.append({
            'fecha_hora': reserva.fecha_hora,
            'servicio_nombre': reserva.servicio_nombre or (
                reserva.servicio.nombre if reserva.servicio else 'Servicio no disponible'
            ),
            'profesional_nombre': profesional_nombre,
            'duracion_minutos': reserva.duracion_minutos,
            'estado_cliente': reserva.estado_cliente,
            'estado_clase': {
                'Solicitado': 'border-amber-200 bg-amber-50 text-amber-800',
                'Cancelado': 'border-red-200 bg-red-50 text-red-800',
                'Modificado': 'border-violet-200 bg-violet-50 text-violet-800',
                'En curso': 'border-blue-200 bg-blue-50 text-blue-800',
                'Finalizado': 'border-green-200 bg-green-50 text-green-800',
            }.get(reserva.estado_cliente, 'border-[#e8e0da] bg-[#f7f3f0] text-[#66564e]'),
            'motivo': reserva.motivo_cancelacion or reserva.motivo_suspension,
        })
        for evento in reserva.historial.all():
            if evento.evento != 'modificada':
                continue
            historial_completo.append({
                'fecha_hora': evento.fecha_hora,
                'servicio_nombre': evento.servicio_nombre or 'Servicio no disponible',
                'profesional_nombre': evento.profesional_nombre or 'Sin profesional asignado',
                'duracion_minutos': evento.duracion_minutos or reserva.duracion_minutos,
                'estado_cliente': 'Modificado' if evento.evento == 'modificada' else 'Cancelado',
                'estado_clase': 'border-violet-200 bg-violet-50 text-violet-800',
                'motivo': evento.motivo,
            })
    historial_completo.sort(key=lambda cita: cita['fecha_hora'], reverse=True)
    return _vista_cliente(
        request,
        'usuarios/cliente_gestionar_citas.html',
        {
            'reservas_gestionables': [
                reserva for reserva in reservas
                if reserva.fecha_hora > ahora
                and reserva.estado in ['pendiente', 'confirmada', 'suspendida']
            ],
            'reservas_historial': reservas,
            'historial_completo': historial_completo,
            'active_tab': 'historial' if request.GET.get('tab') == 'historial' else 'gestionar',
            'servicios': Servicio.objects.filter(
                activo=True,
                pk__in=servicios_con_horarios_disponibles(),
            ).order_by('nombre'),
            'hoy': timezone.localdate().isoformat(),
            'cliente_profesionales_url': reverse('cliente_profesionales_disponibles'),
            'cliente_horas_url': reverse('cliente_horas_disponibles'),
        },
    )


@never_cache
def cliente_historial_pagos_view(request):
    pedidos = Pedido.objects.filter(
        cliente=request.user,
        pagos_simulados__isnull=False,
    ).distinct().prefetch_related(
        'pagos_simulados',
        'detalles',
    ).order_by('-creado_en')
    return _vista_cliente(
        request,
        'usuarios/cliente_historial_pagos.html',
        {'pedidos': pedidos},
    )


@never_cache
def cliente_configuracion_view(request):
    datos_cliente = {
        'nombre': request.user.nombre,
        'segundo_nombre': request.user.segundo_nombre,
        'apellido_paterno': request.user.apellido_paterno,
        'apellido_materno': request.user.apellido_materno,
        'telefono': request.user.telefono,
        'email': request.user.email,
    }
    perfil_form = ClienteConfiguracionForm(
        request.POST if request.method == 'POST' and request.POST.get('accion') == 'perfil' else None,
        usuario=request.user,
        initial=datos_cliente,
    )
    password_form = ClienteCambiarContrasenaForm(
        request.POST if request.method == 'POST' and request.POST.get('accion') == 'contrasena' else None,
        usuario=request.user,
    )
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'perfil' and perfil_form.is_valid():
            perfil_form.save()
            messages.success(request, 'Tus datos personales se actualizaron correctamente.')
            return redirect('cliente_configuracion')
        if accion == 'contrasena' and password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'La contraseña se actualizó correctamente.')
            return redirect('cliente_configuracion')
        if accion not in ('perfil', 'contrasena'):
            messages.error(request, 'Selecciona qué información deseas actualizar.')
    return _vista_cliente(
        request,
        'usuarios/cliente_configuracion.html',
        {
            'perfil_form': perfil_form,
            'password_form': password_form,
        },
    )


@never_cache
@require_POST
def cliente_eliminar_cuenta_view(request):
    if request.POST.get('confirmar') != 'eliminar':
        messages.error(request, 'Confirma la eliminación de la cuenta para continuar.')
        return redirect('cliente_configuracion')

    usuario_id = request.user.pk
    session_key = request.session.session_key
    with transaction.atomic():
        usuario = Usuario.objects.select_for_update().get(pk=usuario_id)
        reservas = list(
            Reserva.objects.select_for_update().filter(
                cliente=usuario,
                fecha_hora__gt=timezone.now(),
                estado__in=['pendiente', 'confirmada', 'suspendida'],
            ).select_related('profesional', 'servicio')
        )
        for reserva in reservas:
            profesional = reserva.profesional
            profesional_nombre = ' '.join(part for part in (
                profesional.nombre,
                profesional.segundo_nombre,
                profesional.apellido_paterno,
                profesional.apellido_materno,
            ) if part) if profesional else 'Sin asignar'
            HistorialReserva.objects.create(
                reserva=reserva,
                evento='cancelada',
                fecha_hora=reserva.fecha_hora,
                servicio_nombre=reserva.servicio_nombre or 'Servicio no disponible',
                profesional_nombre=profesional_nombre,
                estado=reserva.estado,
                motivo='Cita cancelada por eliminación de cuenta del cliente.',
            )
            reserva.estado = 'cancelada'
            reserva.motivo_cancelacion = 'Cita cancelada por eliminación de cuenta del cliente.'
            reserva.cliente_nombre = 'Cliente anonimizado'
            reserva.cliente_email = ''
            reserva.cliente_telefono = ''
            reserva.save(update_fields=[
                'estado', 'motivo_cancelacion', 'cliente_nombre',
                'cliente_email', 'cliente_telefono', 'updated_at',
            ])

        Reserva.objects.filter(cliente=usuario).update(
            cliente_nombre='Cliente anonimizado',
            cliente_email='',
            cliente_telefono='',
        )
        if session_key:
            for reserva_producto in ReservaProductoCarrito.objects.select_for_update().filter(
                session_key=session_key,
            ):
                producto = Producto.objects.select_for_update().filter(
                    pk=reserva_producto.producto_id,
                ).first()
                if producto:
                    producto.stock += reserva_producto.cantidad
                    producto.save(update_fields=['stock'])
                reserva_producto.delete()

        usuario.nombre = 'Cuenta anonimizada'
        usuario.segundo_nombre = ''
        usuario.apellido_paterno = 'Cuenta'
        usuario.apellido_materno = 'eliminada'
        usuario.telefono = ''
        usuario.email = f'eliminado-{usuario.pk}@cuentas-eliminadas.invalid'
        usuario.is_active = False
        usuario.deleted_at = timezone.now()
        usuario.set_unusable_password()
        usuario.save(update_fields=[
            'nombre', 'segundo_nombre', 'apellido_paterno', 'apellido_materno',
            'telefono', 'email', 'is_active', 'deleted_at', 'password',
        ])

    request.session.pop('carrito_compra', None)
    request.session.modified = True
    logout(request)
    messages.success(
        request,
        'La cuenta fue eliminada y anonimizada. Su correo ya puede usarse para crear otra cuenta; '
        'la cuenta eliminada y sus datos personales no se pueden recuperar.',
    )
    return redirect('login')


@never_cache
def cliente_cancelar_cita_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {'titulo': 'Cancelar cita', 'descripcion': 'Aquí podrás revisar y cancelar tus citas.'},
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')
