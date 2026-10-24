import re
import unicodedata

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError


DOMINIO_ACCESO = 'nicolettstudio.cl'


def _normalizar_usuario(valor):
    normalizado = unicodedata.normalize('NFKD', valor)
    ascii_texto = normalizado.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '', ascii_texto.casefold())


def sugerir_usuario_acceso(nombre, apellido_paterno, apellido_materno):
    primer_nombre = _normalizar_usuario((nombre or '').strip().split(' ')[0])
    primer_apellido = _normalizar_usuario((apellido_paterno or '').strip().split(' ')[0])
    segundo_apellido = _normalizar_usuario((apellido_materno or '').strip())
    if not primer_nombre or not primer_apellido or not segundo_apellido:
        return ''
    return f'{primer_nombre[0]}{primer_apellido[0]}.{segundo_apellido}'


def correo_acceso_disponible(usuario_local, excluir_pk=None):
    User = get_user_model()
    base = (usuario_local or '').strip().casefold()
    numero = 1
    while True:
        sufijo = '' if numero == 1 else str(numero)
        correo = f'{base}{sufijo}@{DOMINIO_ACCESO}'
        usuarios = User.objects.filter(email__iexact=correo)
        if excluir_pk is not None:
            usuarios = usuarios.exclude(pk=excluir_pk)
        if not usuarios.exists():
            return correo
        numero += 1


def generar_correo_acceso(nombre, apellido_paterno, apellido_materno, excluir_pk=None):
    usuario_local = sugerir_usuario_acceso(nombre, apellido_paterno, apellido_materno)
    if not usuario_local:
        return ''
    return correo_acceso_disponible(usuario_local, excluir_pk=excluir_pk)


def normalizar_correo_acceso(
    valor,
    nombre,
    apellido_paterno,
    apellido_materno,
    excluir_pk=None,
):
    entrada = (valor or '').strip().casefold()
    if not entrada:
        sugerencia = sugerir_usuario_acceso(nombre, apellido_paterno, apellido_materno)
        if not sugerencia:
            raise ValidationError('Completa el nombre y ambos apellidos para generar el acceso.')
        return correo_acceso_disponible(sugerencia, excluir_pk=excluir_pk)

    if '@' in entrada:
        usuario_local, dominio = entrada.rsplit('@', 1)
        if dominio != DOMINIO_ACCESO:
            raise ValidationError(f'El correo de acceso debe terminar en @{DOMINIO_ACCESO}.')
    else:
        usuario_local = entrada

    if not re.fullmatch(r'[a-z0-9]+(?:[._+-][a-z0-9]+)*', usuario_local):
        raise ValidationError('Usa letras sin tildes, números y separadores simples en el usuario.')

    correo = f'{usuario_local}@{DOMINIO_ACCESO}'
    User = get_user_model()
    usuarios = User.objects.filter(email__iexact=correo)
    if excluir_pk is not None:
        usuarios = usuarios.exclude(pk=excluir_pk)
    if usuarios.exists():
        raise ValidationError('Ya existe una cuenta con este correo de acceso.')
    return correo
