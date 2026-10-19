from django import forms

from .models import Camara, EventoBitacora


class EventoBitacoraForm(forms.ModelForm):
    class Meta:
        model = EventoBitacora
        fields = ["momento", "tipo", "descripcion", "ph", "ec", "volumen_litros", "foto"]
        widgets = {
            "momento": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "descripcion": forms.Textarea(attrs={"rows": 3}),
            "foto": forms.ClearableFileInput(attrs={"accept": "image/*", "capture": "environment"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["momento"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean_ph(self):
        ph = self.cleaned_data.get("ph")
        if ph is not None and not 0 <= ph <= 14:
            raise forms.ValidationError("El pH debe estar entre 0 y 14.")
        return ph


class CamaraForm(forms.ModelForm):
    class Meta:
        model = Camara
        fields = ["nombre", "tipo", "url", "url_foto", "intervalo_seg", "foto_diaria", "hora_foto"]

    def clean_hora_foto(self):
        hora = self.cleaned_data["hora_foto"]
        if not 0 <= hora <= 23:
            raise forms.ValidationError("La hora va de 0 a 23.")
        return hora

    def clean_url(self):
        url = self.cleaned_data["url"].strip()
        if not url.lower().startswith(("http://", "https://")):
            raise forms.ValidationError("La dirección tiene que empezar con http:// o https://")
        return url
