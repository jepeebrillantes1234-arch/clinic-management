from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clinic.decorators import role_required
from clinic.models import ActivityLog, DispenseRecord, Medicine, MedicineRecord, Nurse, Student
from clinic.services import create_activity_log, notify_admins, user_role

TRASH_MODELS = {
    'student': (Student, 'Student'),
    'medicine': (Medicine, 'Medicine'),
    'medicine_record': (MedicineRecord, 'Medicine record'),
    'nurse': (Nurse, 'Assistant'),
    'activity': (ActivityLog, 'Activity log'),
    'dispense_record': (DispenseRecord, 'Dispense record'),
}


def _record(record_type, pk):
    model, label = TRASH_MODELS.get(record_type, (None, None))
    return (get_object_or_404(model, pk=pk), label) if model else (None, None)


def _log_student_action(request, student, action):
    role = getattr(getattr(request.user, 'profile', None), 'role', 'unknown').title()
    ActivityLog.objects.create(user=request.user, category='student', action=action, details=student.full_name,
        description=f'{request.user.get_full_name() or request.user.username} ({role}) {action.lower()}: {student.full_name}.')


@login_required
@role_required('admin')
def trash_list(request):
    query = request.GET.get('q', '').strip().lower()
    selected_type = request.GET.get('type', '').strip()
    selected_date = request.GET.get('date', '').strip()
    records = []
    for record_type, (model, label) in TRASH_MODELS.items():
        if selected_type and record_type != selected_type:
            continue
        for item in model.objects.filter(is_deleted=True):
            deleted_at = getattr(item, 'deleted_at', None)
            if query and query not in str(item).lower():
                continue
            if selected_date and (not deleted_at or deleted_at.date().isoformat() != selected_date):
                continue
            deleted_by = getattr(item, 'deleted_by', None)
            deleted_by_name = 'System'
            if deleted_by:
                deleted_by_name = deleted_by.get_full_name() or deleted_by.username
            records.append({'type': record_type, 'label': label, 'pk': item.pk, 'name': str(item),
                            'deleted_by_name': deleted_by_name, 'deleted_at': deleted_at})
    records.sort(key=lambda item: item['deleted_at'] or timezone.now(), reverse=True)
    counts = {'total': len(records), 'students': sum(r['type'] == 'student' for r in records),
              'medicines': sum(r['type'] == 'medicine' for r in records)}
    counts['other'] = counts['total'] - counts['students'] - counts['medicines']
    return render(request, 'clinic/trash.html', {'records': records, 'query': request.GET.get('q', '').strip(),
        'selected_type': selected_type, 'selected_date': selected_date, 'counts': counts,
        'record_types': [(key, value[1]) for key, value in TRASH_MODELS.items()]})


@login_required
@role_required('admin', 'nurse')
@require_POST
def move_to_trash(request, record_type, pk):
    record, label = _record(record_type, pk)
    if record is None:
        messages.error(request, 'Invalid record type.')
    elif not record.is_deleted:
        record.is_deleted, record.deleted_at, record.deleted_by = True, timezone.now(), request.user
        record.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        if record_type == 'student':
            _log_student_action(request, record, 'Student moved to Recycle Bin')
        messages.success(request, 'Successfully moved to Recycle Bin.')
    return redirect(request.POST.get('next') or 'dashboard')


@login_required
@role_required('admin')
@require_POST
def restore_from_trash(request, record_type, pk):
    record, label = _record(record_type, pk)
    if record is None or not record.is_deleted:
        messages.error(request, 'Record was not found in the Recycle Bin.')
    else:
        record.is_deleted, record.deleted_at, record.deleted_by = False, None, None
        record.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        create_activity_log(user=request.user, action='Restored record', module='Recycle Bin', affected_record=str(record), description=f'{user_role(request.user)} restored {record} from the Recycle Bin.', request=request)
        notify_admins(title='Record Restored', message=f'Admin restored {record} from the Recycle Bin.', notification_type='recycle_bin', module=label, related_object_id=record.pk, exclude_user=request.user)
        messages.success(request, 'Record successfully restored.')
    return redirect('trash_list')


@login_required
@role_required('admin')
@require_POST
def permanently_delete(request, record_type, pk):
    record, label = _record(record_type, pk)
    if record is None or not record.is_deleted:
        messages.error(request, 'Only Recycle Bin records can be permanently deleted.')
    else:
        record_name = str(record)
        create_activity_log(user=request.user, action='Permanently deleted record', module='Recycle Bin', affected_record=record_name, description=f'{user_role(request.user)} permanently deleted {record_name}.', request=request)
        notify_admins(title='Record Permanently Deleted', message=f'Admin permanently deleted {record_name}.', notification_type='recycle_bin', module=label, related_object_id=record.pk, exclude_user=request.user)
        record.delete()
        messages.success(request, 'Record permanently deleted.')
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
                record.delete()
                deleted += 1
        except (ValueError, TypeError):
            continue
    messages.success(request, f'{deleted} record(s) permanently deleted.' if deleted else 'Select at least one Recycle Bin record.')
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
                record.is_deleted, record.deleted_at, record.deleted_by = False, None, None
                record.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
                restored += 1
        except (ValueError, TypeError):
            continue
    messages.success(request, f'{restored} record(s) restored.' if restored else 'Select at least one Recycle Bin record.')
    return redirect('trash_list')
