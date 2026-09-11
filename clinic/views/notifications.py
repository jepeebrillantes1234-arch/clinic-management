from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from clinic.models import Notification


@login_required
@require_POST
def mark_notification_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    return redirect(request.POST.get('next') or 'dashboard')


@login_required
@require_POST
def mark_all_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect(request.POST.get('next') or 'dashboard')


@login_required
def notification_status(request):
    notifications = Notification.objects.filter(recipient=request.user).values('id', 'title', 'message', 'is_read', 'created_at')[:8]
    return JsonResponse({'unread_count': Notification.objects.filter(recipient=request.user, is_read=False).count(),
                         'notifications': list(notifications)})
