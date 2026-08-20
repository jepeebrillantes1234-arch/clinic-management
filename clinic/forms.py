from django import forms
from .models import Nurse


class NurseForm(forms.ModelForm):
    # Hindi bahagi ng Nurse model — ginagamit lang para gumawa/i-update
    # ang login account ng nurse (User account).
    username = forms.CharField(
        required=False,
        max_length=150,
        label="Username (para sa Login)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'hal. nurse_maria'})
    )
    password = forms.CharField(
        required=False,
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Iwanang blangko para hindi baguhin'})
    )

    class Meta:
        model = Nurse
        fields = ['full_name', 'age', 'photo', 'position', 'contact_number', 'email', 'schedule']
        widgets = {
        'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buong pangalan'}),
        'age': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Edad'}),
        'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'hal. School Nurse'}),
        'contact_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09XXXXXXXXX'}),
        'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
        'schedule': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'hal. Mon-Fri, 8AM-5PM'}),
        'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
    }