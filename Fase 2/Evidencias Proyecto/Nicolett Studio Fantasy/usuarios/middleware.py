from django.shortcuts import redirect, render

from .permissions import es_administrador


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith(('/panel_admin/', '/admin/')):
            if not request.user.is_authenticated:
                return redirect('login')
            if not request.user.is_active or not es_administrador(request.user):
                return render(
                    request,
                    'usuarios/acceso_denegado.html',
                    status=403,
                )
        return self.get_response(request)
