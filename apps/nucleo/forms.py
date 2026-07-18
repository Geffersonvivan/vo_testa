from decimal import Decimal

from django import forms

from .models import (
    UH,
    Agencia,
    CategoriaFinanceira,
    ContaPagarReceber,
    EntradaLogbook,
    FormaPagamento,
    Fornecedor,
    Funcionario,
    Hospede,
    LancamentoFinanceiro,
    MovimentoCaixa,
    Pessoa,
    Temporada,
    TipoUH,
    centro_choices,
)


class DataInput(forms.DateInput):
    input_type = "date"


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


class FuncionarioForm(forms.ModelForm):
    class Meta:
        model = Funcionario
        fields = ["cargo", "setor", "admissao", "usuario"]
        widgets = {"admissao": DataInput()}


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
        fields = ["numero", "tipo", "bloco", "andar", "status", "pcd", "observacoes"]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}


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
