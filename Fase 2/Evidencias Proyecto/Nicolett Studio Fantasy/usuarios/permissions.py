def es_administrador(usuario):
    if not usuario.is_authenticated:
        return False
    rol = getattr(usuario, 'rol', None)
    return usuario.is_superuser or (
        rol is not None and rol.nombre.casefold() == 'admin'
    )


def es_cliente(usuario):
    if not usuario.is_authenticated:
        return False
    rol = getattr(usuario, 'rol', None)
    return (
        not es_administrador(usuario)
        and rol is not None
        and rol.nombre.casefold() == 'cliente'
    )
