from decimal import Decimal

from django import forms

from apps.nucleo.models import UH, FormaPagamento, Pessoa

from .models import Acompanhante, FichaFNRH, GrupoReserva, LancamentoConta, Reserva


class DataInput(forms.DateInput):
    input_type = "date"


class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = [
            "hospede", "uh", "checkin", "checkout",
            "adultos", "criancas", "canal",
            "faturamento", "titular", "valor_diaria", "observacoes",
        ]
        widgets = {
            "checkin": DataInput(),
            "checkout": DataInput(),
            "observacoes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hospede"].queryset = Pessoa.objects.filter(ativo=True)
        self.fields["uh"].queryset = UH.objects.filter(status=UH.Status.ATIVA)
        # Titular só faz sentido quando não é particular; queryset = agências/empresas.
        self.fields["titular"].queryset = Pessoa.objects.filter(
            ativo=True, agencia__isnull=False
        )
        self.fields["titular"].required = False
        # Alpine: o campo Titular só aparece quando o faturamento não é particular.
        self.fields["faturamento"].widget.attrs["x-model"] = "fat"
        self.fields["valor_diaria"].required = False
        self.fields["valor_diaria"].help_text = (
            "Deixe em branco para usar a tarifa vigente do período."
        )

    def clean(self):
        dados = super().clean()
        faturamento = dados.get("faturamento")
        titular = dados.get("titular")
        if faturamento and faturamento != Reserva.Faturamento.PARTICULAR and not titular:
            self.add_error(
                "titular", "Escolha a agência/empresa que fatura esta reserva."
            )
        if faturamento == Reserva.Faturamento.PARTICULAR:
            dados["titular"] = None
        return dados


class LancamentoContaForm(forms.ModelForm):
    class Meta:
        model = LancamentoConta
        fields = ["tipo", "natureza", "descricao", "valor"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Diária é lançada pelo sistema (check-in/rotina), não manualmente.
        self.fields["tipo"].choices = [
            c for c in LancamentoConta.Tipo.choices
            if c[0] != LancamentoConta.Tipo.DIARIA
        ]
        self.fields["valor"].widget = forms.TextInput(attrs={
            "class": "mascara-reais", "inputmode": "numeric", "placeholder": "0,00",
        })


class RecebimentoForm(forms.Form):
    forma = forms.ModelChoiceField(
        label="Forma de pagamento",
        queryset=FormaPagamento.objects.filter(ativo=True),
    )
    valor = forms.DecimalField(
        label="Valor (R$)", min_value=Decimal("0.01"), decimal_places=2,
        widget=forms.TextInput(attrs={
            "class": "mascara-reais", "inputmode": "numeric", "placeholder": "0,00",
        }),
    )
    parcelas = forms.IntegerField(label="Parcelas", min_value=1, initial=1)
    observacao = forms.CharField(
        label="Pagador / observação (rateio)", required=False, max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Casal A, cartão do João"}),
    )


class CancelamentoForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo do cancelamento", widget=forms.Textarea(attrs={"rows": 2})
    )


class AcompanhanteForm(forms.ModelForm):
    class Meta:
        model = Acompanhante
        fields = ["nome", "documento"]


class FichaFNRHForm(forms.ModelForm):
    """Ficha Nacional de Registro de Hóspedes — uma por pessoa hospedada."""

    class Meta:
        model = FichaFNRH
        fields = [
            "nome", "nascimento", "sexo", "nacionalidade", "profissao",
            "documento_tipo", "documento_numero", "documento_emissor", "cpf",
            "pais", "cep", "endereco", "cidade", "uf", "telefone", "email",
            "motivo_viagem", "meio_transporte", "procedencia", "proximo_destino",
        ]
        widgets = {
            "nascimento": DataInput(),
        }

    # Seções da ficha (agrupamento §16): título → campos.
    GRUPOS = [
        ("Identificação", ["nome", "nascimento", "sexo", "nacionalidade", "profissao"]),
        ("Documento", ["documento_tipo", "documento_numero", "documento_emissor", "cpf"]),
        ("Endereço e contato", ["pais", "cep", "endereco", "cidade", "uf", "telefone", "email"]),
        ("Sobre a viagem", ["motivo_viagem", "meio_transporte", "procedencia", "proximo_destino"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Campos mínimos exigidos pela FNRH (espelham CAMPOS_OBRIGATORIOS do model).
        for campo in FichaFNRH.CAMPOS_OBRIGATORIOS:
            if campo in self.fields:
                self.fields[campo].required = True

    def grupos(self):
        """Campos agrupados por seção, para renderizar a ficha em blocos."""
        return [(titulo, [self[nome] for nome in nomes]) for titulo, nomes in self.GRUPOS]


# Formset: todas as fichas de uma reserva editadas juntas (um único celular
# no portal; ou a recepção). extra=0 — os slots são preparados na view.
FichaFNRHFormSet = forms.modelformset_factory(
    FichaFNRH, form=FichaFNRHForm, extra=0,
)


class GrupoForm(forms.ModelForm):
    """Abre a reserva-mãe. O titular vem do combobox de pessoa (input `titular`)."""

    class Meta:
        model = GrupoReserva
        fields = ["rotulo", "faturamento", "canal", "checkin", "checkout", "observacoes"]
        widgets = {
            "checkin": DataInput(),
            "checkout": DataInput(),
            "observacoes": forms.Textarea(attrs={"rows": 2}),
        }
