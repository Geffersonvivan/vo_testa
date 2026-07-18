from decimal import Decimal

from django.db import migrations, models


def semear_day_use(apps, schema_editor):
    TipoUH = apps.get_model("nucleo", "TipoUH")
    UH = apps.get_model("nucleo", "UH")
    tipo, _ = TipoUH.objects.get_or_create(
        nome="Dia na Pousada",
        defaults={
            "descricao": (
                "Day use: piscina, mirantes e passeio pela estrutura, "
                "sem pernoite. Mesma reserva, conta e consumo do CRM."
            ),
            "capacidade": 10,
            "tarifa_base": Decimal("180.00"),
            "modalidade": "day_use",
            "ativo": True,
        },
    )
    if tipo.modalidade != "day_use":
        tipo.modalidade = "day_use"
        tipo.capacidade = tipo.capacidade or 10
        tipo.tarifa_base = tipo.tarifa_base or Decimal("180.00")
        tipo.save()
    for i in range(1, 9):
        UH.objects.get_or_create(
            numero=f"DAY-{i:02d}",
            defaults={
                "tipo_id": tipo.pk,
                "bloco": "Day use",
                "status": "ativa",
                "observacoes": "Vaga de Dia na Pousada (não aparece no mapa dos 24 quartos).",
            },
        )


def reverter_day_use(apps, schema_editor):
    UH = apps.get_model("nucleo", "UH")
    TipoUH = apps.get_model("nucleo", "TipoUH")
    UH.objects.filter(numero__startswith="DAY-").delete()
    TipoUH.objects.filter(nome="Dia na Pousada").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nucleo", "0014_uh_pcd"),
    ]

    operations = [
        migrations.AddField(
            model_name="tipouh",
            name="modalidade",
            field=models.CharField(
                choices=[
                    ("hospedagem", "Hospedagem (pernoite)"),
                    ("day_use", "Dia na Pousada (day use)"),
                ],
                default="hospedagem",
                help_text=(
                    "Hospedagem = pernoite nos 24 quartos. Day use = Dia na Pousada "
                    "(mesma reserva/conta/consumo, sem pernoite)."
                ),
                max_length=12,
                verbose_name="modalidade",
            ),
        ),
        migrations.RunPython(semear_day_use, reverter_day_use),
    ]
