from django.db import migrations, models


def guardar_fecha_cita_en_envios_existentes(apps, schema_editor):
    RecordatorioEnviado = apps.get_model('notificaciones', 'RecordatorioEnviado')
    Reserva = apps.get_model('agenda', 'Reserva')
    alias = schema_editor.connection.alias
    envios = RecordatorioEnviado.objects.using(alias).filter(
        tipo='cita',
        fecha_hora_cita__isnull=True,
    )
    for envio in envios.iterator():
        fecha_hora = Reserva.objects.using(alias).filter(
            pk=envio.reserva_id,
        ).values_list('fecha_hora', flat=True).first()
        if fecha_hora is not None:
            envio.fecha_hora_cita = fecha_hora
            envio.save(using=alias, update_fields=['fecha_hora_cita'])


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0003_remove_recordatorioenviado_uniq_recordatorio_reserva_tipo_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='recordatorioenviado',
            name='fecha_hora_cita',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(
            guardar_fecha_cita_en_envios_existentes,
            migrations.RunPython.noop,
        ),
    ]
