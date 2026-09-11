import os
import time
from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()

# Cache for production to prevent excessive disk I/O
_MTIME_CACHE = {}


@register.simple_tag
def static_v(path):
    """
    Returns the static URL for a file with an automatically appended
    cache-busting query parameter (?v=<timestamp>) based on the file's
    last modification time (mtime).
    
    Usage:
        {% load static_version %}
        <link rel="stylesheet" href="{% static_v 'css/style.css' %}">
        <script src="{% static_v 'js/main.js' %}"></script>
    """
    url = static(path)
    
    # In development mode, always bust cache with current timestamp or live mtime
    if getattr(settings, 'DEBUG', False):
        version = int(time.time())
        # Try checking actual file mtime if accessible
        for base in getattr(settings, 'STATICFILES_DIRS', []):
            full_path = os.path.join(base, path)
            if os.path.exists(full_path):
                version = int(os.path.getmtime(full_path))
                break
        return f"{url}?v={version}"
    
    # In production, check cached mtime or static root
    if path in _MTIME_CACHE:
        return f"{url}?v={_MTIME_CACHE[path]}"
    
    version = int(time.time())
    static_root = getattr(settings, 'STATIC_ROOT', None)
    if static_root:
        full_path = os.path.join(static_root, path)
        if os.path.exists(full_path):
            version = int(os.path.getmtime(full_path))
    
    _MTIME_CACHE[path] = version
    return f"{url}?v={version}"
