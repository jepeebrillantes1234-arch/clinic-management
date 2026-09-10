from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clinic.decorators import role_required
from clinic.models import ActivityLog, DispenseRecord, Medicine, MedicineRecord, Nurse, Student

TRASH_MODELS = {
    'student': (Student, 'Student'),
    'medicine': (Medicine, 'Medicine'),
    'medicine_record': (MedicineRecord, 'Medicine record'),
    'nurse': (Nurse, 'Nurse'),
    'activity': (ActivityLog, 'Activity log'),
    'dispense_record': (DispenseRecord, 'Dispense record'),
}


def _record(record_type, pk):
    model, label = TRASH_MODELS.get(record_type, (None, None))
    if model is None:
        return None, None
    return get_object_or_404(model, pk=pk), label


def _log_student_action(request, student, action):
    role = getattr(getattr(request.user, 'profile', None), 'role', 'unknown').title()
    ActivityLog.objects.create(
        user=request.user, category='student', action=action, details=student.full_name,
        description=f'{request.user.get_full_name() or request.user.username} ({role}) {action.lower()}: {student.full_name}.',
    )


@login_required
@role_required('admin')
def trash_list(request):
    query = request.GET.get('q', '').strip().lower()
    records = []
    for record_type, (model, label) in TRASH_MODELS.items():
        for item in model.objects.filter(is_deleted=True).order_by('-pk'):
            if query and query not in str(item).lower():
                continue
            records.append({'type': record_type, 'label': label, 'pk': item.pk, 'name': str(item), 'deleted_by': getattr(item, 'deleted_by', None), 'deleted_at': getattr(item, 'deleted_at', None)})
    records.sort(key=lambda item: (item['label'], item['name'].lower()))
    return render(request, 'clinic/trash.html', {'records': records, 'query': request.GET.get('q', '').strip()})


@login_required
@role_required('admin')
@require_POST
def move_to_trash(request, record_type, pk):
    record, label = _record(record_type, pk)
    if record is None:
        messages.error(request, 'Invalid record type.')
    elif record_type != 'student':
        messages.error(request, 'Use the record-specific action to move this item to the Recycle Bin.')
    elif not record.is_deleted:
        record.is_deleted, record.deleted_at, record.deleted_by = True, timezone.now(), request.user
        record.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        _log_student_action(request, record, 'Student moved to Recycle Bin')
        messages.success(request, f'{label} moved to Recycle Bin.')
    return redirect(request.POST.get('next') or 'dashboard')


@login_required
@role_required('admin')
@require_POST
def restore_from_trash(request, record_type, pk):
    record, label = _record(record_type, pk)
    if record is None or not record.is_deleted:
        messages.error(request, 'Record was not found in the Recycle Bin.')
    else:
        record.is_deleted = False
        fields = ['is_deleted']
        if record_type == 'student':
            record.deleted_at, record.deleted_by = None, None
            fields += ['deleted_at', 'deleted_by']
            _log_student_action(request, record, 'Student restored from Recycle Bin')
        record.save(update_fields=fields)
        messages.success(request, f'{label} restored from Recycle Bin.')
    return redirect('trash_list')


@login_required
@role_required('admin')
@require_POST
def permanently_delete(request, record_type, pk):
    record, label = _record(record_type, pk)
    if record is None or not record.is_deleted:
        messages.error(request, 'Only Recycle Bin records can be permanently deleted.')
    else:
        if record_type == 'student':
            _log_student_action(request, record, 'Student permanently deleted')
        record.delete()
        messages.success(request, f'{label} permanently deleted.')
    return redirect('trash_list')


@login_required
@role_required('admin')
@require_POST
def permanently_delete_selected(request):
    deleted = 0
    for value in request.POST.getlist('records'):
        try:
            record_type, pk = value.split(':', 1)
            record, _ = _record(record_type, pk)
            if record and record.is_deleted:
                if record_type == 'student':
                    _log_student_action(request, record, 'Student permanently deleted')
                record.delete()
                deleted += 1
        except (ValueError, TypeError):
            continue
    if deleted:
        messages.success(request, f'{deleted} record(s) permanently deleted.')
    else:
        messages.warning(request, 'Select at least one Recycle Bin record.')
    return redirect('trash_list')

@login_required
@role_required('admin')
@require_POST
def restore_selected(request):
    restored = 0
    for value in request.POST.getlist('records'):
        try:
            record_type, pk = value.split(':', 1)
            record, _ = _record(record_type, pk)
            if record and record.is_deleted:
                record.is_deleted = False
                fields = ['is_deleted']
                if record_type == 'student':
                    record.deleted_at, record.deleted_by = None, None
                    fields += ['deleted_at', 'deleted_by']
                    _log_student_action(request, record, 'Student restored from Recycle Bin')
                record.save(update_fields=fields)
                restored += 1
        except (ValueError, TypeError):
            continue
    messages.success(request, f'{restored} record(s) restored.' if restored else 'Select at least one Recycle Bin record.')
    return redirect('trash_list')
