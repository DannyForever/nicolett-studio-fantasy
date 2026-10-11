from django.core.management.base import BaseCommand, CommandError

from notificaciones.recordatorios import enviar_recordatorios_vencidos


class Command(BaseCommand):
    help = 'Envía por correo los recordatorios que han alcanzado su hora programada.'

    def handle(self, *args, **options):
        enviados, fallidos = enviar_recordatorios_vencidos()
        self.stdout.write(f'Recordatorios enviados: {enviados}.')
        if fallidos:
            raise CommandError(
                f'No se pudieron enviar {fallidos} recordatorios. Revisa los logs del servidor.',
            )
