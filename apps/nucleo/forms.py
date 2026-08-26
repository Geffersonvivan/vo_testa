from decimal import Decimal, InvalidOperation

from django import forms

from .models import (
    UH,
    Agencia,
    CategoriaFinanceira,
    ConfiguracaoUH,
    ContaPagarReceber,
    EntradaLogbook,
    FormaPagamento,
    Fornecedor,
    Funcionario,
    Hospede,
    LancamentoFinanceiro,
    MovimentoCaixa,
    Pessoa,
    PosicaoCama,
    Temporada,
    TipoUH,
    centro_choices,
)


class DataInput(forms.DateInput):
    input_type = "date"
    # <input type="date"> exige o valor em ISO (yyyy-mm-dd) para pré-preencher na edição.
    def __init__(self, *a, **k):
        k.setdefault("format", "%Y-%m-%d")
        super().__init__(*a, **k)


class HoraInput(forms.TimeInput):
    input_type = "time"
    def __init__(self, *a, **k):
        k.setdefault("format", "%H:%M")
        super().__init__(*a, **k)


# ---------- Cadastros ----------


class PessoaForm(forms.ModelForm):
    class Meta:
        model = Pessoa
        fields = [
            "nome", "tipo", "documento", "email", "telefone",
            "endereco", "cidade", "uf", "cep", "observacoes", "ativo",
        ]
        widgets = {
            "observacoes": forms.Textarea(attrs={"rows": 3}),
            "documento": forms.TextInput(
                attrs={"class": "mascara-cpfcnpj", "inputmode": "numeric"}
            ),
            "telefone": forms.TextInput(
                attrs={"class": "mascara-telefone", "inputmode": "numeric"}
            ),
        }


class HospedeForm(forms.ModelForm):
    class Meta:
        model = Hospede
        fields = ["nascimento", "nacionalidade", "preferencias"]
        widgets = {
            "nascimento": DataInput(),
            "preferencias": forms.Textarea(attrs={"rows": 3}),
        }


def _brl(valor) -> str:
    """Decimal → '10.000,00' (sem R$, para preencher input)."""
    return f"{Decimal(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class FuncionarioForm(forms.ModelForm):
    """Ficha de RH do funcionário. O `salario` é sensível — a view só o inclui
    para gerência; o acesso ao sistema (login/módulos/áreas) é tratado à parte."""

    # Salário como texto mascarado (10.000,00) — parseado para Decimal no clean.
    salario = forms.CharField(
        required=False, label="salário base (R$)",
        widget=forms.TextInput(attrs={"class": "money-mask", "inputmode": "decimal", "placeholder": "0,00"}),
    )

    class Meta:
        model = Funcionario
        fields = [
            "cargo", "setor", "sexo", "admissao", "vinculo",
            "turno", "expediente_inicio", "expediente_fim",
            "intervalo_inicio", "intervalo_fim", "carga_semanal",
            "regime_horas", "compensacao_feriado", "salario",
        ]
        widgets = {
            "admissao": DataInput(),
            "expediente_inicio": HoraInput(), "expediente_fim": HoraInput(),
            "intervalo_inicio": HoraInput(), "intervalo_fim": HoraInput(),
        }

    def __init__(self, *args, ver_salario=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not ver_salario:
            self.fields.pop("salario", None)  # salário só p/ gerência
        elif getattr(self.instance, "salario", None) is not None:
            self.initial["salario"] = _brl(self.instance.salario)

    def clean_salario(self):
        raw = (self.cleaned_data.get("salario") or "").strip()
        if not raw:
            return None
        try:  # '10.000,00' → '10000.00'
            return Decimal(raw.replace(".", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise forms.ValidationError("Valor inválido — use o formato 10.000,00.")


class FornecedorForm(forms.ModelForm):
    class Meta:
        model = Fornecedor
        fields = ["atividade"]


class AgenciaForm(forms.ModelForm):
    class Meta:
        model = Agencia
        fields = ["categoria", "comissao_padrao"]


class TipoUHForm(forms.ModelForm):
    class Meta:
        model = TipoUH
        fields = ["nome", "descricao", "capacidade", "tarifa_base", "ativo"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}


class UHForm(forms.ModelForm):
    class Meta:
        model = UH
        fields = [
            "numero", "nome_tematico", "tipo", "bloco", "andar", "status",
            "pcd", "vista_lago", "varanda", "aceita_pet", "ar_condicionado",
            "tipo_cama", "diferenciais", "observacoes",
        ]
        widgets = {
            "observacoes": forms.Textarea(attrs={"rows": 2}),
            "diferenciais": forms.Textarea(attrs={"rows": 2}),
        }


class ConfiguracaoUHForm(forms.ModelForm):
    """Sofá-cama e colchões extras do quarto. A capacidade é derivada disto
    (ver `apps/nucleo/estrutura.py`) — nada aqui digita capacidade."""

    class Meta:
        model = ConfiguracaoUH
        fields = [
            "tem_sofa_cama", "sofa_adultos", "sofa_criancas",
            "sofa_idade_maxima", "max_colchoes_extras", "tarifa_colchao_extra",
        ]


# Posições de cama do quarto: adicionar/remover e escolher a montagem padrão.
PosicaoCamaFormSet = forms.inlineformset_factory(
    UH, PosicaoCama,
    fields=["nome", "montagem_padrao", "ordem"],
    extra=1, can_delete=True,
    widgets={"nome": forms.TextInput(attrs={"placeholder": "Ex.: Quarto 1"})},
)


class TemporadaForm(forms.ModelForm):
    class Meta:
        model = Temporada
        fields = ["nome", "classificacao", "inicio", "fim"]
        widgets = {"inicio": DataInput(), "fim": DataInput()}


# ---------- Caixa ----------


class AbrirCaixaForm(forms.Form):
    modulo = forms.ChoiceField(label="Caixa do módulo")
    fundo_troco = forms.DecimalField(
        label="Fundo de troco (R$)", min_value=Decimal("0.00"),
        decimal_places=2, initial=Decimal("0.00"),
    )

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Operador só abre caixa do núcleo ou de módulo que pode acessar.
        opcoes = [c for c in centro_choices()
                  if c[0] == "nucleo" or (usuario and usuario.pode_acessar(c[0]))]
        self.fields["modulo"].choices = opcoes


class MovimentoCaixaForm(forms.ModelForm):
    class Meta:
        model = MovimentoCaixa
        fields = ["tipo", "forma_pagamento", "valor", "parcelas", "descricao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Estorno tem fluxo próprio (exige origem, motivo e gerência).
        self.fields["tipo"].choices = [
            c for c in MovimentoCaixa.Tipo.choices
            if c[0] != MovimentoCaixa.Tipo.ESTORNO
        ]
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(
            ativo=True
        )
        self.fields["forma_pagamento"].required = False


class FecharCaixaForm(forms.Form):
    valor_contado = forms.DecimalField(
        label="Dinheiro contado na gaveta (R$)",
        min_value=Decimal("0.00"), decimal_places=2,
        help_text="Conferência cega: conte o dinheiro antes — o sistema aponta a diferença.",
    )
    observacoes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class EstornoForm(forms.Form):
    valor = forms.DecimalField(
        label="Valor a estornar (R$)", min_value=Decimal("0.01"), decimal_places=2
    )
    motivo = forms.CharField(
        label="Motivo do estorno", widget=forms.Textarea(attrs={"rows": 2})
    )


# ---------- Financeiro ----------


class LancamentoFinanceiroForm(forms.ModelForm):
    class Meta:
        model = LancamentoFinanceiro
        fields = ["tipo", "categoria", "centro", "descricao", "valor", "data"]
        widgets = {"data": DataInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centro"] = forms.ChoiceField(
            label="Centro de receita/custo", choices=centro_choices()
        )
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            ativo=True
        )


class ContaPagarReceberForm(forms.ModelForm):
    class Meta:
        model = ContaPagarReceber
        fields = [
            "tipo", "pessoa", "categoria", "centro", "descricao", "valor", "vencimento",
        ]
        widgets = {"vencimento": DataInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centro"] = forms.ChoiceField(
            label="Centro de receita/custo", choices=centro_choices()
        )
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            ativo=True
        )
        self.fields["pessoa"].queryset = Pessoa.objects.filter(ativo=True)


class EntradaLogbookForm(forms.ModelForm):
    class Meta:
        model = EntradaLogbook
        fields = ["texto", "importante"]
        widgets = {
            "texto": forms.Textarea(
                attrs={"rows": 3, "placeholder": "O que o próximo turno precisa saber?"}
            )
        }
