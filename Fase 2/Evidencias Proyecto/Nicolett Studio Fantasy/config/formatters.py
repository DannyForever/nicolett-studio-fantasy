from decimal import Decimal


def formatear_miles_clp(valor):
    return format(Decimal(str(valor)), ',.0f').replace(',', '.')


def formatear_pesos(valor):
    return f'${formatear_miles_clp(valor)}'
