def _safe_is_view_only(user):
    if not user or not user.is_authenticated:
        return False
    username = (getattr(user, 'username', '') or '').strip().lower()
    if username in ['mitu', 'staff_mitu', 'mitu_view']:
        return True
    try:
        profile = getattr(user, 'security_profile', None)
        if profile and profile.is_view_only:
            return True
    except Exception:
        pass
    return False

def _safe_can_edit(user):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if _safe_is_view_only(user):
        return False
    try:
        from dashboard.models import DashboardSecurityConfig
        config = DashboardSecurityConfig.get_config()
        if config.strict_admin_only_edit:
            return False
        profile = getattr(user, 'security_profile', None)
        if profile is not None:
            return profile.can_edit_records
    except Exception:
        pass
    return True

def _safe_can_delete(user):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if _safe_is_view_only(user):
        return False
    try:
        from dashboard.models import DashboardSecurityConfig
        config = DashboardSecurityConfig.get_config()
        if config.allow_staff_delete_override:
            profile = getattr(user, 'security_profile', None)
            if profile and profile.can_delete_records:
                return True
    except Exception:
        pass
    return False

def _safe_can_dispatch(user):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if _safe_is_view_only(user):
        return False
    try:
        from dashboard.models import DashboardSecurityConfig
        config = DashboardSecurityConfig.get_config()
        if config.strict_admin_only_dispatch:
            return False
        profile = getattr(user, 'security_profile', None)
        if profile is not None:
            return profile.can_dispatch_orders
    except Exception:
        pass
    return True

def dashboard_permissions(request):
    """
    Context processor to provide unified permission flags across all dashboard templates.
    Ensures View-Only users (such as 'mitu') have accurate flags without manual view injections.
    Guaranteed never to crash or throw 500 error.
    """
    default_perms = {
        'can_edit': False,
        'can_delete': False,
        'can_dispatch': False,
        'is_view_only': False,
        'is_readonly_user': False,
    }
    try:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return default_perms

        # Try to use views helper functions if available, otherwise safe fallbacks
        try:
            from .views import can_user_edit, can_user_delete, can_user_dispatch, is_view_only_user
            view_only = is_view_only_user(user)
            can_edit = can_user_edit(user)
            can_delete = can_user_delete(user)
            can_dispatch = can_user_dispatch(user)
        except Exception:
            view_only = _safe_is_view_only(user)
            can_edit = _safe_can_edit(user)
            can_delete = _safe_can_delete(user)
            can_dispatch = _safe_can_dispatch(user)

        return {
            'can_edit': can_edit,
            'can_delete': can_delete,
            'can_dispatch': can_dispatch,
            'is_view_only': view_only,
            'is_readonly_user': view_only,
        }
    except Exception:
        return default_perms

