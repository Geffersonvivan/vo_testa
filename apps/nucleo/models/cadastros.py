"""
Cadastros base do núcleo (ESPECIFICACAO §4.1): pessoas, estrutura física
(tipos de UH e UHs) e calendário de temporadas.

Pessoa é a base única. Hóspede, Funcionário e Fornecedor são especializações
(OneToOne). Cliente avulso = Pessoa sem especialização — o PDV referencia
Pessoa diretamente, opcional.
"""

from django.core.exceptions import ValidationError
from django.db import models


class Pessoa(models.Model):
    """Base única de pessoas: hóspedes, clientes avulsos, fornecedores, funcionários."""

    class Tipo(models.TextChoices):
        FISICA = "fisica", "Pessoa física"
        JURIDICA = "juridica", "Pessoa jurídica"

    nome = models.CharField("nome", max_length=150)
    tipo = models.CharField(
        "tipo", max_length=8, choices=Tipo.choices, default=Tipo.FISICA
    )
    documento = models.CharField(
        "CPF/CNPJ", max_length=18, blank=True,
        help_text="CPF ou CNPJ, com ou sem pontuação.",
    )
    email = models.EmailField("e-mail", blank=True)
    telefone = models.CharField("telefone", max_length=20, blank=True)
    endereco = models.CharField("endereço", max_length=200, blank=True)
    cidade = models.CharField("cidade", max_length=80, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    cep = models.CharField("CEP", max_length=9, blank=True)
    observacoes = models.TextField("observações", blank=True)
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "pessoa"
        verbose_name_plural = "pessoas"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    @property
    def sigla_tipo(self) -> str:
        return "PJ" if self.tipo == self.Tipo.JURIDICA else "PF"

    @property
    def papeis(self) -> list[str]:
        """Especializações ativas, para exibição em listas."""
        nomes = []
        if hasattr(self, "hospede"):
            nomes.append("Hóspede")
        if hasattr(self, "agencia"):
            nomes.append("Agência/Empresa")
        if hasattr(self, "funcionario"):
            nomes.append("Funcionário")
        if hasattr(self, "fornecedor"):
            nomes.append("Fornecedor")
        if hasattr(self, "prospecto") and not hasattr(self, "hospede"):
            nomes.append("Prospecto")
        return nomes


class Hospede(models.Model):
    pessoa = models.OneToOneField(
        Pessoa, on_delete=models.CASCADE, related_name="hospede",
        verbose_name="pessoa",
    )
    nascimento = models.DateField("data de nascimento", null=True, blank=True)
    nacionalidade = models.CharField(
        "nacionalidade", max_length=60, blank=True, default="Brasileira"
    )
    preferencias = models.TextField(
        "preferências", blank=True,
        help_text="Preferências do hóspede: quarto, travesseiro, restrições etc.",
    )

    class Meta:
        verbose_name = "hóspede"
        verbose_name_plural = "hóspedes"

    def __str__(self):
        return f"Hóspede: {self.pessoa.nome}"


class Prospecto(models.Model):
    """Lead do funil comercial — pessoa em prospecção, ainda não cliente.
    Ao ganhar a oportunidade, o Comercial cria o papel Hóspede (vira cliente)."""

    pessoa = models.OneToOneField(
        Pessoa, on_delete=models.CASCADE, related_name="prospecto",
        verbose_name="pessoa",
    )
    criado_em = models.DateTimeField("em prospecção desde", auto_now_add=True)

    class Meta:
        verbose_name = "prospecto"
        verbose_name_plural = "prospecção"

    def __str__(self):
        return f"Prospecto: {self.pessoa.nome}"


class Funcionario(models.Model):
    pessoa = models.OneToOneField(
        Pessoa, on_delete=models.CASCADE, related_name="funcionario",
        verbose_name="pessoa",
    )
    cargo = models.CharField("cargo", max_length=80)
    setor = models.CharField("setor", max_length=80, blank=True)
    admissao = models.DateField("data de admissão", null=True, blank=True)
    usuario = models.OneToOneField(
        "nucleo.Usuario", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="funcionario", verbose_name="usuário do sistema",
        help_text="Login deste funcionário no CRM, se tiver.",
    )

    class Meta:
        verbose_name = "funcionário"
        verbose_name_plural = "funcionários"

    def __str__(self):
        return f"{self.pessoa.nome} ({self.cargo})"


class Fornecedor(models.Model):
    pessoa = models.OneToOneField(
        Pessoa, on_delete=models.CASCADE, related_name="fornecedor",
        verbose_name="pessoa",
    )
    atividade = models.CharField(
        "ramo de atividade", max_length=100, blank=True,
        help_text="Ex.: hortifrúti, bebidas, lavanderia industrial.",
    )

    class Meta:
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"

    def __str__(self):
        return f"Fornecedor: {self.pessoa.nome}"


class Agencia(models.Model):
    """
    Agência de viagens ou empresa que reserva quartos e pode ser a titular do
    faturamento da reserva (quem paga pode não ser quem se hospeda).
    """

    class Categoria(models.TextChoices):
        AGENCIA = "agencia", "Agência de viagens"
        EMPRESA = "empresa", "Empresa"

    pessoa = models.OneToOneField(
        Pessoa, on_delete=models.CASCADE, related_name="agencia",
        verbose_name="pessoa",
    )
    categoria = models.CharField(
        "categoria", max_length=8, choices=Categoria.choices,
        default=Categoria.AGENCIA,
    )
    comissao_padrao = models.DecimalField(
        "comissão padrão (%)", max_digits=5, decimal_places=2, default=0,
        help_text="Percentual de comissão sobre reservas faturadas para esta agência.",
    )

    class Meta:
        verbose_name = "agência/empresa"
        verbose_name_plural = "agências/empresas"

    def __str__(self):
        return f"{self.get_categoria_display()}: {self.pessoa.nome}"


class TipoUH(models.Model):
    """Tipo de unidade habitacional (categoria de quarto) com tarifa base."""

    class Modalidade(models.TextChoices):
        HOSPEDAGEM = "hospedagem", "Hospedagem (pernoite)"
        DAY_USE = "day_use", "Dia na Pousada (day use)"

    nome = models.CharField("nome", max_length=80, unique=True)
    descricao = models.TextField("descrição", blank=True)
    capacidade = models.PositiveSmallIntegerField("capacidade (pessoas)", default=2)
    tarifa_base = models.DecimalField(
        "tarifa base (R$)", max_digits=10, decimal_places=2,
        help_text="Diária de referência; temporadas e acordos ajustam sobre ela.",
    )
    modalidade = models.CharField(
        "modalidade", max_length=12, choices=Modalidade.choices,
        default=Modalidade.HOSPEDAGEM,
        help_text="Hospedagem = pernoite nos 24 quartos. Day use = Dia na Pousada "
                  "(mesma reserva/conta/consumo, sem pernoite).",
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "tipo de quarto"
        verbose_name_plural = "tipos de quarto"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    @property
    def eh_day_use(self) -> bool:
        return self.modalidade == self.Modalidade.DAY_USE


class UH(models.Model):
    """Quarto (unidade habitacional). Status operacional; limpeza é da Governança."""

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        BLOQUEADA = "bloqueada", "Bloqueada"
        INATIVA = "inativa", "Inativa"

    numero = models.CharField("número/nome", max_length=20, unique=True)
    tipo = models.ForeignKey(
        TipoUH, on_delete=models.PROTECT, related_name="uhs", verbose_name="tipo"
    )
    bloco = models.CharField("bloco/área", max_length=40, blank=True)
    andar = models.CharField("andar", max_length=20, blank=True)
    status = models.CharField(
        "status operacional", max_length=10,
        choices=Status.choices, default=Status.ATIVA,
    )
    pcd = models.BooleanField(
        "acessível (PCD)",
        default=False,
        help_text="Quarto adaptado para pessoa com deficiência.",
    )
    observacoes = models.TextField("observações", blank=True)

    class Meta:
        verbose_name = "quarto"
        verbose_name_plural = "quartos"
        ordering = ["numero"]

    def __str__(self):
        return f"{self.numero} — {self.tipo.nome}"


class Temporada(models.Model):
    """Período do calendário tarifário (baixa/média/alta/super alta/feriado)."""

    class Classificacao(models.TextChoices):
        BAIXA = "baixa", "Baixa"
        MEDIA = "media", "Média"
        ALTA = "alta", "Alta"
        SUPER_ALTA = "super_alta", "Super alta"
        FERIADO = "feriado", "Feriado"

    nome = models.CharField("nome", max_length=80)
    classificacao = models.CharField(
        "classificação", max_length=12, choices=Classificacao.choices
    )
    inicio = models.DateField("início")
    fim = models.DateField("fim")

    class Meta:
        verbose_name = "temporada"
        verbose_name_plural = "temporadas"
        ordering = ["-inicio"]

    def __str__(self):
        return f"{self.nome} ({self.get_classificacao_display()})"

    def clean(self):
        if self.inicio and self.fim and self.fim < self.inicio:
            raise ValidationError("A data de fim deve ser igual ou depois do início.")
