def low_stock_alerts(request):
    """Shared sidebar alert and user-scoped notification data."""
    if not request.user.is_authenticated:
        return {}
    from .models import Medicine, Notification
    role = getattr(getattr(request.user, 'profile', None), 'role', '')
    low_stock_medicines = [m for m in Medicine.objects.filter(is_deleted=False) if m.is_low_stock] if role in ('admin', 'nurse') else []
    
    user_notifications = Notification.objects.filter(recipient=request.user)
    notifications = user_notifications.order_by('-created_at')[:8]
    unread_count = user_notifications.filter(is_read=False).count()
    
    return {
        'nav_low_stock_medicines': low_stock_medicines,
        'nav_low_stock_count': len(low_stock_medicines),
        'nav_notifications': notifications,
        'nav_unread_notification_count': unread_count,
    }