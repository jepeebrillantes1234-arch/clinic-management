from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clinic.medicine_suggestions import find_medicine_suggestions
from clinic.models import Medicine, MedicineBatch, MedicineRecord, MedicineRecordBatch, Student, StudentMedicalRequest
from clinic.inventory import allocate_fefo, InsufficientStock


class MedicineCategorySuggestionTests(TestCase):
    def setUp(self):
        self.fever = Medicine.objects.create(
            name="Biogesic",
            category="Fever",
            quantity_in_stock=8,
            expiration_date=date.today() + timedelta(days=30),
            minimum_suggested_age=12,
            maximum_suggested_age=15,
        )
        self.headache = Medicine.objects.create(
            name="Medicine A",
            category="Headache",
            quantity_in_stock=4,
        )

    def test_fever_and_headache_categories_match_case_insensitively(self):
        fever = find_medicine_suggestions(symptoms="fEvEr", patient_age=14)
        headache = find_medicine_suggestions(symptoms="HEADACHE", patient_age=14)
        self.assertEqual(fever["medicines"], [self.fever])
        self.assertEqual(headache["medicines"], [self.headache])

    def test_multiple_words_and_multiple_categories_match(self):
        compound = Medicine.objects.create(
            name="Combined Category Medicine",
            category="High Fever",
            quantity_in_stock=2,
        )
        result = find_medicine_suggestions(symptoms="High fever and headache", patient_age=14)
        self.assertEqual(set(result["medicines"]), {compound, self.fever, self.headache})

    def test_no_category_match_returns_helpful_message(self):
        result = find_medicine_suggestions(symptoms="toothache", patient_age=14)
        self.assertEqual(result["status"], "no_suitable_match")
        self.assertIn("No suitable medicine suggestions found", result["message"])
        self.assertEqual(result["medicines"], [])

    def test_expired_and_out_of_stock_medicines_are_not_suggested(self):
        expired = Medicine.objects.create(
            name="Expired Fever Medicine",
            category="Fever",
            quantity_in_stock=10,
            expiration_date=date.today() - timedelta(days=1),
        )
        out_of_stock = Medicine.objects.create(
            name="Empty Fever Medicine",
            category="Fever",
            quantity_in_stock=0,
        )
        result = find_medicine_suggestions(symptoms="fever", patient_age=14)
        self.assertEqual(result["medicines"], [self.fever])
        self.assertNotIn(expired, result["medicines"])
        self.assertNotIn(out_of_stock, result["medicines"])

    def test_matched_category_without_available_inventory_has_clear_status(self):
        self.fever.batches.update(quantity_in_stock=0)
        self.fever.quantity_in_stock = 0
        self.fever.save(update_fields=["quantity_in_stock"])
        result = find_medicine_suggestions(symptoms="fever", patient_age=14)
        self.assertEqual(result["status"], "no_suitable_match")
        self.assertIn("No suitable medicine suggestions found", result["message"])

    def test_age_bounds_and_contraindications_filter_suggestions(self):
        too_young = Medicine.objects.create(
            name="Adult Fever Medicine", category="Fever", quantity_in_stock=10,
            minimum_suggested_age=21, maximum_suggested_age=30,
        )
        blocked_by_allergy = Medicine.objects.create(
            name="Allergy Conflict", category="Fever", quantity_in_stock=10,
            contraindications="peanut",
        )
        result = find_medicine_suggestions(symptoms="fever", patient_age=14, allergies="peanut")
        self.assertEqual(result["medicines"], [self.fever])
        self.assertNotIn(too_young, result["medicines"])
        self.assertNotIn(blocked_by_allergy, result["medicines"])


class StudentMedicalRequestWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="clinic-assistant", password="test-password")
        self.user.profile.role = "nurse"
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)
        self.available = Medicine.objects.create(
            name="Manual Choice",
            category="Unrelated Category",
            quantity_in_stock=5,
        )

    def student_post_data(self, **overrides):
        data = {
            "student_id": "TEST-001",
            "last_name": "Sample",
            "first_name": "Student",
            "middle_name": "",
            "age": "19",
            "gender": "F",
            "contact_number": "09123456789",
            "address": "Clinic Test Address",
            "course": "BSIT",
            "year_level": "1st Year",
            "section": "A",
            "emergency_contact": "Emergency Contact",
            "emergency_contact_number": "09987654321",
            "reason": "unmatched reason",
            "medicine": "",
            "dosage": "1 tablet",
        }
        data.update(overrides)
        return data

    def test_suggestion_endpoint_returns_name_category_and_stock(self):
        Medicine.objects.create(name="Fever Stock", category="Fever", quantity_in_stock=12)
        Medicine.objects.create(name="Another Fever Medicine", category="Fever", quantity_in_stock=3)
        reviewed = Medicine.objects.filter(category="Fever")
        reviewed.update(suggestion_safety_reviewed=True)
        response = self.client.post(reverse("medicine_suggestions"), {"symptoms": "FEVER", "patient_age": "14"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "suggestions")
        self.assertEqual(data["suggestions"][0]["name"], "Another Fever Medicine")
        self.assertEqual(data["suggestions"][0]["category"], "Fever")
        self.assertEqual(data["suggestions"][0]["stock"], 3)
        self.assertEqual(data["suggestions"][1]["name"], "Fever Stock")
        self.assertEqual(data["primary_suggestion_id"], data["suggestions"][0]["id"])
        self.assertEqual(Medicine.objects.get(name="Fever Stock").quantity_in_stock, 12)
        self.assertEqual(MedicineRecord.objects.count(), 0)

    def test_student_form_keeps_manual_selection_and_no_medicine_option(self):
        response = self.client.get(reverse("student_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No Medicine Needed")
        self.assertContains(response, "Manual Choice")
        self.assertNotContains(response, "Known Allergies")
        self.assertNotContains(response, "Enable symptom suggestions after clinic safety review")
        self.assertNotContains(response, "Assess the student and confirm any medicine")
        self.assertNotContains(response, "I assessed and confirm the selected medicine")
        self.assertNotContains(response, "I have reviewed and confirm this student's medical request")
        self.assertNotContains(response, 'name="quantity"')

    def test_primary_suggestion_ui_defaults_first_and_supports_replacement_and_refresh(self):
        response = self.client.get(reverse("student_create"))
        self.assertContains(response, 'id="primarySuggestionCard"')
        self.assertContains(response, 'id="otherSuggestionsList"')
        self.assertContains(response, 'setSelection(currentSuggestions[0].id, "auto")')
        self.assertContains(response, 'setSelection(item.id, "manual")')
        self.assertContains(response, 'reason.addEventListener("input", scheduleUpdate)')
        self.assertContains(response, 'oldMode === "manual"')
        self.assertContains(response, 'The selected medicine is no longer available.')

    def test_manual_selection_works_without_removed_confirmations_or_quantity_field(self):
        response = self.client.post(reverse("student_create"), self.student_post_data(
            medicine=str(self.available.pk),
        ))
        self.assertEqual(response.status_code, 302)
        self.available.refresh_from_db()
        self.assertEqual(self.available.quantity_in_stock, 4)
        self.assertEqual(MedicineRecord.objects.count(), 1)
        self.assertEqual(MedicineRecord.objects.get().dosage, "1 tablet")
        self.assertEqual(MedicineRecord.objects.get().quantity, 1)
        request = StudentMedicalRequest.objects.get()
        self.assertEqual(request.medicine, self.available)
        self.assertEqual(request.medicine_name, "Manual Choice")

    def test_only_finally_selected_medicine_is_recorded_and_deducted(self):
        other_suggestion = Medicine.objects.create(
            name="Other Fever Choice", category="Fever", quantity_in_stock=9,
        )
        final_choice = Medicine.objects.create(
            name="Final Fever Choice", category="Fever", quantity_in_stock=6,
        )
        response = self.client.post(reverse("student_create"), self.student_post_data(
            reason="fever",
            medicine=str(final_choice.pk),
        ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MedicineRecord.objects.count(), 1)
        self.assertEqual(MedicineRecord.objects.get().medicine, final_choice)
        final_choice.refresh_from_db()
        other_suggestion.refresh_from_db()
        self.assertEqual(final_choice.quantity_in_stock, 5)
        self.assertEqual(other_suggestion.quantity_in_stock, 9)
        self.assertEqual(MedicineRecord.objects.get().quantity, 1)

    def test_duplicate_submit_cannot_create_duplicate_dispensing_or_deduct_twice(self):
        data = self.student_post_data(
            medicine=str(self.available.pk),
        )
        self.client.post(reverse("student_create"), data)
        self.client.post(reverse("student_create"), data)
        self.available.refresh_from_db()
        self.assertEqual(self.available.quantity_in_stock, 4)
        self.assertEqual(StudentMedicalRequest.objects.count(), 1)
        self.assertEqual(MedicineRecord.objects.count(), 1)

    def test_no_medicine_needed_saves_request_without_dispensing_or_stock_change(self):
        response = self.client.post(reverse("student_create"), self.student_post_data())
        self.assertEqual(response.status_code, 302)
        request = StudentMedicalRequest.objects.get()
        self.assertEqual(request.medicine_name, "No Medicine Needed")
        self.assertEqual(request.reason, "unmatched reason")
        self.assertEqual(MedicineRecord.objects.count(), 0)
        self.available.refresh_from_db()
        self.assertEqual(self.available.quantity_in_stock, 5)

    def test_no_medicine_needed_appears_in_student_request_details(self):
        self.client.post(reverse("student_create"), self.student_post_data())
        student = Student.objects.get(student_id="TEST-001")
        response = self.client.get(reverse("student_views", args=[student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Medical Requests")
        self.assertContains(response, "Student Information")
        self.assertContains(response, "Medicine Records")
        self.assertEqual(StudentMedicalRequest.objects.count(), 1)

    def test_actual_selection_needs_no_removed_confirmation_checkbox(self):
        response = self.client.post(reverse("student_create"), self.student_post_data(
            medicine=str(self.available.pk),
        ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentMedicalRequest.objects.count(), 1)
        self.assertEqual(MedicineRecord.objects.count(), 1)
        self.available.refresh_from_db()
        self.assertEqual(self.available.quantity_in_stock, 4)

    def test_expired_or_stale_selected_medicine_is_rejected_clearly(self):
        expired = Medicine.objects.create(
            name="Expired Choice",
            category="Fever",
            quantity_in_stock=4,
            expiration_date=date.today() - timedelta(days=1),
        )
        response = self.client.post(reverse("student_create"), self.student_post_data(
            medicine=str(expired.pk),
        ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(MedicineRecord.objects.count(), 0)
        expired.refresh_from_db()
        self.assertEqual(expired.quantity_in_stock, 4)
        form_response = self.client.get(reverse("student_create"))
        self.assertContains(form_response, "selected medicine is no longer available")

    def test_invalidated_automatic_selection_requires_new_choice(self):
        response = self.client.post(reverse("student_create"), self.student_post_data(
            medicine_selection_valid="false",
        ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentMedicalRequest.objects.count(), 0)
        form_response = self.client.get(reverse("student_create"))
        self.assertContains(form_response, "previous medicine selection is no longer valid")


class MedicineFormCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="medicine-editor", password="test-password")
        self.user.profile.role = "nurse"
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)

    def test_medicine_form_exposes_category_age_limits_and_dosage_instructions(self):
        response = self.client.get(reverse("medicine_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="category"')
        self.assertContains(response, 'name="indications"')
        self.assertContains(response, 'name="contraindications"')
        self.assertContains(response, 'name="minimum_suggested_age"')
        self.assertContains(response, 'name="maximum_suggested_age"')
        self.assertContains(response, 'name="approved_dosage_instructions"')
        list_response = self.client.get(reverse("medicine_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Suggested Age")
        self.assertContains(list_response, "Approved Dosage Instructions")

    def test_editing_category_preserves_legacy_suggestion_values(self):
        medicine = Medicine.objects.create(
            name="Legacy Medicine",
            category="Old Category",
            indications="old symptoms",
            contraindications="legacy caution",
            minimum_suggested_age=10,
            maximum_suggested_age=80,
            approved_dosage_instructions="legacy directions",
            suggestion_safety_reviewed=True,
        )
        response = self.client.post(reverse("medicine_edit", args=[medicine.pk]), {
            "name": medicine.name,
            "category": "Fever",
            "quantity_in_stock": "7",
            "unit": "tablets",
            "low_stock_threshold": "2",
        })
        self.assertEqual(response.status_code, 302)
        medicine.refresh_from_db()
        self.assertEqual(medicine.category, "Fever")
        self.assertEqual(medicine.indications, "old symptoms")
        self.assertEqual(medicine.contraindications, "legacy caution")
        self.assertEqual(medicine.minimum_suggested_age, 10)
        self.assertEqual(medicine.approved_dosage_instructions, "legacy directions")
        self.assertTrue(medicine.suggestion_safety_reviewed)

    def test_create_medicine_saves_age_limits_and_optional_dosage(self):
        response = self.client.post(reverse("medicine_create"), {
            "name": "Age Range Medicine",
            "category": "Fever",
            "minimum_suggested_age": "12",
            "maximum_suggested_age": "15",
            "approved_dosage_instructions": "Use only clinic-approved directions.",
            "quantity_in_stock": "4",
            "unit": "tablets",
            "expiration_date": "",
            "low_stock_threshold": "1",
        })
        self.assertEqual(response.status_code, 302)
        medicine = Medicine.objects.get(name="Age Range Medicine")
        self.assertEqual(medicine.minimum_suggested_age, 12)
        self.assertEqual(medicine.maximum_suggested_age, 15)
        self.assertEqual(medicine.approved_dosage_instructions, "Use only clinic-approved directions.")


class MedicineBatchInventoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="batch-editor", password="test-password")
        self.user.profile.role = "nurse"
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)

    def test_fefo_allocation_uses_earliest_expiration_and_keeps_audit_rows(self):
        medicine = Medicine.objects.create(name="Batch Test")
        later = MedicineBatch.objects.create(medicine=medicine, batch_number="LATE", quantity_in_stock=8,
            unit="pcs", expiration_date=date.today() + timedelta(days=90))
        earlier = MedicineBatch.objects.create(medicine=medicine, batch_number="EARLY", quantity_in_stock=3,
            unit="pcs", expiration_date=date.today() + timedelta(days=10))
        medicine.quantity_in_stock = 11
        medicine.save(update_fields=["quantity_in_stock"])
        allocations = allocate_fefo(medicine, 5)
        self.assertEqual([(batch.pk, qty) for batch, qty in allocations], [(earlier.pk, 3), (later.pk, 2)])
        record = MedicineRecord.objects.create(student=Student.objects.create(
            student_id="BATCH-STU", full_name="Batch Student", age=20, gender="F", address="A",
            contact_number="1", course="C", year_level="1", emergency_contact="E", emergency_contact_number="12345678901"),
            medicine=medicine, medicine_name=medicine.name, quantity=5)
        MedicineRecordBatch.objects.bulk_create([MedicineRecordBatch(medicine_record=record, batch=batch, quantity=qty)
            for batch, qty in allocations])
        medicine.refresh_from_db()
        self.assertEqual(medicine.quantity_in_stock, 6)
        self.assertEqual(record.batch_allocations.count(), 2)

    def test_expired_batches_are_unavailable_and_never_deducted(self):
        medicine = Medicine.objects.create(name="Expired Batch Test")
        expired = MedicineBatch.objects.create(medicine=medicine, quantity_in_stock=4, unit="pcs",
            expiration_date=date.today() - timedelta(days=1))
        medicine.quantity_in_stock = 4
        medicine.save(update_fields=["quantity_in_stock"])
        with self.assertRaises(InsufficientStock):
            allocate_fefo(medicine, 1)
        expired.refresh_from_db()
        self.assertEqual(expired.quantity_in_stock, 4)

    def test_edit_medicine_updates_age_limits_and_instructions(self):
        medicine = Medicine.objects.create(name="Editable Medicine", quantity_in_stock=2)
        response = self.client.post(reverse("medicine_edit", args=[medicine.pk]), {
            "name": medicine.name,
            "category": "Headache",
            "minimum_suggested_age": "18",
            "maximum_suggested_age": "25",
            "approved_dosage_instructions": "Clinic reviewed directions.",
            "quantity_in_stock": "2",
            "unit": "pcs",
            "expiration_date": "",
            "low_stock_threshold": "10",
        })
        self.assertEqual(response.status_code, 302)
        medicine.refresh_from_db()
        self.assertEqual((medicine.minimum_suggested_age, medicine.maximum_suggested_age), (18, 25))
        self.assertEqual(medicine.approved_dosage_instructions, "Clinic reviewed directions.")

    def test_invalid_age_range_is_rejected_without_creating_medicine(self):
        response = self.client.post(reverse("medicine_create"), {
            "name": "Invalid Range Medicine",
            "category": "Fever",
            "minimum_suggested_age": "16",
            "maximum_suggested_age": "12",
            "quantity_in_stock": "4",
            "unit": "pcs",
            "low_stock_threshold": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Minimum suggested age must not exceed maximum suggested age")
        self.assertFalse(Medicine.objects.filter(name="Invalid Range Medicine").exists())


class StudentAgeBasedDispensingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dispensing-assistant", password="test-password")
        self.user.profile.role = "nurse"
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)
        self.student = Student.objects.create(
            student_id="AGE-014", full_name="Student Fourteen", age=14, gender="F",
            address="Test", contact_number="09123456789", course="BSIT", year_level="1st Year",
            emergency_contact="Contact", emergency_contact_number="09987654321",
        )

    def test_pdf_downloads_are_valid_attachments_for_reports_roster_and_student(self):
        for url in (
            reverse("reports_pdf"),
            reverse("student_print_all_pdf"),
            reverse("student_pdf", args=[self.student.pk]),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertIn("attachment; filename=", response["Content-Disposition"])
            self.assertTrue(response.content.startswith(b"%PDF-1.4"))
            self.assertIn(b"%%EOF", response.content[-32:])
        roster = self.client.get(reverse("student_print_all_pdf"))
        profile = self.client.get(reverse("student_pdf", args=[self.student.pk]))
        self.assertIn(b"/MediaBox [0 0 842 595]", roster.content)
        self.assertIn(b"/MediaBox [0 0 595 842]", profile.content)
        self.assertIn(b"/Subtype /Image", profile.content)
        self.assertIn(b"/ca 0.120 /CA 0.120", profile.content)
        self.assertIn(b"/XObject << /Logo", profile.content)
        self.assertIn(b"INTERNATIONAL CLINIC OF EXCELLENCE", profile.content)
        self.assertIn(b"Urdaneta City, Pangasinan", profile.content)
        profile_content = profile.content.split(b"stream\n", 2)[-1]
        self.assertLess(profile_content.index(b"/Logo Do Q"), profile_content.index(b"INTERNATIONAL CLINIC OF EXCELLENCE"))
        self.assertIn(b"/Subtype /Image", roster.content)
        self.assertIn(b"/Logo Do Q", roster.content)
        report = self.client.get(reverse("reports_pdf"))
        self.assertIn(b"/Subtype /Image", report.content)
        self.assertIn(b"/Logo Do Q", report.content)
        self.assertIn(b"1.000 1.000 1.000 rg 0.00 0.00 842.00 595.00 re f", report.content)

        for url in (
            reverse("reports_pdf") + "?inline=1",
            reverse("student_print_all_pdf") + "?inline=1",
            reverse("student_pdf", args=[self.student.pk]) + "?inline=1",
        ):
            inline_response = self.client.get(url)
            self.assertEqual(inline_response.status_code, 200)
            self.assertIn("inline; filename=", inline_response["Content-Disposition"])

    def test_roster_pdf_repeats_column_headers_across_pages(self):
        for index in range(70):
            Student.objects.create(
                student_id=f"PDF-{index:03}", full_name=f"Student Record {index}", age=18,
                gender="F", address="Clinic address", contact_number="09123456789",
                course="Course", year_level="Year 1", emergency_contact="Contact Name",
                emergency_contact_number="09987654321",
            )
        response = self.client.get(reverse("student_print_all_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.content, rb"/Count [2-9][0-9]*")
        self.assertGreaterEqual(response.content.count(b"(Student ID) Tj"), 2)

    def test_report_pdf_contains_the_full_dashboard_sections(self):
        response = self.client.get(reverse("reports_pdf"))
        content = response.content
        self.assertIn(b"/MediaBox [0 0 842 595]", content)
        for section in (
            b"Reports & Analytics", b"TOTAL STUDENTS", b"MEDICINES IN INVENTORY",
            b"MEDICAL REQUESTS", b"TOTAL UNITS DISPENSED", b"Students by Course",
            b"Students by Year Level", b"Medical Requests by Status",
            b"Top Dispensed Medicines", b"Low Stock Medicines", b"Expiring Soon",
        ):
            self.assertIn(section, content)

    def test_student_pdf_uses_a_spaced_information_card(self):
        response = self.client.get(reverse("student_pdf", args=[self.student.pk]))
        self.assertIn(b"STUDENT INFORMATION", response.content)
        self.assertIn(b"Dispensing and Medicine Records", response.content)
        self.assertIn(b"/MediaBox [0 0 595 842]", response.content)

    def test_student_print_views_define_theme_independent_a4_print_styles(self):
        roster = self.client.get(reverse("student_print_all"))
        profile = self.client.get(reverse("student_views", args=[self.student.pk]))
        self.assertEqual(roster.status_code, 302)
        self.assertIn("inline=1", roster["Location"])
        roster_pdf = self.client.get(roster["Location"])
        self.assertEqual(roster_pdf.status_code, 200)
        self.assertEqual(roster_pdf["Content-Type"], "application/pdf")
        self.assertIn("inline; filename=", roster_pdf["Content-Disposition"])
        self.assertEqual(profile.status_code, 200)
        profile_html = profile.content.decode()
        self.assertIn("size: A4 portrait", profile_html)
        self.assertIn(".print-watermark { display: none; }", profile_html)
        for html in (profile_html,):
            self.assertIn("background-color: #fff", html)
            self.assertIn("color: #111", html)
            self.assertIn("print-color-adjust: exact", html)
            self.assertIn("display: table-header-group", html)
            self.assertIn("background-color: #dbeafe", html)
            self.assertIn("color: #123b68", html)

        print_response = self.client.get(reverse("student_views", args=[self.student.pk]) + "?print=1")
        self.assertEqual(print_response.status_code, 302)
        self.assertIn("inline=1", print_response["Location"])

        reports = self.client.get(reverse("reports"))
        self.assertEqual(reports.status_code, 200)
        reports_html = reports.content.decode()
        self.assertIn("@page { size: A4 landscape", reports_html)
        self.assertIn('id="reports-print-area"', reports_html)
        self.assertIn("print-color-adjust: exact", reports_html)

    def test_add_record_form_renders_age_suggestion_area_and_dosage(self):
        response = self.client.get(reverse("medicine_record_create", args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student age: 14")
        self.assertContains(response, 'id="recordSuggestionList"')
        self.assertContains(response, 'name="dosage"')
        self.assertContains(response, "Select for review")
        page = response.content.decode()
        self.assertLess(page.index("Sakit / Sintomas / Dahilan"), page.index("-- Select an eligible medicine --"))

    def test_manual_dropdown_only_lists_age_stock_expiration_and_contraindication_eligible_medicines(self):
        eligible = Medicine.objects.create(name="Eligible Manual", quantity_in_stock=3)
        Medicine.objects.create(name="Adult Only", quantity_in_stock=3, minimum_suggested_age=21)
        Medicine.objects.create(name="No Stock", quantity_in_stock=0)
        Medicine.objects.create(
            name="Expired", quantity_in_stock=3, expiration_date=date.today() - timedelta(days=1),
        )
        self.student.allergies = "peanut"
        self.student.save(update_fields=["allergies"])
        Medicine.objects.create(name="Contraindicated", quantity_in_stock=3, contraindications="peanut")
        response = self.client.get(reverse("medicine_record_create", args=[self.student.pk]))
        self.assertContains(response, eligible.name)
        self.assertNotContains(response, "Adult Only")
        self.assertNotContains(response, "No Stock")
        self.assertNotContains(response, "Expired")
        self.assertNotContains(response, "Contraindicated")

    def test_suggestions_include_age_range_stock_and_dosage(self):
        medicine = Medicine.objects.create(
            name="Fever Choice", category="Fever", quantity_in_stock=6,
            minimum_suggested_age=12, maximum_suggested_age=15,
            approved_dosage_instructions="1 tablet per clinic protocol.",
        )
        response = self.client.post(reverse("medicine_suggestions"), {
            "student_pk": str(self.student.pk), "symptoms": "FEVER",
        })
        self.assertEqual(response.status_code, 200)
        item = response.json()["suggestions"][0]
        self.assertEqual(item["id"], medicine.pk)
        self.assertEqual(item["patient_age"], 14)
        self.assertEqual(item["age_range"], "12–15")
        self.assertEqual(item["dosage_instructions"], "1 tablet per clinic protocol.")
        self.assertEqual(item["stock"], 6)

    def test_suggestions_exclude_out_of_age_medicines(self):
        Medicine.objects.create(
            name="Adult Fever Choice", category="Fever", quantity_in_stock=6,
            minimum_suggested_age=21, maximum_suggested_age=30,
        )
        response = self.client.post(reverse("medicine_suggestions"), {
            "student_pk": str(self.student.pk), "symptoms": "Fever",
        })
        self.assertEqual(response.json()["status"], "no_suitable_match")
        self.assertIn("No suitable medicine suggestions found", response.json()["message"])

    def test_missing_approved_dosage_uses_review_message(self):
        Medicine.objects.create(
            name="No Directions Fever Choice", category="Fever", quantity_in_stock=3,
        )
        response = self.client.post(reverse("medicine_suggestions"), {
            "student_pk": str(self.student.pk), "symptoms": "Fever",
        })
        self.assertEqual(
            response.json()["suggestions"][0]["dosage_instructions"],
            "Dosage instructions require clinic review.",
        )

    def test_dispensing_rejects_medicine_outside_age_range(self):
        medicine = Medicine.objects.create(
            name="Age Restricted Fever Choice", category="Fever", quantity_in_stock=6,
            minimum_suggested_age=18, maximum_suggested_age=25,
        )
        response = self.client.post(reverse("medicine_record_create", args=[self.student.pk]), {
            "medicine": str(medicine.pk), "quantity": "1", "dosage": "Clinic-reviewed direction",
            "prescription": "Fever",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MedicineRecord.objects.count(), 0)
        medicine.refresh_from_db()
        self.assertEqual(medicine.quantity_in_stock, 6)

    def test_dispensing_rejects_recorded_allergy_contraindication_conflict(self):
        self.student.allergies = "peanut"
        self.student.save(update_fields=["allergies"])
        medicine = Medicine.objects.create(
            name="Contraindicated Choice", category="Fever", quantity_in_stock=6,
            contraindications="peanut",
        )
        response = self.client.post(reverse("medicine_record_create", args=[self.student.pk]), {
            "medicine": str(medicine.pk), "quantity": "1", "dosage": "Clinic-reviewed direction",
            "prescription": "Fever",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MedicineRecord.objects.count(), 0)
        medicine.refresh_from_db()
        self.assertEqual(medicine.quantity_in_stock, 6)

    def test_dosage_is_saved_separately_from_quantity(self):
        medicine = Medicine.objects.create(name="Record Medicine", quantity_in_stock=8, unit="bottles")
        self.client.post(reverse("medicine_record_create", args=[self.student.pk]), {
            "medicine": str(medicine.pk), "quantity": "2", "dosage": "5 mL after review — twice daily",
            "prescription": "Approved by clinic staff",
        })
        record = MedicineRecord.objects.get(student=self.student)
        self.assertEqual(record.dosage, "5 mL after review — twice daily")
        self.assertEqual(record.quantity, 2)
        medicine.refresh_from_db()
        self.assertEqual(medicine.quantity_in_stock, 6)
        profile_response = self.client.get(reverse("student_views", args=[self.student.pk]))
        self.assertContains(profile_response, "5 mL after review — twice daily")
        self.assertContains(profile_response, "2 bottles")
