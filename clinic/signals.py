from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from .models import LoginActivity
from .services import client_ip, create_activity_log, user_role


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    LoginActivity.objects.create(user=user, ip_address=client_ip(request))
    role = user_role(user)
    create_activity_log(user=user, action='Login', module='Authentication',
                        description=f'{role} logged in.', request=request, category='other')


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if user and user.is_authenticated:
        role = user_role(user)
        create_activity_log(user=user, action='Logout', module='Authentication',
                            description=f'{role} logged out.', request=request, category='other')
