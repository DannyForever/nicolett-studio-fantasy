from django import template

from config.formatters import formatear_miles_clp, formatear_pesos


register = template.Library()


@register.filter
def pesos(valor):
    return formatear_pesos(valor)


@register.filter
def miles_clp(valor):
    return formatear_miles_clp(valor)
