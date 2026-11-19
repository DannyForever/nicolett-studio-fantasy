from django import forms
from django.contrib.auth import get_user_model

from .chile_geography import REGIONES, REGION_ORDER
from .models import DireccionCliente


class ClienteConfiguracionForm(forms.Form):
    nombre = forms.CharField(max_length=100, label='Nombres')
    segundo_nombre = forms.CharField(
        max_length=100,
        required=False,
        label='Segundo nombre (opcional)',
    )
    apellido_paterno = forms.CharField(max_length=100, label='Apellido paterno')
    apellido_materno = forms.CharField(max_length=100, label='Apellido materno')
    email = forms.EmailField(label='Correo electrónico')
    telefono = forms.CharField(max_length=20, label='Teléfono')

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': (
                    'w-full border border-[#ead7bc] bg-white px-3 py-3 text-sm '
                    'disabled:cursor-not-allowed disabled:border-gray-200 '
                    'disabled:bg-gray-100 disabled:text-gray-500 disabled:opacity-100'
                ),
                'disabled': 'disabled',
            })

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exclude(pk=self.usuario.pk).exists():
            raise forms.ValidationError('Ese correo ya está asociado a otra cuenta.')
        return email

    def save(self):
        self.usuario.nombre = self.cleaned_data['nombre'].strip()
        self.usuario.segundo_nombre = self.cleaned_data['segundo_nombre'].strip()
        self.usuario.apellido_paterno = self.cleaned_data['apellido_paterno'].strip()
        self.usuario.apellido_materno = self.cleaned_data['apellido_materno'].strip()
        self.usuario.telefono = self.cleaned_data['telefono'].strip()
        self.usuario.email = self.cleaned_data['email']
        self.usuario.save(update_fields=[
            'nombre',
            'segundo_nombre',
            'apellido_paterno',
            'apellido_materno',
            'telefono',
            'email',
        ])
        return self.usuario


class ClienteCambiarContrasenaForm(forms.Form):
    password_actual = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'current-password',
            'placeholder': '****',
        }),
        label='Contraseña actual',
    )
    password_nueva = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput,
        label='Nueva contraseña',
    )
    password_confirmacion = forms.CharField(
        widget=forms.PasswordInput,
        label='Confirmar nueva contraseña',
    )

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            extra_padding = ' pr-12' if name == 'password_actual' else ''
            field.widget.attrs.update({
                'class': (
                    'w-full border border-[#ead7bc] bg-white px-3 py-3 text-sm'
                    f'{extra_padding}'
                ),
            })

    def clean_password_actual(self):
        password = self.cleaned_data['password_actual']
        if not self.usuario.check_password(password):
            raise forms.ValidationError('La contraseña actual no es correcta.')
        return password

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('password_nueva') != cleaned_data.get('password_confirmacion'):
            self.add_error('password_confirmacion', 'Las contraseñas nuevas no coinciden.')
        return cleaned_data

    def save(self):
        self.usuario.set_password(self.cleaned_data['password_nueva'])
        self.usuario.save(update_fields=['password'])
        return self.usuario


class ClienteDireccionForm(forms.ModelForm):
    region = forms.ChoiceField(
        choices=[('', 'Selecciona una región')] + [
            (region, region) for region in REGION_ORDER
        ],
        label='Región',
    )
    provincia = forms.ChoiceField(
        choices=[('', 'Primero selecciona una región')],
        label='Provincia',
        disabled=True,
    )
    comuna = forms.ChoiceField(
        choices=[('', 'Primero selecciona una provincia')],
        label='Comuna',
        disabled=True,
    )

    class Meta:
        model = DireccionCliente
        fields = [
            'nombre',
            'rut',
            'razon_social',
            'giro',
            'direccion',
            'complemento',
            'region',
            'provincia',
            'comuna',
            'codigo_postal',
            'telefono',
            'instrucciones',
        ]
        labels = {
            'nombre': 'Nombre completo / contacto',
            'rut': 'RUT',
            'razon_social': 'Razón social (opcional)',
            'giro': 'Giro (opcional)',
            'direccion': 'Calle y número',
            'complemento': 'Depto., casa u otra referencia (opcional)',
            'region': 'Región',
            'provincia': 'Provincia',
            'comuna': 'Comuna',
            'codigo_postal': 'Código postal (opcional)',
            'telefono': 'Teléfono de contacto',
            'instrucciones': 'Indicaciones de entrega (opcional)',
        }
        widgets = {
            'instrucciones': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, usuario, tipo, **kwargs):
        if tipo not in dict(DireccionCliente.TIPOS):
            raise ValueError('El tipo de dirección no es válido.')
        self.usuario = usuario
        self.tipo = tipo
        kwargs.setdefault('prefix', tipo)
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.pk:
            self.initial.update({
                'region': '',
                'provincia': '',
                'comuna': '',
            })

        selected_region = (
            self.data.get(self.add_prefix('region'))
            if self.is_bound
            else self.initial.get('region', '')
        )
        if selected_region in REGIONES:
            provincias = REGIONES[selected_region]
            self.fields['provincia'].choices = [
                ('', 'Selecciona una provincia'),
                *[(provincia, provincia) for provincia in provincias],
            ]
            self.fields['provincia'].disabled = False
            selected_provincia = (
                self.data.get(self.add_prefix('provincia'))
                if self.is_bound
                else self.initial.get('provincia', '')
            )
            if selected_provincia in provincias:
                comunas = provincias[selected_provincia]['comunas']
                self.fields['comuna'].choices = [
                    ('', 'Selecciona una comuna'),
                    *[(comuna, comuna) for comuna in comunas],
                ]
                self.fields['comuna'].disabled = False
                selected_comuna = (
                    self.data.get(self.add_prefix('comuna'))
                    if self.is_bound
                    else self.initial.get('comuna', '')
                )
                if selected_comuna in comunas:
                    self.initial['comuna'] = selected_comuna

        if tipo == DireccionCliente.TIPO_ENVIO:
            for name in ('rut', 'razon_social', 'giro'):
                self.fields.pop(name)
            self.fields['nombre'].label = 'Nombre de quien recibe'
            self.fields['instrucciones'].widget.attrs.update({
                'autocomplete': 'off',
            })
        else:
            self.fields.pop('instrucciones')
            self.fields['rut'].required = True

        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'w-full border border-[#ead7bc] bg-white px-3 py-3 text-sm',
            })
        self.fields['region'].widget.attrs['data-address-region'] = ''
        self.fields['provincia'].widget.attrs['data-address-province'] = ''
        self.fields['comuna'].widget.attrs['data-address-commune'] = ''

    def save(self, commit=True):
        direccion = super().save(commit=False)
        direccion.usuario = self.usuario
        direccion.tipo = self.tipo
        if commit:
            direccion.save()
        return direccion
