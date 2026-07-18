from decimal import Decimal

from django import forms

from apps.nucleo.models import (
    CategoriaProduto,
    LocalEstoque,
    Produto,
)


class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = [
            "nome", "codigo_barras", "categoria", "unidade", "natureza",
            "preco_venda", "estoque_minimo", "ativo",
        ]
        # custo_medio é calculado pelo motor — nunca editado à mão.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaProduto.objects.filter(ativo=True)


class CategoriaProdutoForm(forms.ModelForm):
    class Meta:
        model = CategoriaProduto
        fields = ["nome", "ativo"]


class LocalEstoqueForm(forms.ModelForm):
    class Meta:
        model = LocalEstoque
        fields = ["nome", "modulo", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.nucleo.models import centro_choices

        self.fields["modulo"] = forms.ChoiceField(
            label="Vínculo (centro)", choices=centro_choices()
        )


class _ProdutoLocalBase(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True)
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)

    produto = forms.ModelChoiceField(label="Produto", queryset=Produto.objects.none())
    local = forms.ModelChoiceField(label="Local", queryset=LocalEstoque.objects.none())
    quantidade = forms.DecimalField(
        label="Quantidade", min_value=Decimal("0.001"), decimal_places=3
    )


class EntradaForm(_ProdutoLocalBase):
    custo_unitario = forms.DecimalField(
        label="Custo unitário (R$)", min_value=Decimal("0"), decimal_places=4
    )
    documento = forms.CharField(label="Documento (NF)", required=False)
    observacao = forms.CharField(label="Observação", required=False)


class SaidaForm(_ProdutoLocalBase):
    TIPOS = [
        ("saida_venda", "Saída por venda"),
        ("consumo_interno", "Consumo interno"),
        ("perda", "Perda/quebra/vencimento"),
    ]
    tipo = forms.ChoiceField(label="Motivo da saída", choices=TIPOS)
    observacao = forms.CharField(label="Observação", required=False)


class TransferenciaForm(forms.Form):
    produto = forms.ModelChoiceField(label="Produto", queryset=Produto.objects.none())
    origem = forms.ModelChoiceField(label="De", queryset=LocalEstoque.objects.none())
    destino = forms.ModelChoiceField(label="Para", queryset=LocalEstoque.objects.none())
    quantidade = forms.DecimalField(
        label="Quantidade", min_value=Decimal("0.001"), decimal_places=3
    )
    observacao = forms.CharField(label="Observação", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True)
        locais = LocalEstoque.objects.filter(ativo=True)
        self.fields["origem"].queryset = locais
        self.fields["destino"].queryset = locais


class AjusteForm(_ProdutoLocalBase):
    quantidade = forms.DecimalField(
        label="Saldo correto (contado)", min_value=Decimal("0"), decimal_places=3
    )
    motivo = forms.CharField(label="Motivo do ajuste")


class AbrirInventarioForm(forms.Form):
    local = forms.ModelChoiceField(label="Local", queryset=LocalEstoque.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)
