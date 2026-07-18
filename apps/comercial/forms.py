from django import forms

from apps.nucleo.models import Pessoa, TipoUH

from .models import AtividadeComercial, MotivoPerda, Oportunidade


class DataInput(forms.DateInput):
    input_type = "date"


class DataHoraInput(forms.DateTimeInput):
    input_type = "datetime-local"


class OportunidadeForm(forms.ModelForm):
    class Meta:
        model = Oportunidade
        fields = [
            "pessoa", "titulo", "etapa", "faturamento", "origem",
            "valor_estimado", "checkin_previsto", "checkout_previsto",
            "quartos", "hospedes", "responsavel", "observacao",
        ]
        widgets = {
            "checkin_previsto": DataInput(),
            "checkout_previsto": DataInput(),
            "observacao": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pessoa"].queryset = Pessoa.objects.filter(ativo=True)
        self.fields["responsavel"].required = False
        self.fields["etapa"].required = False


class AtividadeForm(forms.ModelForm):
    class Meta:
        model = AtividadeComercial
        fields = ["tipo", "descricao", "quando", "concluida", "responsavel"]
        widgets = {"quando": DataHoraInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quando"].required = False
        self.fields["responsavel"].required = False


class ConversaoForm(forms.Form):
    tipo_uh = forms.ModelChoiceField(
        queryset=TipoUH.objects.all(), label="Tipo de quarto",
    )
    checkin = forms.DateField(label="Check-in", widget=DataInput())
    checkout = forms.DateField(label="Check-out", widget=DataInput())
    valor_diaria = forms.DecimalField(
        label="Diária (R$)", required=False, max_digits=10, decimal_places=2,
        help_text="Vazio = usa a tarifa do período.",
    )
    criar_sinal = forms.BooleanField(
        label="Gerar cobrança de sinal (Pix)", required=False, initial=False,
        help_text="Se Pagamentos estiver ativo — 30% do valor estimado (ou informe abaixo).",
    )
    valor_sinal = forms.DecimalField(
        label="Valor do sinal (R$)", required=False, max_digits=10, decimal_places=2,
    )

    def clean(self):
        dados = super().clean()
        ci, co = dados.get("checkin"), dados.get("checkout")
        if ci and co and co <= ci:
            raise forms.ValidationError("O check-out deve ser depois do check-in.")
        return dados


class PerdaForm(forms.Form):
    motivo = forms.ModelChoiceField(
        queryset=MotivoPerda.objects.filter(ativo=True), label="Motivo da perda",
    )


class CotacaoForm(forms.Form):
    tipo_uh = forms.ModelChoiceField(
        queryset=TipoUH.objects.all(), label="Tipo de quarto",
    )
    checkin = forms.DateField(label="Check-in", widget=DataInput())
    checkout = forms.DateField(label="Check-out", widget=DataInput())
    valor_diaria = forms.DecimalField(
        label="Diária (R$)", required=False, max_digits=10, decimal_places=2,
        help_text="Vazio = calcula pela tarifa do período (Reservas).",
    )
    validade = forms.DateField(label="Válida até", required=False, widget=DataInput())
    observacao = forms.CharField(
        label="Observação", required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean(self):
        dados = super().clean()
        ci, co = dados.get("checkin"), dados.get("checkout")
        if ci and co and co <= ci:
            raise forms.ValidationError("O check-out deve ser depois do check-in.")
        return dados


class MetaForm(forms.Form):
    valor_meta = forms.DecimalField(
        label="Meta de receita (R$)", max_digits=12, decimal_places=2, min_value=0,
    )
    oportunidades_meta = forms.IntegerField(
        label="Meta de ganhos (qtd)", min_value=0, required=False, initial=0,
    )
