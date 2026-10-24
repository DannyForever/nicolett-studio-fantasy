import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import Categoria, Producto, Servicio
from usuarios.utils import normalizar_correo_acceso

Usuario = get_user_model()


def _texto_caracteristica(valor):
    return ' '.join((valor or '').casefold().split())


class ServicioForm(forms.ModelForm):
    activo = forms.TypedChoiceField(
        choices=(('true', 'Activo'), ('false', 'Desactivado')),
        coerce=lambda value: value == 'true',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Disponibilidad',
    )

    class Meta:
        model = Servicio
        fields = (
            'nombre',
            'categoria',
            'descripcion',
            'precio',
            'duracion_minutos',
            'imagen_url',
            'activo',
        )
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'step': '1'}),
            'duracion_minutos': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'imagen_url': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'nombre': 'Nombre',
            'categoria': 'Categoría',
            'descripcion': 'Descripción',
            'precio': 'Precio (CLP)',
            'duracion_minutos': 'Duración (minutos)',
            'imagen_url': 'Imagen',
            'activo': 'Disponibilidad',
        }

    def clean(self):
        cleaned = super().clean()
        nombre = cleaned.get('nombre')
        categoria = cleaned.get('categoria')
        precio = cleaned.get('precio')
        duracion = cleaned.get('duracion_minutos')
        if not all((nombre, categoria, precio is not None, duracion is not None)):
            return cleaned

        similares = Servicio.objects.filter(
            categoria=categoria,
            precio=precio,
            duracion_minutos=duracion,
        )
        if self.instance.pk:
            similares = similares.exclude(pk=self.instance.pk)
        nombre_normalizado = _texto_caracteristica(nombre)
        descripcion = _texto_caracteristica(cleaned.get('descripcion'))
        if any(
            _texto_caracteristica(item.nombre) == nombre_normalizado
            and _texto_caracteristica(item.descripcion) == descripcion
            for item in similares
        ):
            self.add_error(
                None,
                'Ya existe un servicio con estas características. Modifica al menos un dato para guardarlo.',
            )
        return cleaned

    def clean_precio(self):
        precio = self.cleaned_data['precio']
        if precio <= 0:
            raise forms.ValidationError('El precio debe ser mayor que cero.')
        return precio

    def clean_duracion_minutos(self):
        duracion = self.cleaned_data['duracion_minutos']
        if duracion <= 0:
            raise forms.ValidationError('La duración debe ser mayor que cero.')
        return duracion


class ProductoForm(forms.ModelForm):
    activo = forms.TypedChoiceField(
        choices=(('true', 'Activo'), ('false', 'Desactivado')),
        coerce=lambda value: value == 'true',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Disponibilidad',
    )

    class Meta:
        model = Producto
        fields = (
            'nombre',
            'categoria',
            'descripcion',
            'precio',
            'stock',
            'imagen_url',
            'activo',
        )
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'step': '1'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'imagen_url': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'nombre': 'Nombre',
            'categoria': 'Categoría',
            'descripcion': 'Descripción',
            'precio': 'Precio (CLP)',
            'stock': 'Stock disponible',
            'imagen_url': 'Imagen',
            'activo': 'Disponibilidad',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = Categoria.objects.filter(activa=True).order_by('nombre')
        self.fields['imagen_url'].required = not bool(self.instance.pk)

    def clean(self):
        cleaned = super().clean()
        nombre = cleaned.get('nombre')
        categoria = cleaned.get('categoria')
        precio = cleaned.get('precio')
        if not all((nombre, categoria, precio is not None)):
            return cleaned

        similares = Producto.objects.filter(
            categoria=categoria,
            precio=precio,
        )
        if self.instance.pk:
            similares = similares.exclude(pk=self.instance.pk)
        nombre_normalizado = _texto_caracteristica(nombre)
        descripcion = _texto_caracteristica(cleaned.get('descripcion'))
        if any(
            _texto_caracteristica(item.nombre) == nombre_normalizado
            and _texto_caracteristica(item.descripcion) == descripcion
            for item in similares
        ):
            self.add_error(
                None,
                'Ya existe un producto con estas características. Modifica al menos un dato para guardarlo.',
            )
        return cleaned

    def clean_precio(self):
        precio = self.cleaned_data['precio']
        if precio <= 0:
            raise forms.ValidationError('El precio debe ser mayor que cero.')
        return precio

    def clean_stock(self):
        stock = self.cleaned_data['stock']
        if stock < 0:
            raise forms.ValidationError('El stock no puede ser negativo.')
        return stock


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ('nombre', 'tipo')

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        duplicada = Categoria.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            duplicada = duplicada.exclude(pk=self.instance.pk)
        if duplicada.exists():
            raise forms.ValidationError('Ya existe una categoría con ese nombre.')
        return nombre

    def clean_tipo(self):
        return self.cleaned_data['tipo'].strip()

    def save(self, commit=True):
        categoria = super().save(commit=False)
        categoria.activa = True
        if commit:
            categoria.save()
        return categoria


class PersonalForm(forms.ModelForm):
    email = forms.CharField(
        label='Correo de acceso',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'off',
            'inputmode': 'email',
        }),
    )
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )
    confirmar_password = forms.CharField(
        label='Confirmar contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )
    especializaciones = forms.ModelMultipleChoiceField(
        queryset=Categoria.objects.none(),
        label='Categorías de especialización',
        required=True,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Usuario
        fields = (
            'nombre',
            'segundo_nombre',
            'apellido_paterno',
            'apellido_materno',
            'telefono',
            'correo_contacto',
            'email',
        )
        labels = {
            'nombre': 'Primer nombre',
            'segundo_nombre': 'Segundo nombre (opcional)',
            'apellido_paterno': 'Apellido paterno',
            'apellido_materno': 'Apellido materno',
            'telefono': 'Teléfono',
            'correo_contacto': 'Correo electrónico personal',
            'email': 'Correo de acceso',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'given-name'}),
            'segundo_nombre': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'additional-name'}),
            'apellido_paterno': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'family-name'}),
            'apellido_materno': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TelInput(attrs={
                'class': 'form-control',
                'autocomplete': 'tel',
            }),
            'correo_contacto': forms.EmailInput(attrs={
                'class': 'form-control',
                'autocomplete': 'email',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['especializaciones'].queryset = Categoria.objects.filter(
            activa=True,
        ).order_by('nombre')
        self.fields['correo_contacto'].required = True
        self.order_fields([
            'nombre',
            'segundo_nombre',
            'apellido_paterno',
            'apellido_materno',
            'telefono',
            'correo_contacto',
            'email',
            'password',
            'confirmar_password',
            'especializaciones',
        ])
        if self.instance.pk:
            self.fields['especializaciones'].initial = self.instance.especialidades.values_list(
                'categoria_id',
                flat=True,
            )
            self.initial['email'] = self.instance.email.partition('@')[0]
            self.fields['password'].required = False
            self.fields['confirmar_password'].required = False
            self.fields['password'].help_text = (
                'Déjala en blanco para conservar la contraseña actual.'
            )

    def clean_email(self):
        try:
            return normalizar_correo_acceso(
                self.cleaned_data['email'],
                self.cleaned_data.get('nombre', ''),
                self.cleaned_data.get('apellido_paterno', ''),
                self.cleaned_data.get('apellido_materno', ''),
                excluir_pk=self.instance.pk,
            )
        except DjangoValidationError as error:
            raise forms.ValidationError(error.messages) from error

    def clean_correo_contacto(self):
        return BaseUserManager.normalize_email(self.cleaned_data['correo_contacto'].strip())

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not password:
            return password
        try:
            validate_password(password, self.instance if self.instance.pk else None)
        except DjangoValidationError as error:
            raise forms.ValidationError(error.messages) from error
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirmation = cleaned.get('confirmar_password')
        if password or confirmation:
            if password != confirmation:
                self.add_error('confirmar_password', 'Las contraseñas no coinciden.')
        return cleaned

    def clean_telefono(self):
        telefono = self.cleaned_data['telefono'].strip()
        if not re.fullmatch(r'[+0-9\s().-]+', telefono):
            raise forms.ValidationError(
                'Formato requerido: +569 XXXX XXXX o 9 XXXX XXXX.',
            )
        if telefono.count('+') > 1 or ('+' in telefono and not telefono.startswith('+')):
            raise forms.ValidationError(
                'Formato requerido: +569 XXXX XXXX o 9 XXXX XXXX.',
            )

        digitos = re.sub(r'[^0-9]', '', telefono)
        if telefono.startswith('+'):
            if not digitos.startswith('56'):
                raise forms.ValidationError(
                    'Formato requerido: +569 XXXX XXXX o 9 XXXX XXXX.',
                )
            numero_nacional = digitos[2:]
        elif digitos.startswith('56') and len(digitos) == 11:
            numero_nacional = digitos[2:]
        else:
            numero_nacional = digitos

        if len(numero_nacional) != 9 or not numero_nacional.startswith('9'):
            raise forms.ValidationError(
                'Formato requerido: +569 XXXX XXXX o 9 XXXX XXXX.',
            )
        return f'+56{numero_nacional}'


class AdminProfileForm(forms.ModelForm):
    email = forms.CharField(
        label='Correo de acceso',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'off',
        }),
    )

    class Meta:
        model = Usuario
        fields = (
            'nombre',
            'segundo_nombre',
            'apellido_paterno',
            'apellido_materno',
            'correo_contacto',
            'email',
        )
        labels = {
            'nombre': 'Nombre',
            'segundo_nombre': 'Segundo nombre (opcional)',
            'apellido_paterno': 'Apellido paterno',
            'apellido_materno': 'Apellido materno',
            'correo_contacto': 'Correo electrónico',
            'email': 'Correo de acceso',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'given-name'}),
            'segundo_nombre': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'additional-name'}),
            'apellido_paterno': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'family-name'}),
            'apellido_materno': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'family-name'}),
            'correo_contacto': forms.EmailInput(attrs={
                'class': 'form-control',
                'autocomplete': 'email',
            }),
            'email': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['correo_contacto'].required = True
        if self.instance.pk:
            self.initial['email'] = self.instance.email.partition('@')[0]

    def clean_correo_contacto(self):
        return BaseUserManager.normalize_email(self.cleaned_data['correo_contacto'].strip())

    def clean_email(self):
        try:
            return normalizar_correo_acceso(
                self.cleaned_data['email'],
                self.cleaned_data.get('nombre', ''),
                self.cleaned_data.get('apellido_paterno', ''),
                self.cleaned_data.get('apellido_materno', ''),
                excluir_pk=self.instance.pk,
            )
        except DjangoValidationError as error:
            raise forms.ValidationError(error.messages) from error


class ColaboradorPasswordResetForm(forms.Form):
    password = forms.CharField(
        label='Nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )
    confirmar_password = forms.CharField(
        label='Confirmar contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, usuario, *args, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data['password']
        try:
            validate_password(password, self.usuario)
        except DjangoValidationError as error:
            raise forms.ValidationError(error.messages) from error
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirmation = cleaned.get('confirmar_password')
        if password and confirmation and password != confirmation:
            self.add_error('confirmar_password', 'Las contraseñas no coinciden.')
        return cleaned


class AdminPasswordChangeForm(forms.Form):
    actual = forms.CharField(
        label='Contraseña actual',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'current-password'}),
    )
    nueva = forms.CharField(
        label='Nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    confirmar = forms.CharField(
        label='Confirmar nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_actual(self):
        actual = self.cleaned_data['actual']
        if not self.user.check_password(actual):
            raise forms.ValidationError('La contraseña actual no es correcta.')
        return actual

    def clean(self):
        cleaned = super().clean()
        nueva = cleaned.get('nueva')
        confirmar = cleaned.get('confirmar')
        if nueva and confirmar and nueva != confirmar:
            self.add_error('confirmar', 'Las contraseñas nuevas no coinciden.')
        if nueva and not self.errors.get('nueva'):
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError

            try:
                validate_password(nueva, self.user)
            except ValidationError as error:
                self.add_error('nueva', error)
        return cleaned
