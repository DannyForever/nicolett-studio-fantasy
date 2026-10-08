import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import BaseUserManager

from .models import Categoria, Producto, Servicio

Usuario = get_user_model()


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
            'email',
        )
        labels = {
            'nombre': 'Primer nombre',
            'segundo_nombre': 'Segundo nombre (opcional)',
            'apellido_paterno': 'Apellido paterno',
            'apellido_materno': 'Apellido materno',
            'telefono': 'Teléfono',
            'email': 'Correo electrónico',
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
            'email': forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['especializaciones'].queryset = Categoria.objects.filter(
            activa=True,
        ).order_by('nombre')
        if self.instance.pk:
            self.fields['especializaciones'].initial = self.instance.especialidades.values_list(
                'categoria_id',
                flat=True,
            )

    def clean_email(self):
        return BaseUserManager.normalize_email(self.cleaned_data['email'].strip())

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
