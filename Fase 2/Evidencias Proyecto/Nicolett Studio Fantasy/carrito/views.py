from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from agenda.models import DiaCerrado, Disponibilidad, Reserva
from agenda.views import horas_disponibles
from panel_admin.models import Producto, Servicio
from usuarios.permissions import es_cliente

from .models import (
    DetallePedido,
    PagoSimulado,
    Pedido,
    ReservaProductoCarrito,
)


CLAVE_CARRITO = 'carrito_compra'
ABONO_SERVICIO = Decimal('5000.00')
RESERVA_PRODUCTO_MINUTOS = 30


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
    for item in carrito['servicios']:
        if not isinstance(item, dict) or not str(item.get('id', '')).isdecimal():
            continue
        servicio = servicios.get(int(item['id']))
        if servicio is None:
            continue
        resumen.append({
            'tipo': 'servicio',
            'id': servicio.pk,
            'key': item.get('key', ''),
            'nombre': servicio.nombre,
            'cantidad': 1,
            'precio': servicio.precio,
            'subtotal': servicio.precio,
            'url': reverse('cliente_carrito_actualizar'),
            'agregar_url': reverse('cliente_carrito_agregar_servicio', args=[servicio.pk]),
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


def _session_key(request):
    if request.session.session_key is None:
        request.session.create()
    return request.session.session_key


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
    session_key = request.session.session_key
    ahora = timezone.now()
    reservas = {
        reserva.producto_id: reserva
        for reserva in ReservaProductoCarrito.objects.filter(
            session_key=session_key,
            vence_en__gt=ahora,
        )
    } if session_key else {}
    if reservas:
        ReservaProductoCarrito.objects.filter(
            session_key=session_key,
            vence_en__gt=ahora,
        ).update(vence_en=ahora_reserva_productos())
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
    total_pagar = total_productos
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
        servicios.append({
            'key': item.get('key', ''),
            'id': servicio.pk,
            'nombre': servicio.nombre,
            'precio': precio,
            'duracion': servicio.duracion_minutos,
            'fecha': item.get('fecha', ''),
            'profesional_id': item.get('profesional', ''),
            'hora': item.get('hora', ''),
            'pago': modalidad,
            'monto_pagar': monto_pagar,
            'saldo': precio - monto_pagar,
            'cita_completa': cita_completa,
            'disponible': True,
        })
        total_servicios += precio
        if cita_completa and modalidad in ('completo', 'abono'):
            total_pagar += monto_pagar
        else:
            puede_pagar = False

    resumen, total_resumen = resumen_carrito(request)
    return render(request, 'usuarios/cliente_carrito.html', {
        'productos': productos,
        'servicios': servicios,
        'total_productos': total_productos,
        'total_servicios': total_servicios,
        'total_pedido': total_productos + total_servicios,
        'total_pagar': total_pagar,
        'saldo_pendiente': total_productos + total_servicios - total_pagar,
        'cantidad_articulos_carrito': cantidad_articulos(request),
        'puede_pagar': puede_pagar and bool(productos or servicios),
        'resumen_carrito': resumen,
        'total_resumen_carrito': total_resumen,
        'hoy': timezone.localdate().isoformat(),
        'profesionales_url': reverse('cliente_profesionales_disponibles'),
        'horas_url': reverse('cliente_horas_disponibles'),
    })


@_cliente_view
@require_POST
def agregar_producto(request, pk):
    _liberar_reservas_vencidas(request)
    try:
        cantidad = int(request.POST.get('cantidad', '1'))
    except (TypeError, ValueError):
        messages.error(request, 'Indica una cantidad válida.')
        return redirect('cliente_productos')
    if cantidad < 1:
        messages.error(request, 'La cantidad indicada no es válida.')
        return redirect('cliente_productos')

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
            return redirect('cliente_productos')
        producto, reservada = _ajustar_reserva_producto(
            session_key,
            pk,
            nueva_cantidad,
        )
        if not reservada:
            messages.error(request, 'No hay stock disponible para esa cantidad.')
            return redirect('cliente_productos')
    carrito['productos'][clave] = nueva_cantidad
    _guardar_carrito(request, carrito)
    messages.success(
        request,
        f'{producto.nombre} se añadió y quedó reservado por '
        f'{RESERVA_PRODUCTO_MINUTOS} minutos.',
    )
    return redirect('cliente_productos')


@_cliente_view
@require_POST
def agregar_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk, activo=True)
    carrito = _carrito_sesion(request)
    carrito['servicios'].append({
        'key': str(uuid4()),
        'id': servicio.pk,
        'pago': '',
    })
    _guardar_carrito(request, carrito)
    messages.success(request, f'{servicio.nombre} se añadió. Completa su cita desde el carrito antes de pagar.')
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
            messages.success(request, 'Producto eliminado y stock devuelto.')
        else:
            carrito['productos'][clave] = cantidad
            messages.success(request, 'Cantidad actualizada y stock reservado.')
    elif tipo == 'servicio':
        carrito['servicios'] = [
            item for item in carrito['servicios']
            if item.get('key') != clave
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
    carrito = _carrito_sesion(request)
    item = next((linea for linea in carrito['servicios'] if linea.get('key') == key), None)
    if item is None:
        messages.error(request, 'No se encontró el servicio en tu carrito.')
        return redirect('cliente_carrito')
    try:
        fecha = date.fromisoformat(request.POST.get('fecha', ''))
        hora = time.fromisoformat(request.POST.get('hora', ''))
        profesional_id = request.POST.get('profesional', '')
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
        messages.error(request, 'Completa el servicio, fecha, profesional, hora y modalidad de pago.')
        return redirect('cliente_carrito')

    if fecha < timezone.localdate() or DiaCerrado.objects.filter(fecha=fecha).exists():
        messages.error(request, 'No se puede agendar en una fecha pasada o con el salón cerrado.')
        return redirect('cliente_carrito')
    profesional_valido = servicio.categoria_id and _profesional_valido(
        profesional_id,
        servicio.categoria_id,
    )
    if not profesional_valido:
        messages.error(request, 'El profesional seleccionado no está habilitado para este servicio.')
        return redirect('cliente_carrito')
    if hora.strftime('%H:%M') not in horas_disponibles(
        fecha,
        servicio,
        profesional_id=int(profesional_id),
    ):
        messages.error(request, 'Ese horario ya no está disponible.')
        return redirect('cliente_carrito')

    item.update({
        'fecha': fecha.isoformat(),
        'profesional': str(profesional_id),
        'hora': hora.strftime('%H:%M'),
        'pago': pago,
    })
    _guardar_carrito(request, carrito)
    messages.success(request, f'Cita de {servicio.nombre} agregada a tu carrito.')
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


@_cliente_view
@require_POST
def pagar_carrito(request):
    _liberar_reservas_vencidas(request)
    carrito = _carrito_sesion(request)
    if not carrito['productos'] and not carrito['servicios']:
        messages.error(request, 'Tu carrito está vacío.')
        return redirect('cliente_carrito')
    session_key = request.session.session_key

    with transaction.atomic():
        from usuarios.models import Usuario

        cliente = Usuario.objects.select_for_update().get(pk=request.user.pk)
        productos = []
        total_productos = Decimal('0')
        for product_id, quantity in carrito['productos'].items():
            if not str(product_id).isdecimal() or not isinstance(quantity, int) or quantity < 1:
                messages.error(request, 'Hay una cantidad inválida en tu carrito.')
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
                messages.error(request, 'Un producto ya no está disponible o no tiene stock suficiente.')
                return redirect('cliente_carrito')
            productos.append((producto, quantity))
            total_productos += producto.precio * quantity

        servicios = []
        total_servicios = Decimal('0')
        total_pagar = total_productos
        for item in carrito['servicios']:
            if not isinstance(item, dict):
                messages.error(request, 'Hay un servicio inválido en tu carrito.')
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
                messages.error(request, 'Completa la fecha, el profesional, la hora y el pago de cada servicio antes de pagar.')
                return redirect('cliente_carrito')
            if fecha < timezone.localdate() or DiaCerrado.objects.filter(fecha=fecha).exists():
                messages.error(request, 'Una cita tiene fecha pasada o el salón está cerrado ese día.')
                return redirect('cliente_carrito')
            if not _profesional_valido(profesional_id, servicio.categoria_id):
                messages.error(request, 'Un profesional no está habilitado para el servicio seleccionado.')
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
            ):
                messages.error(request, 'Uno de los horarios seleccionados ya no está disponible.')
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
            messages.error(request, 'No hay artículos válidos para pagar.')
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
                    messages.error(request, 'Una de las citas se cruza con otra reserva tuya o del profesional.')
                    return redirect('cliente_carrito')
            for otra_fecha, otro_inicio, otro_fin in citas_del_pedido:
                if (
                    fecha == otra_fecha
                    and fecha_hora < otro_fin
                    and otro_inicio < fin
                ):
                    messages.error(request, 'Las citas de tu carrito no pueden quedar superpuestas.')
                    return redirect('cliente_carrito')
            citas_del_pedido.append((fecha, fecha_hora, fin))

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
            ):
                messages.error(request, 'El horario de una cita acaba de ser ocupado. Revisa el carrito e intenta otra vez.')
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

        PagoSimulado.objects.create(
            pedido=pedido,
            monto=total_pagar,
            transaccion_id=str(uuid4()),
        )

    request.session.pop(CLAVE_CARRITO, None)
    request.session.modified = True
    return redirect('cliente_compra_resultado', pk=pedido.pk)


@_cliente_view
def resultado_compra(request, pk):
    pedido = get_object_or_404(
        Pedido.objects.filter(cliente=request.user).prefetch_related(
            'detalles__reserva',
            'pagos_simulados',
        ),
        pk=pk,
    )
    return render(request, 'usuarios/cliente_compra_resultado.html', {'pedido': pedido})
