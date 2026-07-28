"""
Backfill da janela de bloqueio nas OS que já bloqueavam quarto e migração do
modelo antigo (UH.status = BLOQUEADA) para o bloqueio POR DATAS.

Para cada OS aberta/em andamento que bloqueia um quarto:
  - início = agendada_para ou a data em que a OS foi aberta;
  - fim    = previsto_para (ou vazio = até concluir);
  - o quarto correspondente volta para ATIVA — a indisponibilidade passa a vir
    da janela de datas (consultada pelo Reservas), não mais do UH.status.
Quartos BLOQUEADA sem OS (bloqueio manual) são preservados.
"""
from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    OrdemServico = apps.get_model("manutencao", "OrdemServico")
    UH = apps.get_model("nucleo", "UH")

    abertas = OrdemServico.objects.filter(
        bloqueia_uh=True, uh__isnull=False,
        status__in=["aberta", "em_andamento"],
    )
    uhs_com_os = set()
    for o in abertas:
        if o.bloqueio_inicio is None:
            base = o.agendada_para or timezone.localtime(o.aberta_em).date()
            o.bloqueio_inicio = base
            o.bloqueio_fim = o.previsto_para or None
            o.save(update_fields=["bloqueio_inicio", "bloqueio_fim"])
        uhs_com_os.add(o.uh_id)

    # Solta o UH.status legado dos quartos que agora são governados pela janela.
    UH.objects.filter(pk__in=uhs_com_os, status="bloqueada").update(status="ativa")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("manutencao", "0003_ordemservico_bloqueio_fim_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
