from django import forms
from .models import Nurse


class NurseForm(forms.ModelForm):
    # Hindi bahagi ng Nurse model — ginagamit lang para gumawa/i-update
    # ang login account ng nurse (User account).
    username = forms.CharField(
        required=False,
        max_length=150,
        label="Username (for Login)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. nurse_maria'})
    )
    password = forms.CharField(
        required=False,
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to keep unchanged'})
    )

    class Meta:
        model = Nurse
        fields = ['full_name', 'age', 'photo', 'position', 'contact_number', 'email', 'schedule']
        widgets = {
        'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
        'age': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Age'}),
        'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Clinic Assistant'}),
        'contact_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09XXXXXXXXX'}),
        'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
        'schedule': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Mon-Fri, 8AM-5PM'}),
        'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
    }
