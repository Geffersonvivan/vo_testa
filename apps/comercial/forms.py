from django import forms

from apps.nucleo.models import Pessoa, TipoUH

from .models import (
    AtividadeComercial,
    Campanha,
    FichaComercial,
    GastoDiario,
    MotivoPerda,
    Oportunidade,
    PaginaCaptacao,
    RespostaRapida,
    TemplateEmail,
)


class FichaComercialForm(forms.ModelForm):
    """Copy comercial do quarto, editada no MESMO form de «Quartos & tipos».

    Capacidade, nome, preço e fotos NÃO ficam aqui (vêm da UH/ConfiguracaoUH/
    TarifaUnidade/Vitrine) — só o que a vendedora fala: resumo, indicado para,
    pontos de atenção (um por linha) e a história do nome.
    """

    pontos_atencao_txt = forms.CharField(
        label="Pontos de atenção (um por linha)", required=False,
        widget=forms.Textarea(attrs={"rows": 3,
                                     "placeholder": "Ex.: Colchão extra não cabe — espaço apertado"}),
        help_text="Avisos dados ANTES (nunca vão no texto ao cliente). Um por linha.",
    )

    class Meta:
        model = FichaComercial
        fields = ["resumo", "indicado_para", "historia_e_venda"]
        widgets = {
            "resumo": forms.TextInput(attrs={"placeholder": "Frase curta que abre a oferta"}),
            "historia_e_venda": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["pontos_atencao_txt"].initial = "\n".join(
                self.instance.pontos_atencao or [])

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.pontos_atencao = [
            linha.strip() for linha in
            self.cleaned_data.get("pontos_atencao_txt", "").splitlines() if linha.strip()
        ]
        if commit:
            obj.save()
        return obj


class RespostaRapidaForm(forms.ModelForm):
    class Meta:
        model = RespostaRapida
        fields = ["titulo", "texto", "atalho", "ordem", "ativo"]
        widgets = {"texto": forms.Textarea(attrs={"rows": 3})}


class TemplateEmailForm(forms.ModelForm):
    class Meta:
        model = TemplateEmail
        fields = ["nome", "assunto", "corpo", "ativo"]
        widgets = {"corpo": forms.Textarea(attrs={"rows": 8})}
        help_texts = {
            "corpo": "Variáveis: {primeiro_nome} {nome} {quarto} {checkin} "
                     "{checkout} {noites} {pessoas} {total}",
        }


class DataInput(forms.DateInput):
    input_type = "date"


class DataHoraInput(forms.DateTimeInput):
    input_type = "datetime-local"


class ReaisInput(forms.TextInput):
    """Campo de moeda BR: máscara 'mascara-reais' (formata ao digitar, converte no submit)."""

    def __init__(self, attrs=None):
        base = {"class": "mascara-reais", "inputmode": "numeric", "placeholder": "0,00"}
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)


class CampanhaForm(forms.ModelForm):
    class Meta:
        model = Campanha
        fields = ["nome", "codigo", "provedor", "pagina_captacao", "verba",
                  "id_externo", "ativa"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pagina_captacao"].queryset = PaginaCaptacao.objects.all()
        self.fields["pagina_captacao"].required = False


class GastoDiarioForm(forms.ModelForm):
    class Meta:
        model = GastoDiario
        fields = ["data", "valor"]
        widgets = {"data": DataInput()}


class PaginaCaptacaoForm(forms.ModelForm):
    class Meta:
        model = PaginaCaptacao
        fields = [
            "nome", "slug", "status", "tema", "tipo_interesse",
            "selo_texto", "tagline", "hero_titulo", "hero_subtitulo",
            "historia_titulo", "historia_texto",
            "oferta_titulo", "oferta_texto", "cta_texto",
            "vagas_restantes", "data_evento", "meta_leads",
            "whatsapp_destino", "meta_pixel_id", "google_tag_id",
            "faq_texto", "endereco", "mapa_embed",
        ]
        widgets = {
            "hero_subtitulo": forms.Textarea(attrs={"rows": 3}),
            "historia_texto": forms.Textarea(attrs={"rows": 6}),
            "oferta_texto": forms.Textarea(attrs={"rows": 3}),
            "faq_texto": forms.Textarea(attrs={"rows": 6}),
            "data_evento": DataHoraInput(),
        }


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
        help_text="Vazio = usa a tarifa do período.", widget=ReaisInput(),
    )
    criar_sinal = forms.BooleanField(
        label="Gerar cobrança de sinal (Pix)", required=False, initial=False,
        help_text="Se Pagamentos estiver ativo — 30% do valor estimado (ou informe abaixo).",
    )
    valor_sinal = forms.DecimalField(
        label="Valor do sinal (R$)", required=False, max_digits=10, decimal_places=2,
        widget=ReaisInput(),
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
        help_text="Vazio = calcula pela motor (lotação do lead + taxas).", widget=ReaisInput(),
    )
    validade = forms.DateField(label="Válida até", required=False, widget=DataInput())
    cobra_iss = forms.BooleanField(label="Incluir ISS (4%)", required=False, initial=True)
    cobra_taxa_turismo = forms.BooleanField(
        label="Incluir taxa de turismo", required=False, initial=True)
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
