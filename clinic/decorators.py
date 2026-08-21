from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


def role_required(*allowed_roles):
    """Restricts access if the user's role is not included in the allowed_roles list."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Check if the user is logged in; if not, redirect to the login page
            if not request.user.is_authenticated:
                return redirect('login')

            # Try to get the user's role from their profile, otherwise set it to None
            try:
                role = request.user.profile.role
            except AttributeError:
                role = None

            # If the user's role is not allowed, show an error message and redirect
            if role not in allowed_roles:
                # Check if the requested URL or action involves a deletion
                if 'delete' in request.path.lower():
                    messages.error(request, "You do not have permission to delete this record.")
                else:
                    messages.error(request, "You do not have permission to access this page.")

                return redirect('dashboard')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator