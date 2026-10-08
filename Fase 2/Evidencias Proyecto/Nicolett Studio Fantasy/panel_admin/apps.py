from django.apps import AppConfig


class PanelAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'panel_admin'
    label = 'dashboard'
    verbose_name = 'Panel administrativo'
