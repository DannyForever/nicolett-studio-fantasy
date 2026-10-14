from django import forms
from django.contrib.auth import get_user_model


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
                    'w-full border border-[#e8e0da] bg-white px-3 py-3 text-sm '
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
        widget=forms.PasswordInput,
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
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'w-full border border-[#e8e0da] bg-white px-3 py-3 text-sm',
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
