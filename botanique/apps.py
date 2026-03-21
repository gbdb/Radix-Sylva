from django.apps import AppConfig


class BotaniqueConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'botanique'
    verbose_name = 'Radix Sylva (botanique)'

    def ready(self):
        import botanique.signals  # noqa: F401
