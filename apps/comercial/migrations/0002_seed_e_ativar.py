from django.db import migrations

ETAPAS = [
    # (nome, ordem, probabilidade, tipo)
    ("Novo lead", 10, 10, "aberta"),
    ("Contato feito", 20, 30, "aberta"),
    ("Cotação enviada", 30, 50, "aberta"),
    ("Negociação", 40, 70, "aberta"),
    ("Ganho", 50, 100, "ganho"),
    ("Perdido", 60, 0, "perdido"),
]

MOTIVOS = ["Preço", "Data indisponível", "Escolheu concorrente", "Sem resposta", "Outro"]


def semear(apps, schema_editor):
    EtapaFunil = apps.get_model("comercial", "EtapaFunil")
    MotivoPerda = apps.get_model("comercial", "MotivoPerda")
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    for nome, ordem, prob, tipo in ETAPAS:
        EtapaFunil.objects.get_or_create(
            nome=nome, defaults={"ordem": ordem, "probabilidade": prob, "tipo": tipo},
        )
    for nome in MOTIVOS:
        MotivoPerda.objects.get_or_create(nome=nome)
    ModuloContratado.objects.get_or_create(codigo="comercial", defaults={"ativo": True})


def reverter(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="comercial").delete()
    # Etapas/motivos não são apagados (podem já ter oportunidades vinculadas).


class Migration(migrations.Migration):
    dependencies = [
        ("comercial", "0001_initial"),
        ("nucleo", "0012_alter_modulocontratado_codigo"),
    ]
    operations = [
        migrations.RunPython(semear, reverter),
    ]
