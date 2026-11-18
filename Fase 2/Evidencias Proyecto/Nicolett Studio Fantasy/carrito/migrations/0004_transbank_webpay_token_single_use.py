from django.db import migrations, models


def marcar_tokens_previos_como_abiertos(apps, schema_editor):
    transbank_pago = apps.get_model('carrito', 'TransbankPago')
    transbank_pago.objects.filter(
        estado='pendiente',
        token__isnull=False,
    ).exclude(token='').update(estado='webpay_abierto')


def restaurar_tokens_abiertos(apps, schema_editor):
    transbank_pago = apps.get_model('carrito', 'TransbankPago')
    transbank_pago.objects.filter(estado='webpay_abierto').update(
        estado='pendiente',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('carrito', '0003_transbankpago'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transbankpago',
            name='estado',
            field=models.CharField(
                choices=[
                    ('iniciando', 'Iniciando'),
                    ('pendiente', 'Pendiente'),
                    ('webpay_abierto', 'Abierto en Webpay'),
                    ('autorizado', 'Autorizado'),
                    ('aprobado', 'Aprobado'),
                    ('rechazado', 'Rechazado'),
                    ('anulado', 'Anulado'),
                    ('reembolsado', 'Reembolsado'),
                    ('error', 'Error'),
                    ('reembolso_pendiente', 'Reembolso pendiente'),
                ],
                default='iniciando',
                max_length=24,
            ),
        ),
        migrations.RunPython(
            marcar_tokens_previos_como_abiertos,
            restaurar_tokens_abiertos,
        ),
    ]
