from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


def role_required(*allowed_roles):
    """Bawal pumasok kung ang role ng user ay wala sa allowed_roles list."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            try:
                role = request.user.profile.role
            except AttributeError:
                role = None

            if role not in allowed_roles:
                # Suriin kung ang binubuksan o pinipindot ay may kinalaman sa delete
                if 'delete' in request.path.lower():
                    messages.error(request, "Wala kang pahintulot na mag-delete ng record na ito.")
                else:
                    messages.error(request, "Wala kang pahintulot na i-access ang page na ito.")

                return redirect('dashboard')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator