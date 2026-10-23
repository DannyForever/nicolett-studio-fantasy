import smtplib
from urllib.parse import quote

from django.shortcuts import render, redirect
from django.core.mail import send_mail
from django.core.mail.message import BadHeaderError
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.conf import settings

# Create your views here.
def home_view(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        apellido = request.POST.get('apellido')
        email = request.POST.get('email')
        telefono = request.POST.get('telefono')
        asunto = request.POST.get('asunto')
        mensaje_usuario = request.POST.get('mensaje')

        cuerpo_correo = (
            f"Nuevo mensaje de contacto desde la web de Nicolett Studio Fantasy:\n\n"
            f"Nombre: {nombre} {apellido}\n"
            f"Email: {email}\n"
            f"Teléfono: {telefono}\n"
            f"Asunto: {asunto}\n\n"
            f"Mensaje:\n{mensaje_usuario}"
        )

        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            messages.error(request, 'El servicio de correo no está configurado. Inténtalo más tarde.')
        else:
            try:
                send_mail(
                    subject=f"[Contacto Web] {asunto}",
                    message=cuerpo_correo,
                    from_email=None,
                    recipient_list=[settings.EMAIL_HOST_USER],
                    fail_silently=False,
                )
                messages.success(request, '¡Tu mensaje se envió exitosamente! Nos pondremos en contacto contigo pronto.')
            except (BadHeaderError, OSError, smtplib.SMTPException):
                messages.error(request, 'Hubo un problema al enviar el mensaje. Por favor, inténtalo nuevamente.')

        return redirect('home')

    whatsapp_message = (
        'Hola, quisiera hacer una consulta general sobre Nicolett Studio Fantasy. '
        'Me interesa conocer información sobre sus servicios, productos, horarios o '
        'disponibilidad. ¿Me podrían orientar? Mi consulta es:'
    )
    whatsapp_url = (
        'https://wa.me/56982108409?text='
        f'{quote(whatsapp_message, safe="")}'
    )
    return render(
        request,
        'core/landing.html',
        {'whatsapp_url': whatsapp_url},
    )

# Importa tu modelo de usuario si lo necesitas aquí, o maneja la lógica:
def login_view(request):
    if request.method == 'POST':
        # Lógica de inicio de sesión
        pass
    return render(request, 'usuarios/login.html') # O la ruta de tu template de login

def register_view(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        segundo_nombre = request.POST.get('segundo_nombre')
        apellido_paterno = request.POST.get('apellido_paterno')
        apellido_materno = request.POST.get('apellido_materno')
        telefono = request.POST.get('telefono')
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        # Aquí puedes guardar en tu modelo de SQLite
        return redirect('login')
        
    return render(request, 'usuarios/register.html')