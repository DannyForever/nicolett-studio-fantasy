from datetime import timedelta
import binascii
import logging
import re
import smtplib
import unicodedata
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import authenticate, login as auth_login, logout, update_session_auth_hash
from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db.models import QuerySet
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from agenda.models import HistorialReserva, Reserva
from agenda.views import servicios_con_horarios_disponibles
from carrito.models import PagoSimulado, Pedido, ReservaProductoCarrito
from panel_admin.models import Producto, Servicio

from .forms import ClienteCambiarContrasenaForm, ClienteConfiguracionForm
from .models import Rol, Usuario
from .permissions import es_administrador, es_cliente, es_colaborador

logger = logging.getLogger(__name__)

MENSAJE_BIENVENIDA_WHATSAPP = (
    '✨ ¡Hola! Bienvenida a Nicolett Studio Fantasy 💖\n'
    'Gracias por escribirnos 💌\n'
    'Somos un espacio dedicado a realzar tu belleza con atención 100% personalizada ✨\n'
    '💅 Servicios disponibles:\n'
    '• Uñas\n'
    '• Peluquería 💇‍♀️\n'
    '• Pestañas 👁️\n'
    '• Depilación\n'
    '📍 Atendemos en Buin con previo abono\n'
    '💳 Aceptamos todos los medios de pago\n'
    'Para agendar tu hora, cuéntanos:\n'
    '👉 Qué servicio te interesa\n'
    '👉 Qué día y horario prefieres\n'
    'Te responderemos lo antes posible para coordinar contigo 💕'
)


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        usuario = authenticate(request, email=email, password=password)

        if usuario is None:
            usuario_pendiente = Usuario.objects.filter(
                email__iexact=email,
                is_active=False,
                deleted_at__isnull=True,
            ).select_related('rol').first()
            if (
                usuario_pendiente is not None
                and usuario_pendiente.check_password(password)
                and es_cliente(usuario_pendiente)
            ):
                correo_smtp_configurado = bool(
                    settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD
                )
                verification_url_local = ''
                if settings.DEBUG and not correo_smtp_configurado:
                    uid = urlsafe_base64_encode(force_bytes(usuario_pendiente.pk))
                    token = default_token_generator.make_token(usuario_pendiente)
                    verification_url_local = request.build_absolute_uri(
                        reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
                    )
                return render(
                    request,
                    'usuarios/login.html',
                    {
                        'email': usuario_pendiente.email,
                        'exito': (
                            (
                                'Tu cuenta aún no está activada. En esta prueba local no se '
                                'envía un correo real; usa el enlace de activación que aparece '
                                'a continuación.'
                            )
                            if verification_url_local
                            else (
                                'Por favor, verifica tu cuenta. Revisa el correo de '
                                'confirmación que te enviamos al registrarte.'
                            )
                        ),
                        'verification_pending': True,
                        'verification_url_local': verification_url_local,
                    },
                )
            return render(
                request,
                'usuarios/login.html',
                {'error': 'Correo electrónico o contraseña incorrectos.'},
            )

        auth_login(request, usuario)
        if es_administrador(usuario):
            return redirect('admin_dashboard')
        if es_cliente(usuario):
            enviar_aviso_inicio_sesion(request, usuario)
            return redirect('cliente_home')
        if es_colaborador(usuario):
            return redirect('colaborador_mi_agenda')
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


def enviar_aviso_inicio_sesion(request, usuario):
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        logger.error(
            'No se pudo enviar el aviso de inicio de sesión a %s: faltan credenciales SMTP.',
            usuario.email,
        )
        return

    email_context = {
        'nombre': usuario.nombre,
        'fecha_hora': timezone.localtime().strftime('%d/%m/%Y a las %H:%M'),
    }
    try:
        sent_count = send_mail(
            subject='Nuevo inicio de sesión - Nicolett Studio Fantasy',
            message=render_to_string(
                'usuarios/emails/inicio_sesion.txt',
                email_context,
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.email],
            fail_silently=False,
            html_message=render_to_string(
                'usuarios/emails/inicio_sesion.html',
                email_context,
            ),
        )
    except (OSError, smtplib.SMTPException):
        logger.exception('No se pudo enviar el aviso de inicio de sesión a %s.', usuario.email)
        return

    if sent_count != 1:
        logger.error(
            'El backend de correo no confirmó el aviso de inicio de sesión a %s.',
            usuario.email,
        )


def register_view(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        segundo_nombre = request.POST.get('segundo_nombre', '').strip()
        apellido_paterno = request.POST.get('apellido_paterno', '').strip()
        apellido_materno = request.POST.get('apellido_materno', '').strip()
        telefono = re.sub(r'\s+', '', request.POST.get('telefono', ''))
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        if not all((nombre, apellido_paterno, apellido_materno, telefono, email, password)):
            return render(
                request,
                'usuarios/login.html',
                {'error': 'Completa todos los campos obligatorios.', 'mostrar_registro': True},
            )
        if password != password_confirm:
            return render(
                request,
                'usuarios/login.html',
                {'error': 'Las contraseñas no coinciden.', 'mostrar_registro': True},
            )
        if not re.fullmatch(r'(?:\+569\d{8}|9\d{8})', telefono):
            return render(
                request,
                'usuarios/login.html',
                {
                    'error': 'Ingresa un teléfono chileno válido: +569XXXXXXXX o 9XXXXXXXX.',
                    'mostrar_registro': True,
                },
            )
        if telefono.startswith('9'):
            telefono = f'+56{telefono}'

        correo_smtp_configurado = bool(
            settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD
        )
        if not correo_smtp_configurado and not settings.DEBUG:
            return render(
                request,
                'usuarios/login.html',
                {
                    'error': (
                        'El envío de correo todavía no está configurado. '
                        'EMAIL_HOST_USER y EMAIL_HOST_PASSWORD son las credenciales del '
                        'correo del salón que envía los mensajes; el enlace de activación '
                        'se enviará al correo que ingresaste en el formulario. Configura '
                        'ambas variables en el archivo .env del proyecto o en el servidor.'
                    ),
                    'mostrar_registro': True,
                },
            )

        rol_cliente, _ = Rol.objects.get_or_create(nombre='Cliente')
        try:
            usuario = Usuario.objects.create_user(
                email=email,
                password=password,
                nombre=nombre,
                segundo_nombre=segundo_nombre,
                apellido_paterno=apellido_paterno,
                apellido_materno=apellido_materno,
                telefono=telefono,
                rol=rol_cliente,
                is_active=False,
                is_staff=False,
                is_superuser=False,
                acepta_terminos_at=timezone.now(),
            )
        except IntegrityError:
            return render(
                request,
                'usuarios/login.html',
                {'error': 'El correo electrónico ya se encuentra registrado.', 'mostrar_registro': True},
            )

        uid = urlsafe_base64_encode(force_bytes(usuario.pk))
        token = default_token_generator.make_token(usuario)
        verification_url = request.build_absolute_uri(
            reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
        )
        email_context = {
            'nombre': usuario.nombre,
            'verification_url': verification_url,
        }
        try:
            sent_count = send_mail(
                subject='Confirma tu correo - Nicolett Studio Fantasy',
                message=render_to_string(
                    'usuarios/emails/verificar_cuenta.txt',
                    email_context,
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[usuario.email],
                fail_silently=False,
                html_message=render_to_string(
                    'usuarios/emails/verificar_cuenta.html',
                    email_context,
                ),
            )
        except (OSError, smtplib.SMTPException):
            logger.exception('No se pudo enviar el correo de confirmación de cuenta.')
            usuario.delete()
            return render(
                request,
                'usuarios/login.html',
                {
                    'error': (
                        'No fue posible enviar el correo de confirmación. '
                        'Verifica tu dirección e inténtalo nuevamente más tarde.'
                    ),
                    'mostrar_registro': True,
                },
            )

        if sent_count != 1:
            logger.error('El backend de correo no confirmó el envío de verificación a %s.', email)
            usuario.delete()
            return render(
                request,
                'usuarios/login.html',
                {
                    'error': (
                        'No fue posible enviar el correo de confirmación. '
                        'Inténtalo nuevamente más tarde.'
                    ),
                    'mostrar_registro': True,
                },
            )

        return render(
            request,
            'usuarios/login.html',
            {
                'exito': (
                    (
                        'La cuenta se creó. Como el correo real no está configurado, '
                        'actívala con el enlace de prueba que aparece a continuación.'
                    )
                    if not correo_smtp_configurado
                    else (
                        'Por favor, verifica tu cuenta. Te hemos enviado un correo '
                        'electrónico para confirmar tu cuenta.'
                    )
                ),
                'email': email,
                'verification_pending': True,
                'verification_url_local': (
                    verification_url if settings.DEBUG and not correo_smtp_configurado else ''
                ),
                'whatsapp_url': (
                    'https://wa.me/56982108409?text='
                    f'{quote(MENSAJE_BIENVENIDA_WHATSAPP, safe="")}'
                ),
            },
        )

    return render(request, 'usuarios/login.html')


def verificar_correo_view(request, uidb64, token):
    try:
        usuario_id = force_str(urlsafe_base64_decode(uidb64))
        usuario = Usuario.objects.get(pk=usuario_id, deleted_at__isnull=True)
    except (
        binascii.Error,
        TypeError,
        ValueError,
        OverflowError,
        UnicodeDecodeError,
        Usuario.DoesNotExist,
    ):
        usuario = None

    token_valido = (
        usuario is not None
        and es_cliente(usuario)
        and default_token_generator.check_token(usuario, token)
    )
    if not token_valido:
        return render(
            request,
            'usuarios/login.html',
            {'error': 'El enlace de confirmación no es válido o ya venció.'},
            status=400,
        )

    cuenta_activada = not usuario.is_active
    if cuenta_activada:
        usuario.is_active = True
        usuario.save(update_fields=['is_active'])

    activation_email_error = ''
    if cuenta_activada:
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            activation_email_error = (
                'Tu cuenta quedó activa, pero no se pudo enviar el correo de confirmación. '
                'Contacta a la administración si necesitas ayuda.'
            )
            logger.error(
                'No se pudo enviar el correo de cuenta activada: faltan credenciales SMTP.'
            )
        else:
            login_url = request.build_absolute_uri(reverse('login'))
            email_context = {
                'email': usuario.email,
                'login_url': login_url,
            }
            try:
                sent_count = send_mail(
                    subject='Tu cuenta está activa - Nicolett Studio Fantasy',
                    message=render_to_string(
                        'usuarios/emails/cuenta_activada.txt',
                        email_context,
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[usuario.email],
                    fail_silently=False,
                    html_message=render_to_string(
                        'usuarios/emails/cuenta_activada.html',
                        email_context,
                    ),
                )
            except (OSError, smtplib.SMTPException):
                logger.exception('No se pudo enviar el correo de cuenta activada.')
                activation_email_error = (
                    'Tu cuenta quedó activa, pero no fue posible enviar el correo de '
                    'confirmación. Puedes iniciar sesión ahora.'
                )
            else:
                if sent_count != 1:
                    logger.error(
                        'El backend de correo no confirmó el envío de activación a %s.',
                        usuario.email,
                    )
                    activation_email_error = (
                        'Tu cuenta quedó activa, pero no fue posible enviar el correo de '
                        'confirmación. Puedes iniciar sesión ahora.'
                    )

    return render(
        request,
        'usuarios/login.html',
        {
            'email': usuario.email,
            'exito': 'Tu correo fue confirmado. Tu cuenta está activa y ya puedes iniciar sesión.',
            'activation_email_error': activation_email_error,
        },
    )


def solicitar_recuperacion_contrasena(request):
    mensaje = ''
    error = ''
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        usuario = Usuario.objects.filter(
            email__iexact=email,
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        if usuario is None:
            error = 'No existe una cuenta registrada con ese correo. No se envió ningún correo de recuperación.'
        elif not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            error = 'El servicio de correo no está configurado. Contacta a la administración.'
        else:
            uid = urlsafe_base64_encode(force_bytes(usuario.pk))
            token = default_token_generator.make_token(usuario)
            enlace = request.build_absolute_uri(
                reverse('password_reset_confirm_custom', kwargs={'uidb64': uid, 'token': token})
            )
            try:
                send_mail(
                    subject='Recupera tu contraseña - Nicolett Studio Fantasy',
                    message=(
                        f'Hola {usuario.nombre},\n\n'
                        f'Para crear una contraseña nueva, abre este enlace:\n{enlace}\n\n'
                        'Si no solicitaste este cambio, puedes ignorar este correo.'
                    ),
                    from_email=None,
                    recipient_list=[usuario.email],
                    fail_silently=False,
                )
            except (OSError, smtplib.SMTPException):
                logger.exception('No se pudo enviar el correo de recuperación.')
                error = 'No fue posible enviar el correo. Inténtalo nuevamente más tarde.'
            else:
                mensaje = 'Enviamos un enlace para recuperar tu contraseña al correo registrado.'
    return render(
        request,
        'usuarios/recuperar_contrasena.html',
        {'mensaje': mensaje, 'error': error},
    )


def restablecer_contrasena(request, uidb64, token):
    try:
        usuario_id = force_str(urlsafe_base64_decode(uidb64))
        usuario = Usuario.objects.get(pk=usuario_id, is_active=True)
    except (binascii.Error, TypeError, ValueError, OverflowError, Usuario.DoesNotExist):
        usuario = None

    token_valido = usuario is not None and default_token_generator.check_token(usuario, token)
    if not token_valido:
        return render(
            request,
            'usuarios/restablecer_contrasena.html',
            {'error': 'El enlace de recuperación no es válido o ya venció.'},
            status=400,
        )

    error = ''
    if request.method == 'POST':
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        if password != password_confirm:
            error = 'Las contraseñas no coinciden.'
        else:
            try:
                validate_password(password, usuario)
            except ValidationError as exc:
                error = ' '.join(exc.messages)
            else:
                usuario.set_password(password)
                usuario.save(update_fields=['password'])
                return render(request, 'usuarios/restablecer_contrasena.html', {'exito': True})
    return render(
        request,
        'usuarios/restablecer_contrasena.html',
        {'error': error, 'token_valido': True},
    )


def _nombre_completo_whatsapp(usuario):
    return ' '.join(
        parte.strip()
        for parte in (
            usuario.nombre,
            usuario.segundo_nombre,
            usuario.apellido_paterno,
            usuario.apellido_materno,
        )
        if parte and parte.strip()
    ).upper()


def _mensaje_consulta_cliente(usuario, tema):
    nombre = _nombre_completo_whatsapp(usuario)
    return (
        f'Hola, soy {nombre}. Quisiera consultar por {tema.upper()} en '
        'Nicolett Studio Fantasy. ¿Me pueden orientar sobre precios, disponibilidad '
        'o detalles?'
    )


def terminos_privacidad_view(request):
    nombre = (
        _nombre_completo_whatsapp(request.user)
        if request.user.is_authenticated
        else ''
    )
    saludo = f'Hola, soy {nombre}. ' if nombre else 'Hola. '
    mensaje = (
        f'{saludo}tengo una consulta sobre Nicolett Studio Fantasy relacionada con '
        'sus servicios, productos o el uso de mi cuenta. ¿Me podrían orientar?'
    )
    return render(
        request,
        'usuarios/terminos_privacidad.html',
        {
            'whatsapp_legal_url': (
                'https://wa.me/56940322551?text='
                f'{quote(mensaje, safe="")}'
            ),
        },
    )


def _url_whatsapp(numero, mensaje):
    return f'https://wa.me/{numero}?text={quote(mensaje, safe="")}'


def _admin_en_vista_cliente(request):
    return (
        request.user.is_authenticated
        and request.user.is_active
        and es_administrador(request.user)
        and request.session.get('admin_vista_cliente') is True
    )


def _colaborador_en_vista_cliente(request):
    return (
        request.user.is_authenticated
        and request.user.is_active
        and es_colaborador(request.user)
        and request.session.get('colaborador_vista_cliente') is True
    )


def _usuario_en_vista_cliente(request):
    return _admin_en_vista_cliente(request) or _colaborador_en_vista_cliente(request)


def _vista_cliente(request, template, context=None):
    if not request.user.is_authenticated:
        return redirect('login')
    contexto = context.copy() if context else {}
    vista_previa = _usuario_en_vista_cliente(request)
    vista_admin_existente = contexto.get('vista_admin', False)
    paginas_previsualizables = {
        'cliente_home',
        'cliente_sobre_nosotros',
        'cliente_servicios',
        'cliente_productos',
    }
    if vista_previa and getattr(request.resolver_match, 'url_name', '') not in paginas_previsualizables:
        return render(request, 'usuarios/acceso_denegado.html', status=403)
    if not request.user.is_active or not (
        es_cliente(request.user) or vista_previa or vista_admin_existente
    ):
        return render(
            request,
            'usuarios/acceso_denegado.html',
            status=403,
        )
    if vista_previa:
        contexto['vista_previa_admin'] = True
        contexto['vista_previa_colaborador'] = _colaborador_en_vista_cliente(request)
        contexto['resumen_carrito'] = []
        contexto['total_resumen_carrito'] = 0
        contexto['cantidad_articulos_carrito'] = 0
    elif es_cliente(request.user):
        from carrito.views import _liberar_reservas_vencidas, resumen_carrito

        _liberar_reservas_vencidas(request)
        contexto['resumen_carrito'], contexto['total_resumen_carrito'] = resumen_carrito(request)
        contexto['cantidad_articulos_carrito'] = sum(
            item['cantidad'] for item in contexto['resumen_carrito']
        )
    nombre_cliente = _nombre_completo_whatsapp(request.user)
    mensaje_cliente = (
        f'Hola, soy {nombre_cliente}. Estoy revisando los servicios y productos de '
        'Nicolett Studio Fantasy y quisiera consultar sobre precios, disponibilidad '
        'o una atención. ¿Me pueden orientar?'
    )
    contexto['whatsapp_url'] = _url_whatsapp('56982108409', mensaje_cliente)
    contexto['whatsapp_contacto_url'] = _url_whatsapp('56940322551', mensaje_cliente)
    categorias_whatsapp = {
        'corte': 'Corte y Estilo',
        'tratamientos': 'Tratamientos capilares',
        'manos': 'Manicure y Pedicure',
        'depilaciones': 'Depilación',
        'peinados': 'Peinados',
        'coloracion': 'Colorimetría',
        'podologia': 'Podología',
        'lash_brow': 'Lash & Brow',
    }
    contexto['whatsapp_categoria_urls'] = {
        categoria: _url_whatsapp('56982108409', _mensaje_consulta_cliente(
            request.user,
            nombre_servicio,
        ))
        for categoria, nombre_servicio in categorias_whatsapp.items()
    }
    if 'servicios' in contexto:
        for servicio in contexto['servicios']:
            servicio.whatsapp_url = _url_whatsapp(
                '56982108409',
                _mensaje_consulta_cliente(request.user, servicio.nombre),
            )
    if 'productos' in contexto:
        for producto in contexto['productos']:
            producto.whatsapp_url = _url_whatsapp(
                '56982108409',
                _mensaje_consulta_cliente(request.user, producto.nombre),
            )
    return render(request, template, contexto)


@never_cache
def cliente_home_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if not request.user.is_active or not (
        es_cliente(request.user) or _usuario_en_vista_cliente(request)
    ):
        return render(
            request,
            'usuarios/acceso_denegado.html',
            status=403,
        )
    return _vista_cliente(request, 'usuarios/cliente_sobre_nosotros.html')


@never_cache
def iniciar_vista_cliente_admin(request):
    if not request.user.is_authenticated or not (
        es_administrador(request.user) or es_colaborador(request.user)
    ):
        return render(request, 'usuarios/acceso_denegado.html', status=403)
    if es_colaborador(request.user):
        request.session['colaborador_vista_cliente'] = True
    else:
        request.session['admin_vista_cliente'] = True
    return redirect('cliente_home')


@never_cache
def salir_vista_cliente_admin(request):
    if not request.user.is_authenticated or not (
        es_administrador(request.user) or es_colaborador(request.user)
    ):
        return render(request, 'usuarios/acceso_denegado.html', status=403)
    if es_colaborador(request.user):
        request.session.pop('colaborador_vista_cliente', None)
        return redirect('colaborador_mi_agenda')
    request.session.pop('admin_vista_cliente', None)
    return redirect('admin_dashboard')


def _normalizar_busqueda(texto):
    texto = unicodedata.normalize('NFD', texto)
    return ''.join(
        caracter for caracter in texto
        if not unicodedata.combining(caracter)
    ).casefold()


@require_GET
def sugerencias_busqueda_cliente(request):
    permitido = (
        request.user.is_authenticated
        and request.user.is_active
        and (es_cliente(request.user) or _usuario_en_vista_cliente(request))
    )
    if not permitido:
        return JsonResponse({'results': [], 'error': 'Debes iniciar sesión para buscar.'}, status=403)

    query = request.GET.get('q', '').strip()[:100]
    if len(query) < 2:
        return JsonResponse({'results': []})
    query_normalizada = _normalizar_busqueda(query)
    terminos = query_normalizada.split()
    resultados = []

    secciones = [
        ('Nosotras', 'Conoce Nicolett Studio Fantasy', reverse('cliente_home'), 'seccion'),
        ('Servicios y citas', 'Explora los servicios disponibles', reverse('cliente_servicios'), 'seccion'),
        ('Productos', 'Revisa productos disponibles', reverse('cliente_productos'), 'seccion'),
        ('Mis citas', 'Consulta tus próximas citas e historial', reverse('cliente_gestionar_citas'), 'seccion'),
        ('Historial de pagos', 'Revisa tus pagos y compras', reverse('cliente_historial_pagos'), 'seccion'),
        ('Configuración', 'Datos personales, direcciones y contraseña', reverse('cliente_configuracion'), 'seccion'),
        ('Direcciones de envío', 'Administra tus direcciones de despacho', f"{reverse('cliente_configuracion')}#direcciones-envio", 'seccion'),
        ('Direcciones de facturación', 'Administra tus datos de facturación', f"{reverse('cliente_configuracion')}#direcciones-facturacion", 'seccion'),
        ('Datos de contacto', 'Actualiza tu información personal', f"{reverse('cliente_configuracion')}#datos-contacto", 'seccion'),
        ('Cambiar contraseña', 'Actualiza la contraseña de tu cuenta', f"{reverse('cliente_configuracion')}#cambiar-contrasena", 'seccion'),
    ]
    for titulo, descripcion, url, tipo in secciones:
        if _usuario_en_vista_cliente(request) and titulo in {
            'Mis citas',
            'Historial de pagos',
            'Configuración',
            'Direcciones de envío',
            'Direcciones de facturación',
            'Datos de contacto',
            'Cambiar contraseña',
        }:
            continue
        contenido = _normalizar_busqueda(f'{titulo} {descripcion}')
        if all(termino in contenido for termino in terminos):
            resultados.append({
                'title': titulo,
                'description': descripcion,
                'url': url,
                'type': tipo,
            })

    if not _usuario_en_vista_cliente(request):
        servicios = Servicio.objects.filter(activo=True).select_related('categoria')
        for servicio in servicios:
            contenido = _normalizar_busqueda(
                f'{servicio.nombre} {servicio.categoria.nombre} {servicio.descripcion or ""}'
            )
            if all(termino in contenido for termino in terminos):
                resultados.append({
                    'title': servicio.nombre,
                    'description': f'Servicio · {servicio.categoria.nombre}',
                    'url': f"{reverse('cliente_servicios')}#servicio-{servicio.pk}",
                    'type': 'servicio',
                })

        productos = Producto.objects.filter(
            activo=True,
            stock__gt=0,
        ).select_related('categoria')
        for producto in productos:
            contenido = _normalizar_busqueda(
                f'{producto.nombre} {producto.categoria.nombre} {producto.descripcion or ""}'
            )
            if all(termino in contenido for termino in terminos):
                resultados.append({
                    'title': producto.nombre,
                    'description': f'Producto · {producto.categoria.nombre}',
                    'url': f"{reverse('cliente_productos')}#producto-{producto.pk}",
                    'type': 'producto',
                })

    return JsonResponse({'results': resultados[:8]})


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
    ).select_related('categoria').order_by(*ordenes[orden])
    servicios_galeria = _agrupar_servicios_galeria(servicios)
    return _vista_cliente(
        request,
        'usuarios/cliente_seccion.html',
        {
            'titulo': 'Servicios',
            'descripcion': 'Aquí podrás conocer los servicios disponibles.',
            'servicios': servicios,
            'servicios_galeria': servicios_galeria,
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


def _agrupar_servicios_galeria(servicios: QuerySet) -> dict[str, list[Servicio]]:
    categorias = {
        'corte': ('corte', 'estilo'),
        'tratamientos': ('tratamiento', 'capilar', 'keratina'),
        'manos': ('manicure', 'pedicure', 'uña', 'nail'),
        'depilaciones': ('depilacion',),
        'peinados': ('peinado',),
        'coloracion': ('colorimetria', 'coloracion', 'tinte', 'balayage'),
        'podologia': ('podologia',),
        'lash_brow': ('lash', 'brow'),
    }
    agrupados = {categoria: [] for categoria in categorias}
    for servicio in servicios:
        texto = unicodedata.normalize(
            'NFKD',
            f'{servicio.nombre} {servicio.categoria.nombre}',
        )
        texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
        texto = texto.casefold()
        for categoria, terminos in categorias.items():
            if any(termino in texto for termino in terminos):
                agrupados[categoria].append(servicio)
    agrupados['depilaciones'].sort(key=lambda servicio: servicio.precio)
    agrupados['peinados'].sort(key=lambda servicio: servicio.precio)
    return agrupados


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
            }.get(reserva.estado_cliente, 'border-[#ead7bc] bg-[#fae9cf] text-[#6b5643]'),
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
    if not request.user.is_authenticated:
        return redirect('login')
    if not request.user.is_active or not es_cliente(request.user):
        return render(request, 'usuarios/acceso_denegado.html', status=403)
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
    if not request.user.is_authenticated:
        return redirect('login')
    if not request.user.is_active or not es_cliente(request.user):
        return render(request, 'usuarios/acceso_denegado.html', status=403)
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
