import textwrap
from datetime import datetime, timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test

from agenda.models import HistorialReserva, Reserva
from usuarios.models import Usuario
from usuarios.permissions import es_administrador, es_cliente


def _pdf_literal(texto):
    contenido = texto.encode('cp1252', errors='replace')
    escapado = bytearray(b'(')
    for byte in contenido:
        if byte in (ord('\\'), ord('('), ord(')')):
            escapado.extend(b'\\' + bytes([byte]))
        elif byte < 32 or byte > 126:
            escapado.extend(f'\\{byte:03o}'.encode('ascii'))
        else:
            escapado.append(byte)
    escapado.extend(b')')
    return bytes(escapado)


def _crear_pdf(lineas):
    paginas = [lineas[indice:indice + 48] for indice in range(0, len(lineas), 48)]
    if not paginas:
        paginas = [[]]

    objetos = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        3: b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    }
    referencias_paginas = []
    siguiente_objeto = 4
    for lineas_pagina in paginas:
        id_pagina = siguiente_objeto
        id_contenido = siguiente_objeto + 1
        siguiente_objeto += 2
        referencias_paginas.append(f'{id_pagina} 0 R')

        comandos = [b'BT', b'/F1 10 Tf', b'50 750 Td', b'14 TL']
        for linea in lineas_pagina:
            comandos.extend((_pdf_literal(linea), b'Tj', b'T*'))
        comandos.append(b'ET')
        contenido = b'\n'.join(comandos)
        objetos[id_pagina] = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            f'/Resources << /Font << /F1 3 0 R >> >> /Contents {id_contenido} 0 R >>'
        ).encode('ascii')
        objetos[id_contenido] = (
            f'<< /Length {len(contenido)} >>\nstream\n'.encode('ascii')
            + contenido
            + b'\nendstream'
        )

    objetos[2] = (
        f'<< /Type /Pages /Kids [{" ".join(referencias_paginas)}] '
        f'/Count {len(paginas)} >>'
    ).encode('ascii')

    documento = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0] * (max(objetos) + 1)
    for numero in range(1, max(objetos) + 1):
        offsets[numero] = len(documento)
        documento.extend(f'{numero} 0 obj\n'.encode('ascii'))
        documento.extend(objetos[numero])
        documento.extend(b'\nendobj\n')

    inicio_xref = len(documento)
    documento.extend(f'xref\n0 {len(offsets)}\n'.encode('ascii'))
    documento.extend(b'0000000000 65535 f \n')
    for desplazamiento in offsets[1:]:
        documento.extend(f'{desplazamiento:010} 00000 n \n'.encode('ascii'))
    documento.extend(
        (
            f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n'
            f'startxref\n{inicio_xref}\n%%EOF'
        ).encode('ascii')
    )
    return bytes(documento)


def _crear_pdf_ficha_cliente(datos_cliente, registros):
    ancho_pagina = 612
    alto_pagina = 792
    margen = 50
    paginas = []
    comandos = []
    cursor_y = 0

    def texto(valor, x, y, tamano=9, negrita=False, color=(0.17, 0.14, 0.13)):
        fuente = 'F2' if negrita else 'F1'
        rojo, verde, azul = color
        comandos.extend([
            f'{rojo:.3f} {verde:.3f} {azul:.3f} rg'.encode('ascii'),
            b'BT',
            f'/{fuente} {tamano} Tf'.encode('ascii'),
            f'{x:.2f} {y:.2f} Td'.encode('ascii'),
            _pdf_literal(str(valor)),
            b'Tj',
            b'ET',
        ])

    def rectangulo(x, y, ancho, alto, color):
        rojo, verde, azul = color
        comandos.extend([
            f'{rojo:.3f} {verde:.3f} {azul:.3f} rg'.encode('ascii'),
            f'{x:.2f} {y:.2f} {ancho:.2f} {alto:.2f} re f'.encode('ascii'),
        ])

    def linea(x1, y1, x2, y2, color=(0.91, 0.88, 0.85)):
        rojo, verde, azul = color
        comandos.extend([
            f'{rojo:.3f} {verde:.3f} {azul:.3f} RG'.encode('ascii'),
            f'{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S'.encode('ascii'),
        ])

    def envolver(valor, ancho, tamano=8):
        limite = max(8, int(ancho / (tamano * 0.52)))
        return textwrap.wrap(str(valor or '—'), width=limite) or ['—']

    def nueva_pagina(continuacion=False):
        nonlocal comandos, cursor_y
        if comandos:
            paginas.append(comandos)
        comandos = []
        rectangulo(0, alto_pagina - 50, ancho_pagina, 50, (0.15, 0.13, 0.12))
        rectangulo(0, alto_pagina - 53, ancho_pagina, 3, (0.76, 0.63, 0.56))
        texto('Nicolett Studio Fantasy', margen, alto_pagina - 31, 16, True, (0.98, 0.96, 0.94))
        titulo = 'Ficha técnica del cliente' + (' · continuación' if continuacion else '')
        texto(titulo, (ancho_pagina - len(titulo) * 8.1) / 2, alto_pagina - 83, 15, True)
        cursor_y = alto_pagina - 112

    def encabezado_tabla(titulos, anchos, y):
        alto = 24
        x = margen
        rectangulo(margen, y - alto + 4, sum(anchos), alto, (0.46, 0.34, 0.28))
        for titulo, ancho in zip(titulos, anchos):
            texto(titulo, x + 7, y - 12, 8, True, (1, 1, 1))
            x += ancho
        cursor_y = y - alto
        return cursor_y

    def fila_tabla(valores, anchos, y, indice, font_size=8):
        wrapped = [
            envolver(value, ancho - 12, font_size)
            for value, ancho in zip(valores, anchos)
        ]
        lineas_fila = max(map(len, wrapped))
        alto = max(25, 10 + lineas_fila * 11)
        rectangulo(
            margen,
            y - alto + 4,
            sum(anchos),
            alto,
            (0.99, 0.98, 0.97) if indice % 2 == 0 else (1, 1, 1),
        )
        x = margen
        for lineas_celda, ancho in zip(wrapped, anchos):
            for numero, linea_celda in enumerate(lineas_celda):
                texto(linea_celda, x + 7, y - 10 - numero * 11, font_size)
            x += ancho
            linea(x, y - alto + 4, x, y + 4)
        linea(margen, y - alto + 4, margen + sum(anchos), y - alto + 4)
        return y - alto

    nueva_pagina()
    texto('Datos del cliente', margen, cursor_y, 10, True, (0.46, 0.34, 0.28))
    cursor_y -= 14
    anchos_personales = [120, 392]
    cursor_y = encabezado_tabla(['Dato', 'Información'], anchos_personales, cursor_y)
    for indice, (etiqueta, valor) in enumerate(datos_cliente):
        cursor_y = fila_tabla([etiqueta, valor], anchos_personales, cursor_y, indice)

    cursor_y -= 20
    texto('Historial de citas', margen, cursor_y, 10, True, (0.46, 0.34, 0.28))
    cursor_y -= 14
    anchos_citas = [80, 142, 126, 104, 60]
    titulos_citas = ['Fecha y hora', 'Servicio', 'Profesional', 'Estado', 'Duración']
    cursor_y = encabezado_tabla(titulos_citas, anchos_citas, cursor_y)
    if not registros:
        cursor_y = fila_tabla(
            ['—', 'No hay citas registradas.', '—', '—', '—'],
            anchos_citas,
            cursor_y,
            0,
        )
    for indice, registro in enumerate(registros):
        alto_estimado = max(
            len(envolver(valor, ancho - 12, 8))
            for valor, ancho in zip(registro, anchos_citas)
        ) * 11 + 10
        if cursor_y - alto_estimado < 58:
            nueva_pagina(continuacion=True)
            cursor_y = encabezado_tabla(titulos_citas, anchos_citas, cursor_y)
        cursor_y = fila_tabla(registro, anchos_citas, cursor_y, indice)

    paginas.append(comandos)
    total_paginas = len(paginas)
    for numero, pagina in enumerate(paginas, start=1):
        page_commands = pagina
        page_commands.extend([
            b'0.91 0.88 0.85 RG',
            b'50 43 m 562 43 l S',
        ])
        pie = f'Página {numero} de {total_paginas}'
        page_commands.extend([
            b'0.40 0.34 0.31 rg',
            b'BT',
            b'/F1 8 Tf',
            f'{(ancho_pagina - len(pie) * 4.1) / 2:.2f} 27 Td'.encode('ascii'),
            _pdf_literal(pie),
            b'Tj',
            b'ET',
        ])

    objetos = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        3: b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
        4: b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>',
    }
    referencias_paginas = []
    siguiente_objeto = 5
    for pagina in paginas:
        id_pagina = siguiente_objeto
        id_contenido = siguiente_objeto + 1
        siguiente_objeto += 2
        referencias_paginas.append(f'{id_pagina} 0 R')
        contenido = b'\n'.join(pagina)
        objetos[id_pagina] = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            f'/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> '
            f'/Contents {id_contenido} 0 R >>'
        ).encode('ascii')
        objetos[id_contenido] = (
            f'<< /Length {len(contenido)} >>\nstream\n'.encode('ascii')
            + contenido
            + b'\nendstream'
        )
    objetos[2] = (
        f'<< /Type /Pages /Kids [{" ".join(referencias_paginas)}] '
        f'/Count {len(paginas)} >>'
    ).encode('ascii')

    documento = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0] * (max(objetos) + 1)
    for numero in range(1, max(objetos) + 1):
        offsets[numero] = len(documento)
        documento.extend(f'{numero} 0 obj\n'.encode('ascii'))
        documento.extend(objetos[numero])
        documento.extend(b'\nendobj\n')
    inicio_xref = len(documento)
    documento.extend(f'xref\n0 {len(offsets)}\n'.encode('ascii'))
    documento.extend(b'0000000000 65535 f \n')
    for desplazamiento in offsets[1:]:
        documento.extend(f'{desplazamiento:010} 00000 n \n'.encode('ascii'))
    documento.extend(
        (
            f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n'
            f'startxref\n{inicio_xref}\n%%EOF'
        ).encode('ascii')
    )
    return bytes(documento)


def _respuesta_ficha_tecnica_cliente(cliente):
    reservas = list(
        Reserva.objects.filter(cliente=cliente).select_related(
            'servicio',
            'profesional',
        ).order_by('-fecha_hora')
    )
    eventos = HistorialReserva.objects.filter(
        reserva__cliente=cliente,
    ).select_related('reserva').order_by('-registrado_en')
    ahora = timezone.now()
    registros = []
    for reserva in reservas:
        fecha = timezone.localtime(reserva.fecha_hora)
        profesional = reserva.profesional
        nombre_profesional = ' '.join(part for part in (
            profesional.nombre,
            profesional.segundo_nombre,
            profesional.apellido_paterno,
            profesional.apellido_materno,
        ) if part) if profesional else 'Sin asignar'
        servicio = reserva.servicio_nombre or (
            reserva.servicio.nombre if reserva.servicio_id else 'Servicio no disponible'
        )
        if reserva.estado == 'cancelada':
            estado = 'Cancelado'
        elif reserva.estado == 'completada':
            estado = 'Finalizado'
        elif reserva.estado == 'suspendida':
            estado = 'Modificado'
        elif reserva.fecha_hora <= ahora < reserva.fecha_hora + timedelta(minutes=reserva.duracion_minutos):
            estado = 'En curso'
        else:
            estado = 'Solicitado'
        registros.append(
            (
                fecha.strftime('%d/%m/%Y %H:%M'),
                servicio,
                nombre_profesional,
                estado,
                f'{reserva.duracion_minutos} min',
            )
        )
    for evento in eventos:
        fecha = timezone.localtime(evento.fecha_hora)
        registros.append(
            (
                fecha.strftime('%d/%m/%Y %H:%M'),
                evento.servicio_nombre or 'Servicio no disponible',
                evento.profesional_nombre or 'Sin asignar',
                'Modificado' if evento.evento == 'modificada' else 'Cancelado',
                '—',
            )
        )
    registros.sort(key=lambda fila: datetime.strptime(fila[0], '%d/%m/%Y %H:%M'), reverse=True)

    respuesta = HttpResponse(
        _crear_pdf_ficha_cliente(
            [
                (
                    'Nombres',
                    ' '.join(part for part in (cliente.nombre, cliente.segundo_nombre) if part) or '—',
                ),
                (
                    'Apellidos',
                    ' '.join(part for part in (cliente.apellido_paterno, cliente.apellido_materno) if part) or '—',
                ),
                ('Correo electrónico', cliente.email),
                ('Teléfono de contacto', cliente.telefono or '—'),
            ],
            registros,
        ),
        content_type='application/pdf',
    )
    respuesta['Content-Disposition'] = (
        f'inline; filename="ficha-tecnica-cliente-{cliente.pk}.pdf"'
    )
    return respuesta


@login_required(login_url='login')
@user_passes_test(es_administrador, login_url='login')
def ficha_tecnica_pdf(request, cliente_id):
    cliente = get_object_or_404(
        Usuario,
        pk=cliente_id,
        rol__nombre__iexact='Cliente',
    )
    return _respuesta_ficha_tecnica_cliente(cliente)


@login_required(login_url='login')
@user_passes_test(es_cliente, login_url='login')
def ficha_tecnica_cliente_pdf(request):
    respuesta = _respuesta_ficha_tecnica_cliente(request.user)
    respuesta['Content-Disposition'] = 'inline; filename="ficha-tecnica-mis-citas.pdf"'
    return respuesta
