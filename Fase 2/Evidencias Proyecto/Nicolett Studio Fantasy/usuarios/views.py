from django.contrib.auth import authenticate, login as auth_login, logout
from django.db import IntegrityError
from django.db.models import QuerySet
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from agenda.models import Reserva
from panel_admin.models import Producto, Servicio

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
            return redirect('cliente_home')
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
    return _vista_cliente(
        request,
        'usuarios/cliente_home.html',
        {'usuario': request.user},
    )


@never_cache
def cliente_servicios_view(request):
    servicios = Servicio.objects.filter(activo=True).select_related('categoria').order_by('nombre')
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {
            'titulo': 'Servicios',
            'descripcion': 'Aquí podrás conocer los servicios disponibles.',
            'servicios': servicios,
            'filtros_categoria': _filtros_catalogo(servicios),
        },
    )


@never_cache
def cliente_productos_view(request):
    productos = Producto.objects.filter(activo=True).select_related('categoria').order_by('nombre')
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {
            'titulo': 'Productos',
            'descripcion': 'Aquí podrás revisar los productos del estudio.',
            'productos': productos,
            'filtros_categoria': _filtros_catalogo(productos),
        },
    )


def _filtros_catalogo(items: QuerySet) -> list[str]:
    filtros = {}
    for nombre, tipo in items.values_list('categoria__nombre', 'categoria__tipo').distinct():
        for valor in (nombre, tipo):
            valor = (valor or '').strip()
            if valor:
                filtros.setdefault(valor.casefold(), valor)
    return sorted(filtros.values(), key=str.casefold)


@never_cache
def cliente_agendamiento_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_agendamiento.html',
        {
            'servicios': Servicio.objects.filter(activo=True).select_related('categoria').order_by('nombre'),
            'hoy': timezone.localdate().isoformat(),
            'cliente_profesionales_url': reverse('cliente_profesionales_disponibles'),
            'cliente_horas_url': reverse('cliente_horas_disponibles'),
        },
    )


@never_cache
def cliente_historial_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_historial.html',
        {
            'reservas': Reserva.objects.filter(
                cliente=request.user,
            ).select_related(
                'servicio',
                'profesional',
            ).order_by('-fecha_hora'),
        },
    )


@never_cache
def cliente_gestionar_citas_view(request):
    ahora = timezone.now()
    return _vista_cliente(
        request,
        'usuarios/cliente_gestionar_citas.html',
        {
            'reservas': Reserva.objects.filter(
                cliente=request.user,
                fecha_hora__gt=ahora,
            ).exclude(
                estado__in=['cancelada', 'completada'],
            ).select_related(
                'servicio',
                'profesional',
                'cambio_disponibilidad',
            ).order_by('fecha_hora'),
            'servicios': Servicio.objects.filter(activo=True).order_by('nombre'),
            'hoy': timezone.localdate().isoformat(),
            'cliente_profesionales_url': reverse('cliente_profesionales_disponibles'),
            'cliente_horas_url': reverse('cliente_horas_disponibles'),
        },
    )


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
