from django import forms

class AddTemplateForm(forms.Form):
    template_name = forms.CharField(max_length=50)
    namespace_prefix = forms.CharField(max_length=20)
    root_element = forms.CharField(max_length=55)
    file = forms.FileField()