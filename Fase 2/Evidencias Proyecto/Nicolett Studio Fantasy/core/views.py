from django.shortcuts import render, redirect
from django.core.mail import send_mail
from django.contrib import messages
from django.contrib.auth.hashers import make_password

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

        try:
            send_mail(
                subject=f"[Contacto Web] {asunto}",
                message=cuerpo_correo,
                from_email='danielabe.hc@gmail.com',
                recipient_list=['danielabe.hc@gmail.com'],
                fail_silently=False,
            )
            messages.success(request, '¡Tu mensaje se envió exitosamente! Nos pondremos en contacto contigo pronto.')
        except Exception as e:
            messages.error(request, 'Hubo un problema al enviar el mensaje. Por favor, inténtalo nuevamente.')

        return redirect('home')

    return render(request, 'core/landing.html')

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