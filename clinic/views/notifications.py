from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from clinic.models import Notification
from clinic.models import Notification, Student, Medicine

@login_required
def notification_list(request):
    query = request.GET.get('q', '').strip()
    notification_type = request.GET.get('type', '').strip().lower()
    status = request.GET.get('status', '').strip().lower()
    date_filter = request.GET.get('date', '').strip().lower()
    notifications = Notification.objects.filter(recipient=request.user).select_related('triggered_by')
    if query:
        notifications = notifications.filter(Q(title__icontains=query) | Q(message__icontains=query) | Q(module__icontains=query) | Q(triggered_by__username__icontains=query))
    if notification_type:
        notifications = notifications.filter(notification_type__iexact=notification_type)
    if status == 'unread':
        notifications = notifications.filter(is_read=False)
    elif status == 'read':
        notifications = notifications.filter(is_read=True)
    today = timezone.localdate()
    if date_filter == 'today':
        notifications = notifications.filter(created_at__date=today)
    elif date_filter == 'yesterday':
        notifications = notifications.filter(created_at__date=today - timedelta(days=1))
    elif date_filter == 'last7':
        notifications = notifications.filter(created_at__gte=timezone.now() - timedelta(days=7))
    elif date_filter == 'last30':
        notifications = notifications.filter(created_at__gte=timezone.now() - timedelta(days=30))
    return render(request, 'clinic/notifications.html', {
        'notifications': notifications, 'query': query, 'selected_type': notification_type,
        'selected_status': status, 'selected_date': date_filter,
    })


@login_required
@require_POST
def mark_notification_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])

    ntype = notification.notification_type
    obj_id = notification.related_object_id

    if ntype == 'student' and obj_id:
        if Student.objects.filter(pk=obj_id, is_deleted=False).exists():
            return redirect('student_views', pk=obj_id)
        messages.error(request, "This record is no longer available.")
        return redirect('student_records')

    if ntype == 'medicine' and obj_id:
        if Medicine.objects.filter(pk=obj_id, is_deleted=False).exists():
            return redirect('medicine_edit', pk=obj_id)
        messages.error(request, "This record is no longer available.")
        return redirect('medicine_list')

    if ntype == 'recycle_bin':
        return redirect('trash_list')

    if ntype in ('system', 'assistant'):
        return redirect('activity_log_list')

    return redirect(request.POST.get('next') or 'dashboard')


@login_required
@require_POST
def mark_all_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect(request.POST.get('next') or 'dashboard')


@login_required
@require_POST
def delete_selected_notifications(request):
    notification_ids = request.POST.getlist('notification_ids')
    deleted_count, _ = Notification.objects.filter(recipient=request.user, pk__in=notification_ids).delete()
    messages.success(request, f'{deleted_count} selected notification(s) deleted.' if deleted_count else 'Select at least one notification.')
    return redirect(request.POST.get('next') or 'notification_list')


@login_required
@require_POST
def clear_all_notifications(request):
    deleted_count, _ = Notification.objects.filter(recipient=request.user).delete()
    messages.success(request, f'{deleted_count} notification(s) cleared.' if deleted_count else 'There are no notifications to clear.')
    return redirect('notification_list')


@login_required
def notification_status(request):
    notifications = Notification.objects.filter(recipient=request.user).values('id', 'title', 'message', 'is_read', 'created_at')[:8]
    return JsonResponse({'unread_count': Notification.objects.filter(recipient=request.user, is_read=False).count(),
                         'notifications': list(notifications)})
