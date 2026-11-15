from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin


class TemporaryPasswordMiddleware(MiddlewareMixin):
    """Require accounts using an admin-issued temporary password to change it."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated:
            return None

        match = getattr(request, "resolver_match", None)
        url_name = match.url_name if match else None
        if url_name == "logout":
            return None

        profile = getattr(request.user, "profile", None)
        if not profile or not profile.must_change_password:
            return None

        expires_at = profile.temporary_password_expires_at
        if not expires_at or expires_at <= timezone.now():
            logout(request)
            messages.error(request, "Temporary password expired. Please contact the administrator for a new reset.")
            return redirect("landing")

        if url_name != "change_password":
            return redirect("change_password")
        return None
