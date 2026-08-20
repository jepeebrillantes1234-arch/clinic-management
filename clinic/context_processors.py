def low_stock_alerts(request):
    """Ginagawang available ang low-stock medicine data sa LAHAT ng templates,
    para gumana ang notification bell/popup kahit anong page ang binibisita."""
    if not request.user.is_authenticated:
        return {}

    try:
        role = request.user.profile.role
    except AttributeError:
        role = 'student'

    if role not in ('admin', 'nurse'):
        return {}

    from .models import Medicine

    low_stock_medicines = [m for m in Medicine.objects.all() if m.is_low_stock]

    return {
        'nav_low_stock_medicines': low_stock_medicines,
        'nav_low_stock_count': len(low_stock_medicines),
    }