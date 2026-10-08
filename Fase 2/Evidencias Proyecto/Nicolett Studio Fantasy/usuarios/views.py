from django.contrib.auth import authenticate, login as auth_login, logout
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

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
    return render(request, template, context or {})


@never_cache
def cliente_home_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_home.html',
        {'usuario': request.user},
    )


@never_cache
def cliente_servicios_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {'titulo': 'Servicios', 'descripcion': 'Aquí podrás conocer los servicios disponibles.'},
    )


@never_cache
def cliente_productos_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {'titulo': 'Productos', 'descripcion': 'Aquí podrás revisar los productos del estudio.'},
    )


@never_cache
def cliente_agendamiento_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {'titulo': 'Agendamiento', 'descripcion': 'Aquí podrás agendar una cita.'},
    )


@never_cache
def cliente_historial_view(request):
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {'titulo': 'Historial de citas', 'descripcion': 'Aquí podrás consultar tus citas anteriores.'},
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
