from django.contrib.auth.models import User
from clinic.models import ActivityLog, Notification


def client_ip(request):
    if not request:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')


def user_role(user):
    role = getattr(getattr(user, 'profile', None), 'role', '')
    return 'Assistant' if role == 'nurse' else (role.title() if role else 'System')


def create_activity_log(*, user=None, action, module, description='', affected_record='', request=None, status='success', category='other'):
    """Create trusted audit entries only from Django backend actions."""
    return ActivityLog.objects.create(
        user=user, role=user_role(user), action=action, module=module,
        details=affected_record, description=description, status=status,
        category=category, ip_address=client_ip(request),
    )


def notify_admins(*, title, message, notification_type='system', module='', related_object_id=None,
                  exclude_user=None, triggered_by=None):
    admins = User.objects.filter(profile__role='admin', is_active=True)
    if exclude_user:
        admins = admins.exclude(pk=exclude_user.pk)
    return [Notification.objects.create(recipient=admin, title=title, message=message,
            notification_type=notification_type, module=module, related_object_id=related_object_id,
            triggered_by=triggered_by)
            for admin in admins]
