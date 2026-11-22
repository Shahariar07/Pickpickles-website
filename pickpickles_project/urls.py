"""
URL configuration for pickpickles_project project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.views.generic import TemplateView


def cached_serve(request, path, document_root=None, show_indexes=False):
    response = serve(request, path, document_root=document_root, show_indexes=show_indexes)
    if response.status_code == 200 and 'Cache-Control' not in response:
        response['Cache-Control'] = 'public, max-age=2592000'
    return response


urlpatterns = [
    path('manifest.json', TemplateView.as_view(template_name='manifest.json', content_type='application/manifest+json'), name='manifest'),
    path('service-worker.js', TemplateView.as_view(template_name='webpush_serviceworker.js', content_type='application/javascript'), name='root_service_worker'),
    path('admin/', admin.site.urls),
    path('dashboard/', include('dashboard.urls')),
    path('', include('store.urls')),
    re_path(r'^media/(?P<path>.*)$', cached_serve, {'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', cached_serve, {'document_root': settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else settings.STATIC_ROOT}),
]

try:
    import webpush  # noqa: F401
    urlpatterns.insert(2, path('webpush/', include('webpush.urls')))
except ImportError:
    pass

# Custom Error Handlers
handler404 = 'store.views.custom_404_view'
handler500 = 'store.views.custom_500_view'
