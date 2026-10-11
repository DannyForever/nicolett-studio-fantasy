from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from agenda.models import Disponibilidad, ProfesionalCategoria
from panel_admin.models import Categoria, Producto, Servicio
from usuarios.models import Rol, Usuario


class Command(BaseCommand):
    help = 'Crea servicios, productos, personal y horarios ficticios para probar la agenda.'

    @transaction.atomic
    def handle(self, *args, **options):
        rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
        categorias = {
            'unas': Categoria.objects.get_or_create(
                nombre='Uñas',
                tipo='Manicure y pedicure',
                defaults={'activa': True},
            )[0],
            'facial': Categoria.objects.get_or_create(
                nombre='Cuidado facial',
                tipo='Tratamientos faciales',
                defaults={'activa': True},
            )[0],
            'pestanas': Categoria.objects.get_or_create(
                nombre='Pestañas',
                tipo='Mirada',
                defaults={'activa': True},
            )[0],
        }

        servicios_data = (
            ('Manicure clásica de prueba', 'unas', 'Manicure tradicional para pruebas de agenda.', '15000.00', 60),
            ('Limpieza facial de prueba', 'facial', 'Limpieza e hidratación facial de demostración.', '28000.00', 75),
            ('Lifting de pestañas de prueba', 'pestanas', 'Lifting para probar la reserva de horas.', '22000.00', 60),
        )
        servicios = {}
        for nombre, categoria_key, descripcion, precio, duracion in servicios_data:
            servicio, _ = Servicio.objects.get_or_create(
                nombre=nombre,
                categoria=categorias[categoria_key],
                defaults={
                    'descripcion': descripcion,
                    'precio': Decimal(precio),
                    'duracion_minutos': duracion,
                    'activo': True,
                },
            )
            servicios[categoria_key] = servicio

        productos_data = (
            ('Aceite nutritivo de prueba', 'unas', 'Producto de demostración para cuidado de cutículas.', '4990.00', 12),
            ('Sérum facial de prueba', 'facial', 'Producto de demostración para hidratación diaria.', '8990.00', 8),
            ('Sérum de pestañas de prueba', 'pestanas', 'Producto de demostración para cuidado de pestañas.', '7990.00', 10),
        )
        for nombre, categoria_key, descripcion, precio, stock in productos_data:
            Producto.objects.get_or_create(
                nombre=nombre,
                categoria=categorias[categoria_key],
                defaults={
                    'descripcion': descripcion,
                    'precio': Decimal(precio),
                    'stock': stock,
                    'activo': True,
                },
            )

        profesionales = {}
        for indice, categoria_key in enumerate(('unas', 'facial', 'pestanas'), start=1):
            email = f'demo.profesional{indice}@example.com'
            profesional, creado = Usuario.objects.get_or_create(
                email=email,
                defaults={
                    'nombre': f'Profesional Demo {indice}',
                    'segundo_nombre': '',
                    'apellido_paterno': 'Prueba',
                    'apellido_materno': 'Salón',
                    'telefono': f'+5690000000{indice}',
                    'rol': rol_colaborador,
                    'is_active': True,
                    'is_staff': True,
                    'is_superuser': False,
                },
            )
            if profesional.rol_id != rol_colaborador.pk:
                raise CommandError(
                    f'El correo de demostración {email} ya está asociado a otro tipo de usuario.',
                )
            if creado:
                profesional.set_unusable_password()
                profesional.save(update_fields=['password'])
            profesionales[categoria_key] = profesional
            ProfesionalCategoria.objects.get_or_create(
                profesional=profesional,
                categoria_id=categorias[categoria_key].pk,
            )

        hoy = timezone.localdate()
        horas_inicio = (datetime.strptime('10:00', '%H:%M').time(), datetime.strptime('15:00', '%H:%M').time())
        for dias_adelante in range(1, 15):
            fecha = hoy + timedelta(days=dias_adelante)
            for categoria_key, servicio in servicios.items():
                profesional = profesionales[categoria_key]
                for hora_inicio in horas_inicio:
                    inicio = datetime.combine(fecha, hora_inicio)
                    hora_fin = (inicio + timedelta(minutes=servicio.duracion_minutos)).time()
                    Disponibilidad.objects.update_or_create(
                        profesional=profesional,
                        servicio_id=servicio.pk,
                        fecha_especifica=fecha,
                        hora_inicio=hora_inicio,
                        defaults={
                            'hora_fin': hora_fin,
                            'dia_semana': str(fecha.weekday()),
                            'activo': True,
                            'intervalo_minutos': servicio.duracion_minutos,
                        },
                    )

        self.stdout.write(self.style.SUCCESS(
            'Datos de demostración listos: 3 servicios, 3 productos, 3 profesionales y horarios para los próximos 14 días.'
        ))
