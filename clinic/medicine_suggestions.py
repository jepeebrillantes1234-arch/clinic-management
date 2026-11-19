"""Age and inventory aware medicine suggestions for clinic staff assessment."""

import re
from django.utils import timezone

from clinic.models import Medicine


NO_SUITABLE_MESSAGE = "No suitable medicine suggestions found. Please consult the clinic staff."


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _phrase_matches(text, phrase):
    normalized_phrase = _normalize(phrase)
    return bool(normalized_phrase and f" {normalized_phrase} " in f" {_normalize(text)} ")


def medicine_age_allowed(medicine, patient_age):
    if patient_age is None:
        return medicine.minimum_suggested_age is None and medicine.maximum_suggested_age is None
    return (
        (medicine.minimum_suggested_age is None or patient_age >= medicine.minimum_suggested_age)
        and (medicine.maximum_suggested_age is None or patient_age <= medicine.maximum_suggested_age)
    )


def _matches_symptoms(medicine, symptoms):
    if _phrase_matches(symptoms, medicine.category):
        return True
    return any(_phrase_matches(symptoms, keyword) for keyword in medicine.indications.split(","))


def medicine_contraindication_matches(medicine, allergies):
    warnings = ",".join(filter(None, [medicine.contraindications, medicine.allergy_warnings]))
    if not allergies.strip() or not warnings.strip():
        return False
    allergy_terms = [term.strip() for term in allergies.split(",") if term.strip()]
    contraindication_terms = [term.strip() for term in warnings.split(",") if term.strip()]
    return any(
        _phrase_matches(allergy, contraindication)
        or _phrase_matches(contraindication, allergy)
        for allergy in allergy_terms
        for contraindication in contraindication_terms
    )


def find_medicine_suggestions(*, symptoms, patient_age=None, allergies=""):
    """Return only reviewed, in-stock, unexpired medicines matching age and symptoms."""
    try:
        patient_age = int(patient_age) if patient_age not in (None, "") else None
    except (TypeError, ValueError):
        patient_age = None

    active_inventory = list(Medicine.objects.filter(is_deleted=False).prefetch_related("batches").order_by("name"))
    available = [
        medicine for medicine in active_inventory
        if medicine.available_stock > 0
    ]
    available_ids = [medicine.pk for medicine in available]
    eligible = [
        medicine for medicine in available
        if medicine_age_allowed(medicine, patient_age)
        and not medicine_contraindication_matches(medicine, allergies)
    ]
    eligible_ids = [medicine.pk for medicine in eligible]

    if not _normalize(symptoms):
        return {
            "status": "empty",
            "message": "Enter symptoms or a reason to see eligible clinic-reviewed suggestions.",
            "medicines": [],
            "available_medicine_ids": available_ids,
            "eligible_medicine_ids": eligible_ids,
        }
    if patient_age is None:
        return {
            "status": "age_required",
            "message": "A valid student age is required before showing medicine suggestions.",
            "medicines": [],
            "available_medicine_ids": available_ids,
            "eligible_medicine_ids": eligible_ids,
        }

    matching = [
        medicine for medicine in eligible
        if _matches_symptoms(medicine, symptoms)
    ]
    if matching:
        return {
            "status": "suggestions",
            "message": "Potential matches for clinic staff review only; this is not a diagnosis or prescription.",
            "medicines": matching,
            "available_medicine_ids": available_ids,
            "eligible_medicine_ids": eligible_ids,
        }

    return {
        "status": "no_suitable_match",
        "message": NO_SUITABLE_MESSAGE,
        "medicines": [],
        "available_medicine_ids": available_ids,
        "eligible_medicine_ids": eligible_ids,
    }
