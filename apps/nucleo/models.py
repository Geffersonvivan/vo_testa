from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models

from .modulos import DEPENDENCIAS, Modulo


class Usuario(AbstractUser):
    """
    Usuário do sistema (login individual por funcionário).
    Campos de RH (cargo, setor, vínculo com Funcionário) entram com o
    cadastro de pessoas; o model existe desde a 1ª migração porque
    AUTH_USER_MODEL não pode ser trocado depois.
    """

    modulos = models.ManyToManyField(
        "nucleo.ModuloContratado",
        blank=True,
        verbose_name="módulos com acesso",
        related_name="usuarios",
        help_text=(
            "Módulos que este usuário pode acessar. "
            "Superusuários acessam todos os módulos ativos."
        ),
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self):
        return self.get_full_name() or self.username

    def pode_acessar(self, codigo: str) -> bool:
        """Acesso = módulo ativo E (superusuário OU módulo atribuído no Admin)."""
        if not modulo_ativo(codigo):
            return False
        if self.is_superuser:
            return True
        return self.modulos.filter(codigo=codigo, ativo=True).exists()


class ModuloContratado(models.Model):
    """
    Registro de módulos ativos — a base do modelo comercial por módulos.
    Menus, permissões e integrações consultam esta tabela via
    `modulo_ativo()`; nunca hard-code.
    """

    codigo = models.CharField(
        "módulo", max_length=20, choices=Modulo.choices, unique=True
    )
    ativo = models.BooleanField("ativo", default=True)
    ativado_em = models.DateTimeField("ativado em", auto_now_add=True)
    desativado_em = models.DateTimeField("desativado em", null=True, blank=True)
    parametros = models.JSONField(
        "parâmetros", default=dict, blank=True,
        help_text="Configurações específicas do módulo para este cliente.",
    )

    class Meta:
        verbose_name = "módulo contratado"
        verbose_name_plural = "módulos contratados"
        ordering = ["codigo"]

    def __str__(self):
        situacao = "ativo" if self.ativo else "inativo"
        return f"{self.get_codigo_display()} ({situacao})"

    def clean(self):
        if self.ativo:
            exigidos = DEPENDENCIAS.get(self.codigo, [])
            faltando = [
                Modulo(c).label
                for c in exigidos
                if not ModuloContratado.objects.filter(codigo=c, ativo=True)
                .exclude(pk=self.pk)
                .exists()
            ]
            if faltando:
                raise ValidationError(
                    f"O módulo {Modulo(self.codigo).label} depende de: "
                    f"{', '.join(faltando)}."
                )


def modulo_ativo(codigo: str) -> bool:
    """Consulta central de ativação de módulo. Uso: modulo_ativo(Modulo.LOJA)."""
    return ModuloContratado.objects.filter(codigo=codigo, ativo=True).exists()


def modulos_ativos() -> list[str]:
    """Códigos de todos os módulos ativos, na ordem do catálogo."""
    from .modulos import APRESENTACAO

    ativos = set(
        ModuloContratado.objects.filter(ativo=True).values_list("codigo", flat=True)
    )
    return sorted(ativos, key=lambda c: APRESENTACAO.get(c, {}).get("ordem", 999))
