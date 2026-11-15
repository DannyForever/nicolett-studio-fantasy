import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from transbank.common.integration_api_keys import IntegrationApiKeys
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes
from transbank.error.transbank_error import TransbankError
from transbank.webpay.webpay_plus.transaction import Transaction


class TransbankGatewayError(Exception):
    pass


def get_transaction():
    environment = settings.TRANSBANK_ENVIRONMENT
    if environment == 'INTEGRATION':
        transaction = Transaction.build_for_integration(
            IntegrationCommerceCodes.WEBPAY_PLUS,
            IntegrationApiKeys.WEBPAY,
        )
    elif environment == 'PRODUCTION':
        if not settings.TRANSBANK_COMMERCE_CODE or not settings.TRANSBANK_API_KEY:
            raise ImproperlyConfigured(
                'Transbank production requires TRANSBANK_COMMERCE_CODE and TRANSBANK_API_KEY.'
            )
        transaction = Transaction.build_for_production(
            settings.TRANSBANK_COMMERCE_CODE,
            settings.TRANSBANK_API_KEY,
        )
    else:
        raise ImproperlyConfigured('TRANSBANK_ENVIRONMENT must be INTEGRATION or PRODUCTION.')

    transaction.options.timeout = 30
    return transaction


def create_transaction(transaction, buy_order, session_id, amount, return_url):
    try:
        return transaction.create(buy_order, session_id, amount, return_url)
    except (TransbankError, requests.RequestException) as error:
        raise TransbankGatewayError('No se pudo iniciar el pago en Transbank.') from error


def commit_transaction(transaction, token):
    try:
        return transaction.commit(token)
    except (TransbankError, requests.RequestException) as error:
        raise TransbankGatewayError('No se pudo confirmar el pago en Transbank.') from error


def transaction_status(transaction, token):
    try:
        return transaction.status(token)
    except (TransbankError, requests.RequestException) as error:
        raise TransbankGatewayError('No se pudo consultar el estado del pago en Transbank.') from error


def refund_transaction(transaction, token, amount):
    try:
        return transaction.refund(token, amount)
    except (TransbankError, requests.RequestException) as error:
        raise TransbankGatewayError('No se pudo solicitar la devolución en Transbank.') from error
