from .views import can_user_edit, can_user_delete, can_user_dispatch, is_view_only_user

def dashboard_permissions(request):
    """
    Context processor to provide unified permission flags across all dashboard templates.
    Ensures View-Only users (such as 'mitu') have accurate flags without manual view injections.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not (user.is_staff or user.is_superuser):
        return {
            'can_edit': False,
            'can_delete': False,
            'can_dispatch': False,
            'is_view_only': False,
            'is_readonly_user': False,
        }

    view_only = is_view_only_user(user)
    return {
        'can_edit': can_user_edit(user),
        'can_delete': can_user_delete(user),
        'can_dispatch': can_user_dispatch(user),
        'is_view_only': view_only,
        'is_readonly_user': view_only,
    }
