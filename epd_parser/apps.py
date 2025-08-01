"""Django app configuration for EPD parser."""
from django.apps import AppConfig


class EpdParserConfig(AppConfig):
    """Configuration for EPD parser app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'epd_parser'
    verbose_name = 'EPD Parser' 