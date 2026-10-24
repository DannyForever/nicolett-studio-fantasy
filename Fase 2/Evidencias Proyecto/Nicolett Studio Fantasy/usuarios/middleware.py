from django.shortcuts import redirect, render

from .permissions import es_administrador, es_colaborador


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith(('/panel_admin/', '/admin/')):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.is_active and es_colaborador(request.user):
                collaborator_paths = (
                    '/panel_admin/mi-agenda/',
                    '/panel_admin/mi-configuracion/',
                    '/panel_admin/citas/',
                    '/panel_admin/agenda/',
                    '/panel_admin/recordatorios/',
                )
                if (
                    request.path_info.startswith(collaborator_paths)
                    and not request.path_info.startswith(
                        '/panel_admin/agenda/respuesta-suspension/',
                    )
                ):
                    return self.get_response(request)
            if not request.user.is_active or not es_administrador(request.user):
                return render(
                    request,
                    'usuarios/acceso_denegado.html',
                    status=403,
                )
        return self.get_response(request)
