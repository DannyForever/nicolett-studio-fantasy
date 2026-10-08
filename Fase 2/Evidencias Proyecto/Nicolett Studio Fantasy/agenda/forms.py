import datetime
from datetime import date, time, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import DiaCerrado, Reserva, ServicioAgenda

Usuario = get_user_model()

FORM_CONTROL = {'class': 'form-control'}
FORM_SELECT = {'class': 'form-select'}


def _profesionales_disponibles_para_servicio(service_id):
    profesionales = Usuario.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
        rol__nombre__iexact='Colaborador',
    ).order_by('nombre', 'apellido_paterno')
    if not service_id:
        return profesionales
    try:
        servicio = ServicioAgenda.objects.get(pk=service_id, activo=True)
    except (ValueError, TypeError, ServicioAgenda.DoesNotExist):
        return profesionales.none()
    return profesionales.filter(
        especialidades__categoria_id=servicio.categoria_id,
    ).distinct()


class ReservaManualForm(forms.ModelForm):
    fecha = forms.DateField(
        widget=forms.DateInput(attrs={**FORM_CONTROL, 'type': 'date'}),
        input_formats=['%Y-%m-%d'],
    )
    hora = forms.TimeField(
        widget=forms.Select(attrs=FORM_SELECT),
        input_formats=['%H:%M'],
    )

    class Meta:
        model = Reserva
        fields = [
            'servicio', 'profesional', 'cliente_nombre',
            'cliente_email', 'cliente_telefono',
        ]
        labels = {
            'servicio': 'Servicio',
            'profesional': 'Profesional',
            'cliente_nombre': 'Nombre de la clienta o cliente',
            'cliente_email': 'Correo electrónico',
            'cliente_telefono': 'Teléfono',
        }
        widgets = {
            'servicio': forms.Select(attrs=FORM_SELECT),
            'profesional': forms.Select(attrs=FORM_SELECT),
            'cliente_nombre': forms.TextInput(attrs=FORM_CONTROL),
            'cliente_email': forms.EmailInput(attrs=FORM_CONTROL),
            'cliente_telefono': forms.TextInput(attrs=FORM_CONTROL),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servicio'].queryset = ServicioAgenda.objects.filter(activo=True).order_by('nombre')
        self.fields['profesional'].queryset = _profesionales_disponibles_para_servicio(
            self.data.get('servicio') if self.is_bound else None,
        )
        self.fields['profesional'].required = True
        self.fields['cliente_nombre'].required = True
        self.fields['cliente_email'].required = False
        self.fields['cliente_telefono'].required = False


class DisponibilidadDiaForm(forms.Form):
    fecha = forms.DateField(
        widget=forms.HiddenInput(),
        input_formats=['%Y-%m-%d'],
    )
    servicio = forms.ModelChoiceField(
        queryset=ServicioAgenda.objects.none(),
        label='Servicio',
        widget=forms.Select(attrs={**FORM_SELECT, 'data-schedule-service': 'true'}),
    )
    profesional = forms.ModelChoiceField(
        queryset=Usuario.objects.none(),
        label='Profesional',
        widget=forms.Select(attrs={**FORM_SELECT, 'data-schedule-professional': 'true'}),
    )
    bloques = forms.JSONField(
        label='Bloques de atención',
        widget=forms.HiddenInput(attrs={'data-schedule-blocks': 'true'}),
    )
    motivo_suspension = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={**FORM_CONTROL, 'rows': 2}),
    )
    notificar_clientes = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servicio'].queryset = ServicioAgenda.objects.filter(
            activo=True,
        ).order_by('nombre')
        servicio_id = self.data.get('servicio') if self.is_bound else None
        self.fields['profesional'].queryset = _profesionales_disponibles_para_servicio(
            servicio_id,
        )

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get('fecha')
        servicio = cleaned.get('servicio')
        bloques = cleaned.get('bloques')

        if fecha and fecha < timezone.localdate():
            self.add_error('fecha', 'No se pueden habilitar horarios en fechas pasadas.')
        if fecha and DiaCerrado.objects.filter(fecha=fecha).exists():
            self.add_error('fecha', 'El salón está cerrado en la fecha seleccionada.')
        if not servicio or not isinstance(bloques, list):
            return cleaned
        if not bloques:
            self.add_error('bloques', 'Agrega al menos un bloque de atención.')
            return cleaned

        duracion = servicio.duracion_minutos
        intervalos = []
        bloques_limpios = []
        for bloque in bloques:
            if not isinstance(bloque, dict):
                self.add_error('bloques', 'Hay un bloque horario inválido.')
                return cleaned
            try:
                inicio = time.fromisoformat(bloque['inicio'])
                fin = time.fromisoformat(bloque['fin'])
            except (KeyError, TypeError, ValueError):
                self.add_error('bloques', 'Completa el inicio y fin de cada bloque.')
                return cleaned
            inicio_dt = datetime.datetime.combine(date.min, inicio)
            fin_esperado = (inicio_dt + timedelta(minutes=duracion)).time()
            if fin != fin_esperado:
                self.add_error(
                    'bloques',
                    f'Cada bloque debe durar exactamente {duracion} minutos según el servicio.',
                )
                return cleaned
            intervalos.append((inicio, fin))
            bloques_limpios.append({
                'inicio': inicio.strftime('%H:%M'),
                'fin': fin.strftime('%H:%M'),
            })

        intervalos.sort()
        if any(actual[0] < anterior[1] for anterior, actual in zip(intervalos, intervalos[1:])):
            self.add_error('bloques', 'Los bloques de atención no pueden superponerse.')
        cleaned['bloques'] = bloques_limpios

        return cleaned


class CierreDiaForm(forms.Form):
    fecha = forms.DateField(
        label='Día que se cerrará',
        widget=forms.DateInput(attrs={**FORM_CONTROL, 'type': 'date'}),
        input_formats=['%Y-%m-%d'],
    )
    motivo = forms.CharField(
        label='Motivo (opcional)',
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs=FORM_CONTROL),
    )

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha < timezone.localdate():
            raise forms.ValidationError('No se puede cerrar una fecha que ya pasó.')
        return fecha


class ReagendarReservaForm(forms.Form):
    fecha = forms.DateField(widget=forms.DateInput(attrs={**FORM_CONTROL, 'type': 'date'}))
    hora = forms.TimeField(widget=forms.Select(attrs=FORM_SELECT), input_formats=['%H:%M'])


class CancelarReservaForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo de cancelación',
        max_length=500,
        widget=forms.Textarea(attrs={**FORM_CONTROL, 'rows': 3}),
    )
