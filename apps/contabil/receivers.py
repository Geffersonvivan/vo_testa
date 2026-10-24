"""
Sinais da camada Contábil (Etapa 2) — o núcleo NÃO depende daqui.

- Carimba `conta_contabil` em LancamentoFinanceiro e ContaPagarReceber recém-criados
  (resolve via de-para). Usa `.update()` para não disparar o próprio post_save de
  novo (sem recursão) nem poluir a trilha de auditoria.
- Quando nasce uma CategoriaFinanceira sem de-para, cria um MapeamentoContabil
  inicial (heurístico) — mantém o de-para completo e o "nunca órfão".
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.nucleo.models.financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    LancamentoFinanceiro,
)

from .classificacao import classificacao_para
from .models import ContaContabil, MapeamentoContabil
from .services import resolver_conta


@receiver(post_save, sender=LancamentoFinanceiro)
def _carimbar_lancamento(sender, instance, created, **kwargs):
    if not created or instance.conta_contabil:
        return
    conta = resolver_conta(
        tipo=instance.tipo, categoria=instance.categoria, centro=instance.centro
    )
    if conta:
        sender.objects.filter(pk=instance.pk).update(
            conta_contabil=conta.classificacao
        )


@receiver(post_save, sender=ContaPagarReceber)
def _carimbar_conta(sender, instance, created, **kwargs):
    if not created or instance.conta_contabil:
        return
    tipo = (
        CategoriaFinanceira.Tipo.DESPESA
        if instance.tipo == ContaPagarReceber.Tipo.PAGAR
        else CategoriaFinanceira.Tipo.RECEITA
    )
    conta = resolver_conta(
        tipo=tipo, categoria=instance.categoria, centro=instance.centro
    )
    if conta:
        sender.objects.filter(pk=instance.pk).update(
            conta_contabil=conta.classificacao
        )


@receiver(post_save, sender=CategoriaFinanceira)
def _garantir_depara_categoria(sender, instance, created, **kwargs):
    if not created:
        return
    if MapeamentoContabil.objects.filter(categoria=instance).exists():
        return
    classif = classificacao_para(instance.nome, instance.tipo)
    conta = ContaContabil.objects.filter(classificacao=classif).first()
    if conta:
        MapeamentoContabil.objects.create(
            conta=conta, categoria=instance, prioridade=10,
            observacao="de-para automático (categoria nova)",
        )
