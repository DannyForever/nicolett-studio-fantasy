from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from importlib import import_module
import logging
from secrets import compare_digest
import smtplib
from urllib.parse import unquote, urlencode, urlparse
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.db import DatabaseError, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from config.formatters import formatear_pesos
from agenda.models import (
    DiaCerrado,
    Disponibilidad,
    Reserva,
    ReservaCitaTemporal,
)
from agenda.views import (
    RESERVA_CITA_CARRITO_MINUTOS,
    horas_disponibles,
)
from pagos.models import Pago
from pagos.transbank import (
    TransbankGatewayError,
    commit_transaction,
    create_transaction,
    get_transaction,
    refund_transaction,
    transaction_status,
)
from panel_admin.models import Producto, Servicio
from ventas.models import DetalleVenta, Venta
from usuarios.permissions import es_cliente

from .models import (
    DetallePedido,
    PagoSimulado,
    Pedido,
    ReservaProductoCarrito,
    TransbankPago,
)


CLAVE_CARRITO = 'carrito_compra'
ABONO_SERVICIO = Decimal('5000.00')
RESERVA_PRODUCTO_MINUTOS = 30
logger = logging.getLogger(__name__)


def cantidad_articulos(request):
    carrito = request.session.get(CLAVE_CARRITO, {})
    productos = carrito.get('productos', {})
    servicios = carrito.get('servicios', [])
    return sum(
        cantidad
        for cantidad in productos.values()
        if isinstance(cantidad, int) and cantidad > 0
    ) + len(servicios)


def resumen_carrito(request):
    carrito = _carrito_sesion(request)
    resumen = []
    total = Decimal('0')
    productos = Producto.objects.filter(
        pk__in=[
            int(product_id)
            for product_id in carrito['productos']
            if str(product_id).isdecimal()
        ],
        activo=True,
    )
    for producto in productos:
        cantidad = carrito['productos'].get(str(producto.pk), 0)
        if not isinstance(cantidad, int) or cantidad < 1:
            continue
        subtotal = producto.precio * cantidad
        resumen.append({
            'tipo': 'producto',
            'id': producto.pk,
            'key': str(producto.pk),
            'nombre': producto.nombre,
            'cantidad': cantidad,
            'precio': producto.precio,
            'subtotal': subtotal,
            'url': reverse('cliente_carrito_actualizar'),
        })
        total += subtotal

    servicios_ids = [
        int(item['id'])
        for item in carrito['servicios']
        if isinstance(item, dict) and str(item.get('id', '')).isdecimal()
    ]
    servicios = {
        servicio.pk: servicio
        for servicio in Servicio.objects.filter(pk__in=servicios_ids, activo=True)
    }
    from usuarios.models import Usuario

    profesional_ids = {
        int(item['profesional'])
        for item in carrito['servicios']
        if isinstance(item, dict) and str(item.get('profesional', '')).isdecimal()
    }
    profesionales = {
        profesional.pk: profesional
        for profesional in Usuario.objects.filter(pk__in=profesional_ids)
    }
    for item in carrito['servicios']:
        if not isinstance(item, dict) or not str(item.get('id', '')).isdecimal():
            continue
        servicio = servicios.get(int(item['id']))
        if servicio is None:
            continue
        profesional = (
            profesionales.get(int(item['profesional']))
            if str(item.get('profesional', '')).isdecimal()
            else None
        )
        resumen.append({
            'tipo': 'servicio',
            'id': servicio.pk,
            'key': item.get('key', ''),
            'nombre': servicio.nombre,
            'cantidad': 1,
            'precio': servicio.precio,
            'subtotal': servicio.precio,
            'url': reverse('cliente_carrito_actualizar'),
            'fecha': item.get('fecha', ''),
            'hora': item.get('hora', ''),
            'profesional': (
                ' '.join(part for part in (
                    profesional.nombre,
                    profesional.segundo_nombre,
                    profesional.apellido_paterno,
                    profesional.apellido_materno,
                ) if part) if profesional else ''
            ),
            'pago': item.get('pago', ''),
            'viene_con_acompanante': item.get('viene_con_acompanante', False),
        })
        total += servicio.precio
    return resumen, total


def _carrito_sesion(request):
    carrito = request.session.get(CLAVE_CARRITO)
    if not isinstance(carrito, dict):
        carrito = {'productos': {}, 'servicios': []}
    if not isinstance(carrito.get('productos'), dict):
        carrito['productos'] = {}
    if not isinstance(carrito.get('servicios'), list):
        carrito['servicios'] = []
    carrito.setdefault('productos', {})
    carrito.setdefault('servicios', [])
    return carrito


def _guardar_carrito(request, carrito):
    request.session[CLAVE_CARRITO] = carrito
    request.session.modified = True


def _cliente_view(view):
    return user_passes_test(es_cliente, login_url='login')(login_required(view, login_url='login'))


def _liberar_reservas_vencidas(request=None):
    ahora = timezone.now()
    producto_ids = list(
        ReservaProductoCarrito.objects.filter(vence_en__lte=ahora)
        .values_list('producto_id', flat=True)
        .distinct()
    )
    expiradas_sesion = []
    if producto_ids:
        with transaction.atomic():
            productos = {
                producto.pk: producto
                for producto in Producto.objects.select_for_update()
                .filter(pk__in=producto_ids).order_by('pk')
            }
            reservas = ReservaProductoCarrito.objects.select_for_update().filter(
                producto_id__in=producto_ids,
                vence_en__lte=ahora,
            ).order_by('pk')
            for reserva in reservas:
                producto = productos.get(reserva.producto_id)
                if producto is not None:
                    producto.stock += reserva.cantidad
                    producto.save(update_fields=['stock'])
                if (
                    request is not None
                    and reserva.session_key == request.session.session_key
                ):
                    expiradas_sesion.append(str(reserva.producto_id))
                reserva.delete()

    if expiradas_sesion and request is not None:
        carrito = request.session.get(CLAVE_CARRITO, {})
        productos_carrito = carrito.get('productos', {}) if isinstance(carrito, dict) else {}
        for producto_id in expiradas_sesion:
            productos_carrito.pop(producto_id, None)
        if isinstance(carrito, dict):
            carrito['productos'] = productos_carrito
            request.session[CLAVE_CARRITO] = carrito
            request.session.modified = True
            messages.info(
                request,
                'La reserva temporal de un producto venció y volvió a estar disponible.',
            )

    holds_expirados = ReservaCitaTemporal.objects.filter(vence_en__lte=ahora)
    expirados_actual = list(
        holds_expirados.filter(
            session_key=request.session.session_key,
        ).values_list('cart_item_key', flat=True)
    ) if request is not None and request.session.session_key else []
    holds_expirados.delete()
    if expirados_actual and request is not None:
        carrito = _carrito_sesion(request)
        keys = set(expirados_actual)
        carrito['servicios'] = [
            item for item in carrito['servicios']
            if not isinstance(item, dict) or item.get('key') not in keys
        ]
        _guardar_carrito(request, carrito)
        messages.info(
            request,
            'La reserva temporal de una cita venció y el horario volvió a estar disponible.',
        )


def _session_key(request):
    if request.session.session_key is None:
        request.session.create()
    return request.session.session_key


def _mensaje_checkout(request, nivel, texto, habilitado=True):
    if habilitado:
        messages.add_message(request, nivel, texto)


def _limpiar_carrito_checkout(request, session_key):
    if request.session.session_key == session_key:
        request.session.pop(CLAVE_CARRITO, None)
        request.session.modified = True
        return

    session_store = import_module(settings.SESSION_ENGINE).SessionStore(
        session_key=session_key,
    )
    if session_store.exists(session_key):
        session_store.pop(CLAVE_CARRITO, None)
        session_store.save()


def _referencia_transbank(attempt, salt):
    return signing.dumps({'attempt': attempt.pk}, salt=salt, compress=True)


def _cargar_referencia_transbank(referencia, salt, max_age=60 * 60):
    ultimo_error = None
    for _ in range(3):
        try:
            return signing.loads(referencia, salt=salt, max_age=max_age)
        except signing.BadSignature as error:
            ultimo_error = error
            referencia_decodificada = unquote(referencia)
            if referencia_decodificada == referencia:
                raise
            referencia = referencia_decodificada
    raise ultimo_error


def _ajustar_reserva_producto(session_key, producto_id, cantidad):
    producto = Producto.objects.select_for_update().filter(pk=producto_id).first()
    if producto is None:
        return None, False
    reserva = ReservaProductoCarrito.objects.select_for_update().filter(
        session_key=session_key,
        producto_id=producto_id,
    ).first()
    cantidad_reservada = reserva.cantidad if reserva else 0
    diferencia = cantidad - cantidad_reservada
    if diferencia > 0 and producto.stock < diferencia:
        return producto, False

    if diferencia:
        producto.stock -= diferencia
        producto.save(update_fields=['stock'])

    if cantidad <= 0:
        if reserva:
            reserva.delete()
    else:
        ReservaProductoCarrito.objects.update_or_create(
            session_key=session_key,
            producto_id=producto_id,
            defaults={
                'cantidad': cantidad,
                'vence_en': ahora_reserva_productos(),
            },
        )
    return producto, True


def ahora_reserva_productos():
    return timezone.now() + timedelta(minutes=RESERVA_PRODUCTO_MINUTOS)


@_cliente_view
def ver_carrito(request):
    _liberar_reservas_vencidas(request)
    carrito = _carrito_sesion(request)
    session_key = _session_key(request)
    ahora = timezone.now()
    reservas = {
        reserva.producto_id: reserva
        for reserva in ReservaProductoCarrito.objects.filter(
            session_key=session_key,
            vence_en__gt=ahora,
        )
    } if session_key else {}
    holds_cita = {
        hold.cart_item_key: hold
        for hold in ReservaCitaTemporal.objects.filter(
            session_key=session_key,
            vence_en__gt=ahora,
        )
    } if session_key else {}
    if reservas:
        ReservaProductoCarrito.objects.filter(
            session_key=session_key,
            vence_en__gt=ahora,
        ).update(vence_en=ahora_reserva_productos())
    if session_key:
        ReservaCitaTemporal.objects.filter(
            session_key=session_key,
            vence_en__gt=ahora,
        ).update(
            vence_en=ahora + timedelta(minutes=RESERVA_CITA_CARRITO_MINUTOS),
        )
    ids_producto = []
    for product_id, quantity in carrito['productos'].items():
        if str(product_id).isdecimal() and isinstance(quantity, int) and quantity > 0:
            ids_producto.append(int(product_id))
    productos_db = {
        producto.pk: producto
        for producto in Producto.objects.filter(pk__in=ids_producto)
    }
    productos = []
    total_productos = Decimal('0')
    puede_pagar = True
    for product_id, quantity in carrito['productos'].items():
        if not str(product_id).isdecimal() or not isinstance(quantity, int) or quantity < 1:
            productos.append({
                'id': product_id,
                'cantidad': quantity,
                'disponible': False,
                'nombre': 'Producto con cantidad no válida',
            })
            puede_pagar = False
            continue
        producto = productos_db.get(int(product_id))
        if producto is None:
            productos.append({
                'id': product_id,
                'cantidad': quantity,
                'disponible': False,
                'nombre': 'Producto no disponible',
            })
            puede_pagar = False
            continue
        subtotal = producto.precio * quantity
        reserva = reservas.get(producto.pk)
        disponible = (
            producto.activo
            and reserva is not None
            and reserva.cantidad == quantity
        )
        productos.append({
            'id': producto.pk,
            'cantidad': quantity,
            'producto': producto,
            'nombre': producto.nombre,
            'precio': producto.precio,
            'subtotal': subtotal,
            'disponible': disponible,
        })
        if disponible:
            total_productos += subtotal
        else:
            puede_pagar = False

    servicios = []
    total_servicios = Decimal('0')
    total_servicios_completo = Decimal('0')
    total_servicios_abono = Decimal('0')
    saldos_servicios = []
    total_pagar = total_productos
    from usuarios.models import Usuario

    profesional_ids = {
        int(item['profesional'])
        for item in carrito['servicios']
        if isinstance(item, dict) and str(item.get('profesional', '')).isdecimal()
    }
    profesionales = {
        profesional.pk: profesional
        for profesional in Usuario.objects.filter(pk__in=profesional_ids)
    }
    for item in carrito['servicios']:
        if not isinstance(item, dict) or not str(item.get('id', '')).isdecimal():
            servicios.append({
                'key': '',
                'disponible': False,
                'nombre': 'Servicio no disponible',
            })
            puede_pagar = False
            continue
        servicio = Servicio.objects.filter(pk=item['id'], activo=True).first()
        if servicio is None:
            servicios.append({
                'key': item.get('key', ''),
                'disponible': False,
                'nombre': 'Servicio no disponible',
            })
            puede_pagar = False
            continue
        precio = servicio.precio
        modalidad = item.get('pago', '')
        monto_pagar = min(precio, ABONO_SERVICIO) if modalidad == 'abono' else precio
        cita_completa = all(item.get(campo) for campo in ('fecha', 'profesional', 'hora'))
        hold = holds_cita.get(item.get('key'))
        reserva_vigente = bool(
            hold
            and hold.servicio_id == servicio.pk
            and hold.fecha.isoformat() == item.get('fecha')
            and hold.hora.strftime('%H:%M') == item.get('hora')
            and str(hold.profesional_id) == str(item.get('profesional'))
        )
        profesional = profesionales.get(int(item['profesional'])) if str(
            item.get('profesional', ''),
        ).isdecimal() else None
        fecha_display = item.get('fecha', '')
        try:
            fecha_display = date.fromisoformat(fecha_display).strftime('%d/%m/%Y')
        except (TypeError, ValueError):
            fecha_display = 'Fecha no válida'
        servicios.append({
            'key': item.get('key', ''),
            'id': servicio.pk,
            'categoria_id': servicio.categoria_id,
            'nombre': servicio.nombre,
            'precio': precio,
            'duracion': servicio.duracion_minutos,
            'fecha': item.get('fecha', ''),
            'fecha_display': fecha_display,
            'profesional_id': item.get('profesional', ''),
            'profesional_nombre': ' '.join(part for part in (
                profesional.nombre if profesional else '',
                profesional.segundo_nombre if profesional else '',
                profesional.apellido_paterno if profesional else '',
                profesional.apellido_materno if profesional else '',
            ) if part) if profesional else 'Sin profesional asignado',
            'hora': item.get('hora', ''),
            'pago': modalidad,
            'viene_con_acompanante': item.get('viene_con_acompanante', False),
            'viene_con_acompanante': item.get('viene_con_acompanante', False),
            'monto_pagar': monto_pagar,
            'saldo': precio - monto_pagar,
            'cita_completa': cita_completa,
            'disponible': True,
            'reserva_vigente': reserva_vigente,
        })
        total_servicios += precio
        if modalidad == 'completo':
            total_servicios_completo += monto_pagar
        elif modalidad == 'abono':
            total_servicios_abono += monto_pagar
            if precio > monto_pagar:
                saldos_servicios.append({
                    'nombre': servicio.nombre,
                    'saldo': precio - monto_pagar,
                })
        if modalidad in ('completo', 'abono'):
            total_pagar += monto_pagar
            if not cita_completa or not reserva_vigente:
                puede_pagar = False
        else:
            puede_pagar = False

    resumen, total_resumen = resumen_carrito(request)
    return render(request, 'usuarios/cliente_carrito.html', {
        'productos': productos,
        'servicios': servicios,
        'total_productos': total_productos,
        'total_servicios': total_servicios,
        'total_servicios_completo': total_servicios_completo,
        'total_servicios_abono': total_servicios_abono,
        'saldos_servicios': saldos_servicios,
        'saldo_servicios_pendiente': sum(
            (item['saldo'] for item in saldos_servicios),
            Decimal('0'),
        ),
        'total_pedido': total_productos + total_servicios,
        'total_pagar': total_pagar,
        'saldo_pendiente': total_productos + total_servicios - total_pagar,
        'cantidad_articulos_carrito': cantidad_articulos(request),
        'puede_pagar': puede_pagar and bool(productos or servicios),
        'resumen_carrito': resumen,
        'total_resumen_carrito': total_resumen,
    })


@_cliente_view
@require_POST
def agregar_producto(request, pk):
    destino = request.POST.get('return_to', '')

    def volver_al_catalogo():
        if destino and url_has_allowed_host_and_scheme(
            destino,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(destino)
        return redirect('cliente_productos')

    _liberar_reservas_vencidas(request)
    try:
        cantidad = int(request.POST.get('cantidad', '1'))
    except (TypeError, ValueError):
        messages.error(request, 'Indica una cantidad válida.')
        return volver_al_catalogo()
    if cantidad < 1:
        messages.error(request, 'La cantidad indicada no es válida.')
        return volver_al_catalogo()

    carrito = _carrito_sesion(request)
    clave = str(pk)
    nueva_cantidad = carrito['productos'].get(clave, 0) + cantidad
    session_key = _session_key(request)
    with transaction.atomic():
        producto_activo = Producto.objects.select_for_update().filter(
            pk=pk,
            activo=True,
        ).first()
        if producto_activo is None:
            messages.error(request, 'Este producto ya no está disponible.')
            return volver_al_catalogo()
        _, reservada = _ajustar_reserva_producto(
            session_key,
            pk,
            nueva_cantidad,
        )
        if not reservada:
            messages.error(request, 'No hay stock disponible para esa cantidad.')
            return volver_al_catalogo()
    carrito['productos'][clave] = nueva_cantidad
    _guardar_carrito(request, carrito)
    return volver_al_catalogo()


@_cliente_view
@require_POST
def agregar_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk, activo=True)
    return redirect(
        f"{reverse('cliente_servicios')}?servicio={servicio.pk}#servicios-semana",
    )


@_cliente_view
@require_POST
def actualizar_carrito(request):
    _liberar_reservas_vencidas(request)
    carrito = _carrito_sesion(request)
    tipo = request.POST.get('tipo', '')
    clave = request.POST.get('clave', '')
    if tipo == 'producto' and clave in carrito['productos']:
        try:
            cantidad = int(request.POST.get('cantidad', '0'))
        except (TypeError, ValueError):
            messages.error(request, 'Indica una cantidad válida.')
            return redirect('cliente_carrito')
        try:
            producto_id = int(clave)
        except ValueError:
            messages.error(request, 'No se encontró el producto seleccionado.')
            return redirect('cliente_carrito')
        with transaction.atomic():
            if cantidad > 0 and not Producto.objects.select_for_update().filter(
                pk=producto_id,
                activo=True,
            ).exists():
                messages.error(request, 'Este producto ya no está disponible.')
                return redirect('cliente_carrito')
            producto, reservada = _ajustar_reserva_producto(
                _session_key(request),
                producto_id,
                max(cantidad, 0),
            )
            if producto is None:
                messages.error(request, 'Este producto ya no está disponible.')
                return redirect('cliente_carrito')
            if not reservada:
                messages.error(request, 'La cantidad indicada supera el stock disponible.')
                return redirect('cliente_carrito')
        if cantidad <= 0:
            carrito['productos'].pop(clave, None)
        else:
            carrito['productos'][clave] = cantidad
    elif tipo == 'servicio':
        ReservaCitaTemporal.objects.filter(
            session_key=request.session.session_key or '',
            cart_item_key=clave,
        ).delete()
        carrito['servicios'] = [
            item for item in carrito['servicios']
            if not isinstance(item, dict) or item.get('key') != clave
        ]
        messages.success(request, 'Servicio eliminado del carrito.')
    else:
        messages.error(request, 'No se encontró el artículo seleccionado.')
        return redirect('cliente_carrito')
    _guardar_carrito(request, carrito)
    destino = request.POST.get('return_to', '')
    if destino and url_has_allowed_host_and_scheme(
        destino,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(destino)
    return redirect('cliente_carrito')


@_cliente_view
@require_POST
def guardar_cita_carrito(request, key):
    _liberar_reservas_vencidas(request)
    carrito = _carrito_sesion(request)
    item = next((linea for linea in carrito['servicios'] if linea.get('key') == key), None)
    if item is None:
        messages.error(request, 'No se encontró el servicio en tu carrito.')
        return redirect('cliente_carrito')
    try:
        fecha = date.fromisoformat(item.get('fecha', ''))
        hora = time.fromisoformat(item.get('hora', ''))
        profesional_id = item.get('profesional', '')
        pago = request.POST.get('pago', '')
        servicio = Servicio.objects.get(pk=item['id'], activo=True)
        if (
            not profesional_id.isdecimal()
            or int(profesional_id) < 1
            or hora.utcoffset() is not None
            or hora.second
            or hora.microsecond
            or pago not in ('completo', 'abono')
        ):
            raise ValueError
    except (ValueError, TypeError, Servicio.DoesNotExist):
        messages.error(request, 'La cita no tiene datos válidos. Vuelve a seleccionar el horario desde Servicios.')
        return redirect('cliente_carrito')

    try:
        fecha_enviada = date.fromisoformat(request.POST.get('fecha', ''))
        hora_enviada = time.fromisoformat(request.POST.get('hora', ''))
    except (TypeError, ValueError):
        fecha_enviada = None
        hora_enviada = None
    if (
        fecha_enviada != fecha
        or hora_enviada != hora
        or request.POST.get('profesional') != str(profesional_id)
    ):
        messages.error(request, 'Los datos de la cita están bloqueados. Vuelve a Servicios si necesitas otro horario.')
        return redirect('cliente_carrito')

    with transaction.atomic():
        hold = ReservaCitaTemporal.objects.select_for_update().filter(
            session_key=_session_key(request),
            cart_item_key=key,
            servicio_id=servicio.pk,
            fecha=fecha,
            hora=hora,
            profesional_id=int(profesional_id),
            vence_en__gt=timezone.now(),
        ).first()
        if hold is None:
            messages.error(request, 'La reserva temporal venció. Vuelve a seleccionar el horario desde Servicios.')
            return redirect('cliente_carrito')
        hold.vence_en = timezone.now() + timedelta(minutes=RESERVA_CITA_CARRITO_MINUTOS)
        hold.save(update_fields=['vence_en'])
        item['pago'] = pago
        _guardar_carrito(request, carrito)
    messages.success(request, 'Modalidad de pago actualizada.')
    return redirect('cliente_carrito')


def _profesional_valido(profesional_id, categoria_id):
    from usuarios.models import Usuario

    return Usuario.objects.filter(
        pk=profesional_id,
        is_active=True,
        deleted_at__isnull=True,
        rol__nombre__iexact='Colaborador',
        especialidades__categoria_id=categoria_id,
    ).exists()


def _enviar_confirmacion_pedido(request, pedido):
    if (
        not pedido.cliente.email
        or settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend'
    ):
        return False

    pago_transbank = getattr(pedido, 'pago_transbank', None)
    pago_simulado = pedido.pagos_simulados.first()
    if pago_transbank:
        transaccion_id = pago_transbank.transaccion_id or pago_transbank.buy_order
    elif pago_simulado:
        transaccion_id = pago_simulado.transaccion_id
    else:
        transaccion_id = 'No disponible'
    lineas = [
        f'Hola {pedido.cliente.nombre}, este es el comprobante de tu compra.',
        f'Número de compra: {pedido.pk}',
        f'Fecha: {timezone.localtime(pedido.creado_en):%d/%m/%Y %H:%M}',
        f'Monto pagado: {formatear_pesos(pedido.monto_pagado)}',
        f'Número de transacción: {transaccion_id}',
        '',
        'Detalle:',
    ]
    for detalle in pedido.detalles.select_related('reserva__profesional').all():
        if detalle.reserva_id:
            reserva = detalle.reserva
            fecha = timezone.localtime(reserva.fecha_hora)
            profesional = reserva.profesional
            nombre_profesional = ' '.join(part for part in (
                profesional.nombre,
                profesional.segundo_nombre,
                profesional.apellido_paterno,
                profesional.apellido_materno,
            ) if part) if profesional else 'Sin asignar'
            lineas.append(
                f'- Cita: {detalle.nombre}; {fecha:%d/%m/%Y} a las {fecha:%H:%M}; '
                f'profesional: {nombre_profesional}; pago: {formatear_pesos(detalle.monto_pagado)}.'
            )
        else:
            lineas.append(f'- Producto: {detalle.nombre} x{detalle.cantidad}.')
    lineas.extend((
        '',
        'Puedes cancelar o re-agendar tus citas desde Mis citas:',
        request.build_absolute_uri(reverse('cliente_gestionar_citas')),
    ))
    enviados = send_mail(
        'Comprobante de compra - Nicolett Studio',
        '\n'.join(lineas),
        getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
        [pedido.cliente.email],
        fail_silently=False,
    )
    return enviados == 1


def _enviar_formulario_transbank(request, intento):
    referencia = _referencia_transbank(intento, 'carrito.transbank.return')
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'referencia': referencia,
            'webpay_abierto': intento.estado == 'webpay_abierto',
        })
    return render(
        request,
        'usuarios/transbank_formulario.html',
        {
            'webpay_abierto': intento.estado == 'webpay_abierto',
            'referencia': referencia,
        },
    )


def _vigencia_intento_transbank():
    return timedelta(
        minutes=3 if settings.TRANSBANK_ENVIRONMENT == 'PRODUCTION' else 9,
    )


def _iniciar_pago_transbank(request, cliente, carrito, session_key, monto):
    ahora = timezone.now()
    limite_intento = ahora - _vigencia_intento_transbank()
    TransbankPago.objects.filter(
        session_key=session_key,
        estado__in=['iniciando', 'pendiente', 'webpay_abierto'],
        creado_en__lt=limite_intento,
    ).update(estado='error')
    pendiente = TransbankPago.objects.filter(
        session_key=session_key,
        estado__in=['iniciando', 'pendiente', 'webpay_abierto'],
        creado_en__gte=limite_intento,
    ).first()
    if pendiente:
        if pendiente.webpay_url and pendiente.token:
            return _enviar_formulario_transbank(
                request,
                pendiente,
            )
        messages.error(
            request,
            'Ya hay un pago iniciándose. Espera un momento y vuelve a revisar tu carrito.',
        )
        return redirect('cliente_carrito')
    if monto <= 0 or monto != monto.to_integral_value():
        messages.error(request, 'El monto del carrito no es válido para pagar con Transbank.')
        return redirect('cliente_carrito')

    intento = TransbankPago.objects.create(
        cliente=cliente,
        buy_order=uuid4().hex[:26],
        session_id=uuid4().hex,
        session_key=session_key,
        carrito=carrito,
        monto=monto,
    )
    try:
        gateway = get_transaction()
        referencia = _referencia_transbank(intento, 'carrito.transbank.return')
        ruta_retorno = reverse('cliente_webpay_retorno')
        if settings.TRANSBANK_ENVIRONMENT == 'PRODUCTION':
            return_url = settings.TRANSBANK_RETURN_URL
            if not return_url.startswith('https://'):
                raise ImproperlyConfigured(
                    'Production Transbank requires an HTTPS TRANSBANK_RETURN_URL.'
                )
        else:
            return_url = request.build_absolute_uri(ruta_retorno)
        return_url += ('&' if '?' in return_url else '?') + urlencode({'ref': referencia})
        respuesta = create_transaction(
            gateway,
            intento.buy_order,
            intento.session_id,
            int(monto),
            return_url,
        )
        if not isinstance(respuesta, dict):
            raise TransbankGatewayError('Transbank devolvió una respuesta de inicio inválida.')
        token = respuesta.get('token')
        webpay_url = respuesta.get('url')
        host_esperado = (
            'webpay3g.transbank.cl'
            if settings.TRANSBANK_ENVIRONMENT == 'PRODUCTION'
            else 'webpay3gint.transbank.cl'
        )
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(webpay_url, str)
            or urlparse(webpay_url).scheme != 'https'
            or urlparse(webpay_url).hostname != host_esperado
        ):
            raise TransbankGatewayError('Transbank devolvió una respuesta de inicio inválida.')
    except (ImproperlyConfigured, TransbankGatewayError):
        intento.estado = 'error'
        intento.save(update_fields=['estado', 'actualizado_en'])
        logger.exception('No se pudo iniciar el pago Transbank para el intento %s.', intento.pk)
        messages.error(
            request,
            'No se pudo iniciar el pago. No se realizó ningún cobro; intenta nuevamente.',
        )
        return redirect('cliente_carrito')

    intento.token = token
    intento.webpay_url = webpay_url
    intento.estado = 'pendiente'
    intento.save(update_fields=['token', 'webpay_url', 'estado', 'actualizado_en'])
    return _enviar_formulario_transbank(request, intento)


def _procesar_pago_carrito(
    request,
    carrito_override=None,
    session_key_override=None,
    transbank_pago=None,
):
    _liberar_reservas_vencidas(request if session_key_override is None else None)
    carrito = (
        carrito_override
        if carrito_override is not None
        else _carrito_sesion(request)
    )
    if not carrito['productos'] and not carrito['servicios']:
        _mensaje_checkout(request, messages.ERROR, 'Tu carrito está vacío.', transbank_pago is None)
        return redirect('cliente_carrito')
    session_key = session_key_override or _session_key(request)
    messages_enabled = transbank_pago is None

    with transaction.atomic():
        if transbank_pago is not None:
            transbank_pago = TransbankPago.objects.select_for_update().get(pk=transbank_pago.pk)
            if transbank_pago.estado == 'aprobado' and transbank_pago.pedido_id:
                return redirect('cliente_compra_resultado', pk=transbank_pago.pedido_id)
            if transbank_pago.estado != 'autorizado':
                return redirect('cliente_carrito')
        from usuarios.models import Usuario

        cliente = Usuario.objects.select_for_update().get(pk=request.user.pk)
        productos = []
        total_productos = Decimal('0')
        for product_id, quantity in carrito['productos'].items():
            if not str(product_id).isdecimal() or not isinstance(quantity, int) or quantity < 1:
                _mensaje_checkout(request, messages.ERROR, 'Hay una cantidad inválida en tu carrito.', messages_enabled)
                return redirect('cliente_carrito')
            producto = Producto.objects.select_for_update().filter(pk=product_id).first()
            reserva = ReservaProductoCarrito.objects.select_for_update().filter(
                session_key=session_key,
                producto_id=product_id,
                vence_en__gt=timezone.now(),
            ).first()
            if (
                producto is None
                or not producto.activo
                or reserva is None
                or reserva.cantidad != quantity
            ):
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'Un producto ya no está disponible o no tiene stock suficiente.',
                    messages_enabled,
                )
                return redirect('cliente_carrito')
            productos.append((producto, quantity))
            total_productos += producto.precio * quantity

        servicios = []
        total_servicios = Decimal('0')
        total_pagar = total_productos
        for item in carrito['servicios']:
            if not isinstance(item, dict):
                _mensaje_checkout(request, messages.ERROR, 'Hay un servicio inválido en tu carrito.', messages_enabled)
                return redirect('cliente_carrito')
            try:
                servicio = Servicio.objects.get(pk=item.get('id'), activo=True)
                fecha = date.fromisoformat(item.get('fecha', ''))
                hora = time.fromisoformat(item.get('hora', ''))
                profesional_id = item.get('profesional', '')
                if (
                    not profesional_id.isdecimal()
                    or int(profesional_id) < 1
                    or item.get('pago') not in ('completo', 'abono')
                    or hora.utcoffset() is not None
                    or hora.second
                    or hora.microsecond
                ):
                    raise ValueError
            except (ValueError, TypeError, Servicio.DoesNotExist):
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'Completa la fecha, el profesional, la hora y el pago de cada servicio antes de pagar.',
                    messages_enabled,
                )
                return redirect('cliente_carrito')
            if fecha < timezone.localdate() or DiaCerrado.objects.filter(fecha=fecha).exists():
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'Una cita tiene fecha pasada o el salón está cerrado ese día.',
                    messages_enabled,
                )
                return redirect('cliente_carrito')
            if not _profesional_valido(profesional_id, servicio.categoria_id):
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'Un profesional no está habilitado para el servicio seleccionado.',
                    messages_enabled,
                )
                return redirect('cliente_carrito')
            hold = ReservaCitaTemporal.objects.select_for_update().filter(
                session_key=session_key,
                cart_item_key=item.get('key', ''),
                vence_en__gt=timezone.now(),
            ).first()
            if (
                hold is None
                or hold.servicio_id != servicio.pk
                or hold.fecha != fecha
                or hold.hora.strftime('%H:%M') != hora.strftime('%H:%M')
                or hold.profesional_id != int(profesional_id)
            ):
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'La reserva temporal de una cita venció o cambió. '
                    'Guarda nuevamente el horario antes de pagar.',
                    messages_enabled,
                )
                return redirect('cliente_carrito')
            list(Disponibilidad.objects.select_for_update().filter(
                activo=True,
                fecha_especifica=fecha,
                servicio_id=servicio.pk,
                profesional_id=profesional_id,
            ))
            if hora.strftime('%H:%M') not in horas_disponibles(
                fecha,
                servicio,
                profesional_id=int(profesional_id),
                ignorar_carrito_item_key=item.get('key', ''),
                session_key=session_key,
            ):
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'Uno de los horarios seleccionados ya no está disponible.',
                    messages_enabled,
                )
                return redirect('cliente_carrito')
            monto_servicio = (
                min(servicio.precio, ABONO_SERVICIO)
                if item['pago'] == 'abono'
                else servicio.precio
            )
            inicio = datetime.combine(fecha, hora)
            fecha_hora = timezone.make_aware(inicio) if timezone.is_naive(inicio) else inicio
            servicios.append((
                item,
                servicio,
                fecha,
                hora,
                int(profesional_id),
                monto_servicio,
                fecha_hora,
            ))
            total_servicios += servicio.precio
            total_pagar += monto_servicio

        if not productos and not servicios:
            _mensaje_checkout(request, messages.ERROR, 'No hay artículos válidos para pagar.', messages_enabled)
            return redirect('cliente_carrito')

        fechas_citas = {fecha for _, _, fecha, _, _, _, _ in servicios}
        reservas_cliente = list(
            Reserva.objects.filter(
                cliente=cliente,
                fecha_hora__date__in=fechas_citas,
            ).exclude(estado__in=['cancelada', 'completada'])
        ) if fechas_citas else []
        citas_del_pedido = []
        for _, servicio, fecha, _, profesional_id, _, fecha_hora in servicios:
            fin = fecha_hora + timedelta(minutes=servicio.duracion_minutos)
            for reserva in reservas_cliente:
                if timezone.localtime(reserva.fecha_hora).date() != fecha:
                    continue
                inicio_existente = reserva.fecha_hora
                fin_existente = inicio_existente + timedelta(minutes=reserva.duracion_minutos)
                se_superponen = fecha_hora < fin_existente and inicio_existente < fin
                mismo_profesional = reserva.profesional_id == profesional_id
                misma_clienta = reserva.cliente_id == cliente.pk
                if se_superponen and (mismo_profesional or misma_clienta):
                    _mensaje_checkout(
                        request,
                        messages.ERROR,
                        'Una de las citas se cruza con otra reserva tuya o del profesional.',
                        messages_enabled,
                    )
                    return redirect('cliente_carrito')
            for otra_fecha, otro_inicio, otro_fin in citas_del_pedido:
                if (
                    fecha == otra_fecha
                    and fecha_hora < otro_fin
                    and otro_inicio < fin
                ):
                    _mensaje_checkout(
                        request,
                        messages.ERROR,
                        'Las citas de tu carrito no pueden quedar superpuestas.',
                        messages_enabled,
                    )
                    return redirect('cliente_carrito')
            citas_del_pedido.append((fecha, fecha_hora, fin))

        if (
            transbank_pago is None
            and settings.TRANSBANK_ENVIRONMENT != 'SIMULATED'
        ):
            return _iniciar_pago_transbank(
                request,
                cliente,
                carrito,
                session_key,
                total_pagar,
            )

        pedido = Pedido.objects.create(
            cliente=cliente,
            total=total_productos + total_servicios,
            monto_pagado=total_pagar,
            estado='abono' if total_pagar < total_productos + total_servicios else 'pagado',
        )

        for producto, cantidad in productos:
            DetallePedido.objects.create(
                pedido=pedido,
                tipo='producto',
                producto_id_catalogo=producto.pk,
                nombre=producto.nombre,
                cantidad=cantidad,
                precio_unitario=producto.precio,
                monto_pagado=producto.precio * cantidad,
                modalidad_pago='no_aplica',
            )
        if productos:
            ReservaProductoCarrito.objects.filter(
                session_key=session_key,
                producto_id__in=[producto.pk for producto, _ in productos],
            ).delete()

        for item, servicio, fecha, hora, profesional_id, monto_servicio, fecha_hora in servicios:
            if hora.strftime('%H:%M') not in horas_disponibles(
                fecha,
                servicio,
                profesional_id=profesional_id,
                ignorar_carrito_item_key=item.get('key', ''),
                session_key=session_key,
            ):
                _mensaje_checkout(
                    request,
                    messages.ERROR,
                    'El horario de una cita acaba de ser ocupado. Revisa el carrito e intenta otra vez.',
                    messages_enabled,
                )
                transaction.set_rollback(True)
                return redirect('cliente_carrito')
            profesional = Usuario.objects.get(pk=profesional_id)
            reserva = Reserva.objects.create(
                fecha_hora=fecha_hora,
                estado='confirmada',
                origen='cliente',
                cliente=cliente,
                creada_por=cliente,
                profesional=profesional,
                servicio_id=servicio.pk,
                cliente_nombre=' '.join(
                    parte for parte in (
                        cliente.nombre,
                        cliente.segundo_nombre,
                        cliente.apellido_paterno,
                        cliente.apellido_materno,
                    ) if parte
                ) or cliente.email,
                cliente_email=cliente.email,
                cliente_telefono=cliente.telefono,
                servicio_nombre=servicio.nombre,
                duracion_minutos=servicio.duracion_minutos,
                viene_con_acompanante=item.get('viene_con_acompanante', False) is True,
            )
            DetallePedido.objects.create(
                pedido=pedido,
                tipo='servicio',
                servicio_id_catalogo=servicio.pk,
                nombre=servicio.nombre,
                cantidad=1,
                precio_unitario=servicio.precio,
                monto_pagado=monto_servicio,
                modalidad_pago=item['pago'],
                reserva=reserva,
            )
            ReservaCitaTemporal.objects.filter(
                session_key=session_key,
                cart_item_key=item.get('key', ''),
            ).delete()

        if transbank_pago is None:
            transaccion_id = str(uuid4())
            PagoSimulado.objects.create(
                pedido=pedido,
                monto=total_pagar,
                transaccion_id=transaccion_id,
            )
            metodo_pago = 'Carrito cliente'
        else:
            transaccion_id = transbank_pago.buy_order
            transbank_pago.pedido = pedido
            transbank_pago.estado = 'aprobado'
            transbank_pago.transaccion_id = transaccion_id
            transbank_pago.save(update_fields=[
                'pedido',
                'estado',
                'transaccion_id',
                'actualizado_en',
            ])
            metodo_pago = 'Webpay Plus'
        venta = Venta.objects.create(
            cliente=cliente,
            total=total_productos + total_servicios,
            estado='Completada' if total_pagar >= total_productos + total_servicios else 'Pendiente',
        )
        for producto, cantidad in productos:
            DetalleVenta.objects.create(
                venta=venta,
                producto=producto,
                cantidad=cantidad,
                subtotal=producto.precio * cantidad,
                item_nombre=producto.nombre,
                item_descripcion=producto.descripcion or '',
                precio_unitario=producto.precio,
            )
        for _, servicio, _, _, _, _, _ in servicios:
            DetalleVenta.objects.create(
                venta=venta,
                servicio=servicio,
                cantidad=1,
                subtotal=servicio.precio,
                item_nombre=servicio.nombre,
                item_descripcion=servicio.descripcion or '',
                precio_unitario=servicio.precio,
            )
        Pago.objects.create(
            venta=venta,
            monto=total_pagar,
            metodo_pago=metodo_pago,
            estado_pago='Aprobado',
            transaccion_id=transaccion_id,
        )

    _limpiar_carrito_checkout(request, session_key)
    try:
        comprobante_enviado = _enviar_confirmacion_pedido(request, pedido)
    except (OSError, smtplib.SMTPException):
        logger.exception('No se pudo enviar el correo de confirmación del pedido %s.', pedido.pk)
        comprobante_enviado = False

    if not comprobante_enviado:
        _mensaje_checkout(
            request,
            messages.WARNING,
            'El pago y la cita se registraron, pero no se pudo enviar el comprobante al correo. '
            'Revisa la configuración de correo o consulta tus compras y citas en tu cuenta.',
            messages_enabled,
        )
    else:
        _mensaje_checkout(
            request,
            messages.SUCCESS,
            'Pago y cita registrados correctamente. Enviamos el comprobante a tu correo; '
            'también puedes gestionar la cita desde Mis citas.',
            messages_enabled,
        )
    return redirect('cliente_compra_resultado', pk=pedido.pk)


@_cliente_view
@require_GET
def checkout_carrito(request):
    _liberar_reservas_vencidas(request)
    carrito = _carrito_sesion(request)
    resumen, total_pedido = resumen_carrito(request)
    total_pagar = Decimal('0')
    for item in resumen:
        if item['tipo'] == 'producto':
            total_pagar += item['subtotal']
        elif item['pago'] == 'completo':
            total_pagar += item['precio']
        elif item['pago'] == 'abono':
            total_pagar += min(item['precio'], ABONO_SERVICIO)

    servicios_completos = all(
        all(item.get(campo) for campo in ('fecha', 'hora', 'profesional'))
        and item.get('pago') in ('completo', 'abono')
        for item in carrito['servicios']
        if isinstance(item, dict)
    ) and all(isinstance(item, dict) for item in carrito['servicios'])
    puede_pagar = (
        bool(carrito['productos'] or carrito['servicios'])
        and len(resumen) == len(carrito['productos']) + len(carrito['servicios'])
        and servicios_completos
        and total_pagar > 0
    )
    return render(request, 'usuarios/cliente_pago.html', {
        'resumen_carrito': resumen,
        'total_resumen_carrito': total_pedido,
        'total_pedido': total_pedido,
        'total_pagar': total_pagar,
        'saldo_pendiente': total_pedido - total_pagar,
        'carrito_tiene_items': bool(carrito['productos'] or carrito['servicios']),
        'puede_pagar': puede_pagar,
        'modo_simulado': settings.TRANSBANK_ENVIRONMENT == 'SIMULATED',
        'modo_integracion': settings.TRANSBANK_ENVIRONMENT == 'INTEGRATION',
    })


@_cliente_view
@require_POST
def pagar_carrito(request):
    return _procesar_pago_carrito(request)


def _render_estado_transbank(request, titulo, mensaje):
    return render(
        request,
        'usuarios/cliente_transbank_resultado.html',
        {
            'titulo': titulo,
            'mensaje': mensaje,
            'resumen_carrito': [],
            'total_resumen_carrito': Decimal('0'),
            'cantidad_articulos_carrito': 0,
        },
    )


def _reembolsar_transbank(intento, gateway, monto):
    intento.estado = 'reembolso_pendiente'
    intento.save(update_fields=['estado', 'actualizado_en'])
    try:
        respuesta = refund_transaction(gateway, intento.token, int(monto))
    except TransbankGatewayError:
        logger.exception('No se pudo solicitar el reembolso del intento Transbank %s.', intento.pk)
        return False
    if (
        not isinstance(respuesta, dict)
        or str(respuesta.get('response_code')) != '0'
        or respuesta.get('type') != 'REVERSED'
    ):
        logger.error(
            'Transbank no confirmó el reembolso total del intento %s.',
            intento.pk,
        )
        return False
    intento.estado = 'reembolsado'
    intento.save(update_fields=['estado', 'actualizado_en'])
    return True


def _url_resultado_transbank(intento):
    referencia = _referencia_transbank(intento, 'carrito.transbank.result')
    return (
        f"{reverse('cliente_compra_resultado', args=[intento.pedido_id])}"
        f"?{urlencode({'ref': referencia})}"
    )


def _liberar_citas_intento_transbank(request, intento):
    carrito_intento = intento.carrito if isinstance(intento.carrito, dict) else {}
    servicios_intento = carrito_intento.get('servicios', [])
    if not isinstance(servicios_intento, list):
        return
    claves_citas = {
        item.get('key')
        for item in servicios_intento
        if isinstance(item, dict) and item.get('key')
    }
    if not claves_citas or not intento.session_key:
        return

    with transaction.atomic():
        intento_actual = TransbankPago.objects.select_for_update().get(pk=intento.pk)
        if intento_actual.estado == 'aprobado' or intento_actual.pedido_id:
            return
        ReservaCitaTemporal.objects.filter(
            session_key=intento.session_key,
            cart_item_key__in=claves_citas,
        ).delete()

    def quitar_citas(carrito):
        if not isinstance(carrito, dict) or not isinstance(carrito.get('servicios'), list):
            return False
        citas_restantes = [
            item for item in carrito['servicios']
            if not isinstance(item, dict) or item.get('key') not in claves_citas
        ]
        if len(citas_restantes) == len(carrito['servicios']):
            return False
        carrito['servicios'] = citas_restantes
        return True

    if request.session.session_key == intento.session_key:
        carrito = _carrito_sesion(request)
        if quitar_citas(carrito):
            _guardar_carrito(request, carrito)
        return

    session_store_class = import_module(settings.SESSION_ENGINE).SessionStore
    session_store = session_store_class(session_key=intento.session_key)
    if not session_store.exists(intento.session_key):
        return
    carrito = session_store.get(CLAVE_CARRITO)
    if quitar_citas(carrito):
        session_store[CLAVE_CARRITO] = carrito
        session_store.save()


@_cliente_view
@require_POST
def abrir_transbank(request):
    try:
        datos_referencia = _cargar_referencia_transbank(
            request.POST.get('ref', ''),
            'carrito.transbank.return',
        )
    except signing.BadSignature:
        return HttpResponseBadRequest('Referencia de pago inválida.')
    intento = get_object_or_404(
        TransbankPago.objects.select_related('pedido'),
        pk=datos_referencia.get('attempt'),
        cliente=request.user,
        session_key=request.session.session_key,
    )
    if intento.estado == 'aprobado' and intento.pedido_id:
        return redirect(_url_resultado_transbank(intento))
    if intento.estado == 'webpay_abierto':
        return _enviar_formulario_transbank(request, intento)
    if intento.estado != 'pendiente' or not intento.token or not intento.webpay_url:
        messages.info(request, 'Este intento ya no está disponible. Puedes volver al carrito.')
        return redirect('cliente_carrito')
    if intento.creado_en < timezone.now() - _vigencia_intento_transbank():
        TransbankPago.objects.filter(
            pk=intento.pk,
            estado='pendiente',
        ).update(estado='error')
        messages.info(request, 'La sesión de pago venció. Inicia un nuevo intento desde el carrito.')
        return redirect('cliente_carrito')

    abierto = TransbankPago.objects.filter(
        pk=intento.pk,
        estado='pendiente',
    ).update(
        estado='webpay_abierto',
        actualizado_en=timezone.now(),
    )
    if not abierto:
        intento.refresh_from_db()
        if intento.estado == 'webpay_abierto':
            return _enviar_formulario_transbank(request, intento)
        messages.info(request, 'Este intento ya no está disponible. Puedes volver al carrito.')
        return redirect('cliente_carrito')

    return render(
        request,
        'usuarios/transbank_envio.html',
        {
            'webpay_url': intento.webpay_url,
            'token': intento.token,
        },
    )


@_cliente_view
@require_POST
def volver_carrito_transbank(request):
    try:
        datos_referencia = _cargar_referencia_transbank(
            request.POST.get('ref', ''),
            'carrito.transbank.return',
        )
    except signing.BadSignature:
        return HttpResponseBadRequest('Referencia de pago inválida.')
    intento = get_object_or_404(
        TransbankPago.objects.select_related('pedido'),
        pk=datos_referencia.get('attempt'),
        cliente=request.user,
        session_key=request.session.session_key,
    )
    if intento.estado == 'aprobado' and intento.pedido_id:
        return redirect(_url_resultado_transbank(intento))
    if intento.estado not in (
        'iniciando',
        'pendiente',
        'webpay_abierto',
        'autorizado',
    ) or not intento.token:
        messages.info(request, 'Puedes revisar tu carrito y volver a intentarlo.')
        return redirect('cliente_carrito')

    try:
        respuesta = transaction_status(get_transaction(), intento.token)
    except (ImproperlyConfigured, TransbankGatewayError):
        logger.exception('No se pudo verificar el intento Transbank %s al volver al carrito.', intento.pk)
        return _render_estado_transbank(
            request,
            'No pudimos verificar el pago',
            'No vuelvas a pagar todavía. No pudimos confirmar el estado con Transbank; inténtalo más tarde o contacta al salón.',
        )
    if not isinstance(respuesta, dict):
        logger.error(
            'Transbank devolvió un estado inválido para el intento %s al volver al carrito.',
            intento.pk,
        )
        return _render_estado_transbank(
            request,
            'No pudimos verificar el pago',
            'No vuelvas a pagar todavía. Contacta al salón para confirmar el estado de la transacción.',
        )

    try:
        monto_confirmado = Decimal(str(respuesta['amount']))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        monto_confirmado = Decimal('-1')
    if (
        respuesta.get('buy_order') != intento.buy_order
        or respuesta.get('session_id') != intento.session_id
        or monto_confirmado != intento.monto
    ):
        logger.error(
            'Transbank devolvió datos que no coinciden con el intento %s al volver al carrito.',
            intento.pk,
        )
        return _render_estado_transbank(
            request,
            'No pudimos verificar el pago',
            'No vuelvas a pagar todavía. Contacta al salón para confirmar el estado de la transacción.',
        )

    estado_transbank = respuesta.get('status')
    if estado_transbank == 'AUTHORIZED' and str(respuesta.get('response_code')) == '0':
        intento.estado = 'autorizado'
        intento.save(update_fields=['estado', 'actualizado_en'])
        referencia = _referencia_transbank(intento, 'carrito.transbank.return')
        return redirect(
            f"{reverse('cliente_webpay_retorno')}?{urlencode({
                'ref': referencia,
                'token_ws': intento.token,
            })}",
        )
    if estado_transbank in ('INITIALIZED', 'FAILED', 'REVERSED', 'NULLIFIED'):
        intento.estado = 'rechazado' if estado_transbank == 'FAILED' else 'anulado'
        intento.save(update_fields=['estado', 'actualizado_en'])
        _liberar_citas_intento_transbank(request, intento)
        messages.info(
            request,
            'El pago no se completó. Las horas de este intento se liberaron; los productos del carrito se conservaron.',
        )
        return redirect('cliente_carrito')

    return _render_estado_transbank(
        request,
        'No pudimos verificar el pago',
        'No vuelvas a pagar todavía. Transbank aún no confirma el resultado; inténtalo más tarde o contacta al salón.',
    )


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def retorno_transbank(request):
    referencia = request.GET.get('ref', '')
    try:
        datos_referencia = _cargar_referencia_transbank(
            referencia,
            'carrito.transbank.return',
        )
    except signing.BadSignature:
        messages.info(
            request,
            'La referencia de pago venció o ya no está vigente. Puedes iniciar un nuevo pago desde tu carrito.',
        )
        return redirect('cliente_carrito')
    intento = get_object_or_404(
        TransbankPago.objects.select_related('cliente', 'pedido'),
        pk=datos_referencia.get('attempt'),
    )
    datos_retorno = request.POST if request.method == 'POST' else request.GET
    token = datos_retorno.get('token_ws', '')
    token_anulado = datos_retorno.get('TBK_TOKEN', '')

    if intento.estado == 'aprobado' and intento.pedido_id:
        return redirect(_url_resultado_transbank(intento))
    if token_anulado:
        if (
            not intento.token
            or not compare_digest(intento.token, token_anulado)
            or datos_retorno.get('TBK_ORDEN_COMPRA') != intento.buy_order
            or datos_retorno.get('TBK_ID_SESION') != intento.session_id
        ):
            return HttpResponseBadRequest('Referencia de pago inválida.')
        intento.estado = 'anulado'
        intento.save(update_fields=['estado', 'actualizado_en'])
        _liberar_citas_intento_transbank(request, intento)
        return _render_estado_transbank(
            request,
            'Pago cancelado',
            'No se realizó ningún cobro y las horas reservadas se liberaron. Puedes volver a agendar desde Servicios.',
        )
    if not token or not intento.token or not compare_digest(intento.token, token):
        return HttpResponseBadRequest('Token de pago inválido.')
    if intento.estado not in ('pendiente', 'webpay_abierto', 'autorizado'):
        return _render_estado_transbank(
            request,
            'Pago no disponible',
            'Este intento de pago ya no está vigente. Revisa tu carrito para iniciar otro.',
        )

    try:
        gateway = get_transaction()
        if intento.estado == 'autorizado':
            respuesta = transaction_status(gateway, token)
        else:
            try:
                respuesta = commit_transaction(gateway, token)
            except TransbankGatewayError:
                respuesta = transaction_status(gateway, token)
    except (ImproperlyConfigured, TransbankGatewayError):
        logger.exception('No se pudo confirmar el intento Transbank %s.', intento.pk)
        return _render_estado_transbank(
            request,
            'No pudimos confirmar el pago',
            'No vuelvas a pagar todavía. Revisa tu cuenta o comunícate con el salón para confirmar el estado.',
        )

    autorizado = (
        respuesta.get('status') == 'AUTHORIZED'
        and str(respuesta.get('response_code')) == '0'
    )
    if not autorizado:
        intento.estado = 'rechazado'
        intento.save(update_fields=['estado', 'actualizado_en'])
        _liberar_citas_intento_transbank(request, intento)
        return _render_estado_transbank(
            request,
            'Pago no aprobado',
            'Transbank no aprobó el pago. No se registró la compra y las horas reservadas se liberaron.',
        )

    try:
        monto_confirmado = Decimal(str(respuesta['amount']))
    except (KeyError, TypeError, ValueError):
        monto_confirmado = Decimal('-1')
    respuesta_coincide = (
        respuesta.get('buy_order') == intento.buy_order
        and respuesta.get('session_id') == intento.session_id
        and monto_confirmado == intento.monto
    )
    if not respuesta_coincide:
        reembolsado = _reembolsar_transbank(intento, gateway, monto_confirmado if monto_confirmado > 0 else intento.monto)
        _liberar_citas_intento_transbank(request, intento)
        mensaje = (
            'La compra no se registró y Transbank confirmó la devolución.'
            if reembolsado
            else 'La compra no se registró. No vuelvas a pagar y comunícate con el salón para revisar el reembolso.'
        )
        return _render_estado_transbank(request, 'No pudimos validar la compra', mensaje)

    with transaction.atomic():
        intento = TransbankPago.objects.select_for_update().get(pk=intento.pk)
        if intento.estado == 'aprobado' and intento.pedido_id:
            return redirect(_url_resultado_transbank(intento))
        if intento.estado not in ('pendiente', 'webpay_abierto', 'autorizado'):
            return _render_estado_transbank(
                request,
                'Pago no disponible',
                'Este intento de pago ya no está vigente. Revisa tu carrito para iniciar otro.',
            )
        intento.estado = 'autorizado'
        intento.transaccion_id = intento.buy_order
        intento.codigo_autorizacion = str(respuesta.get('authorization_code', ''))[:12]
        intento.save(update_fields=[
            'estado',
            'transaccion_id',
            'codigo_autorizacion',
            'actualizado_en',
        ])
    request.user = intento.cliente
    try:
        _procesar_pago_carrito(
            request,
            carrito_override=intento.carrito,
            session_key_override=intento.session_key,
            transbank_pago=intento,
        )
    except DatabaseError:
        logger.exception('No se pudo registrar la compra del intento Transbank %s.', intento.pk)
        reembolsado = _reembolsar_transbank(intento, gateway, intento.monto)
        _liberar_citas_intento_transbank(request, intento)
        mensaje = (
            'La compra no se registró y Transbank confirmó la devolución.'
            if reembolsado
            else 'La compra no se registró. No vuelvas a pagar y comunícate con el salón para revisar el reembolso.'
        )
        return _render_estado_transbank(request, 'No pudimos completar la compra', mensaje)

    intento.refresh_from_db()
    if intento.pedido_id:
        return redirect(_url_resultado_transbank(intento))

    reembolsado = _reembolsar_transbank(intento, gateway, intento.monto)
    _liberar_citas_intento_transbank(request, intento)
    mensaje = (
        'El pago fue devuelto porque el stock o el horario cambió antes de completar la compra.'
        if reembolsado
        else 'No se completó la compra. No vuelvas a pagar y comunícate con el salón para revisar el reembolso.'
    )
    return _render_estado_transbank(request, 'Compra no completada', mensaje)


def resultado_compra(request, pk):
    if request.user.is_authenticated and request.user.pk:
        pedidos = Pedido.objects.filter(cliente=request.user)
    else:
        pedidos = Pedido.objects.none()
    pedido = pedidos.filter(pk=pk).first()
    if pedido is None:
        try:
            datos = signing.loads(
                request.GET.get('ref', ''),
                salt='carrito.transbank.result',
                max_age=60 * 15,
            )
        except signing.BadSignature:
            return redirect('login')
        pedido = get_object_or_404(
            Pedido.objects.filter(
                pk=pk,
                pago_transbank__pk=datos.get('attempt'),
                pago_transbank__estado='aprobado',
            ),
        )
    pedido = get_object_or_404(
        Pedido.objects.filter(pk=pedido.pk).select_related('pago_transbank').prefetch_related(
            'detalles__reserva',
            'pagos_simulados',
        ),
    )
    resumen, total_resumen = resumen_carrito(request)
    return render(
        request,
        'usuarios/cliente_compra_resultado.html',
        {
            'pedido': pedido,
            'tiene_citas': pedido.detalles.filter(tipo='servicio').exists(),
            'resumen_carrito': resumen,
            'total_resumen_carrito': total_resumen,
            'cantidad_articulos_carrito': sum(item['cantidad'] for item in resumen),
        },
    )
