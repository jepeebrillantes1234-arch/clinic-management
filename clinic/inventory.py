from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from clinic.models import MedicineBatch


class InsufficientStock(Exception):
    def __init__(self, available):
        self.available = available
        super().__init__(f"Only {available} eligible units are available.")


def sync_medicine_totals(medicine):
    total = medicine.batches.aggregate(total=Sum("quantity_in_stock"))["total"] or 0
    earliest = medicine.batches.filter(quantity_in_stock__gt=0).order_by(
        F("expiration_date").asc(nulls_last=True), "pk"
    ).first()
    medicine.quantity_in_stock = total
    medicine.expiration_date = earliest.expiration_date if earliest else None
    medicine.save(update_fields=["quantity_in_stock", "expiration_date"])


@transaction.atomic
def allocate_fefo(medicine, quantity):
    today = timezone.localdate()
    batches = list(MedicineBatch.objects.select_for_update().filter(
        medicine=medicine, quantity_in_stock__gt=0
    ).filter(Q(expiration_date__isnull=True) | Q(expiration_date__gte=today)).order_by(
        F("expiration_date").asc(nulls_last=True),
        F("date_received").asc(nulls_last=True), "pk",
    ))
    available = sum(batch.quantity_in_stock for batch in batches)
    if available < quantity:
        raise InsufficientStock(available)
    remaining = quantity
    allocations = []
    for batch in batches:
        used = min(remaining, batch.quantity_in_stock)
        if used:
            batch.quantity_in_stock -= used
            batch.save(update_fields=["quantity_in_stock"])
            allocations.append((batch, used))
            remaining -= used
        if not remaining:
            break
    sync_medicine_totals(medicine)
    return allocations
