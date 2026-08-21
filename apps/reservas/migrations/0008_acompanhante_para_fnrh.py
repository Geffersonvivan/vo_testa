"""Copia acompanhantes (legado) para fichas FNRH não titulares, preservando o
que já havia sido registrado. Uma via só: não apaga os Acompanhante."""

from django.db import migrations


def acompanhantes_para_fichas(apps, schema_editor):
    Acompanhante = apps.get_model("reservas", "Acompanhante")
    FichaFNRH = apps.get_model("reservas", "FichaFNRH")
    for a in Acompanhante.objects.all():
        ja_tem = FichaFNRH.objects.filter(
            reserva_id=a.reserva_id, titular=False, nome=a.nome
        ).exists()
        if ja_tem:
            continue
        FichaFNRH.objects.create(
            reserva_id=a.reserva_id,
            titular=False,
            nome=a.nome,
            documento_numero=a.documento or "",
            origem="recepcao",
        )


def desfazer(apps, schema_editor):
    # Não remove fichas: elas passam a ser o registro legal.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reservas", "0007_fichafnrh"),
    ]

    operations = [
        migrations.RunPython(acompanhantes_para_fichas, desfazer),
    ]
