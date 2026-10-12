from django.db import migrations, models


def popular_adultos(apps, schema_editor):
    """Leads antigos só tinham `hospedes` (total). Preenche `adultos` com o total
    (crianças seguem 0 até a vendedora ajustar a composição na ficha).

    DEFENSIVO — nunca mexe num lead já captado que alguém tenha ajustado: só repovoa
    linhas ainda no default do campo (adultos=2, vindo do 0016) cujo total difere de 2.
    `criancas`/`idades` já nascem no default correto, não toco."""
    Oportunidade = apps.get_model("comercial", "Oportunidade")
    (Oportunidade.objects
        .filter(adultos=2)
        .exclude(hospedes=2)
        .exclude(hospedes__isnull=True)
        .update(adultos=models.F("hospedes")))


def reverter(apps, schema_editor):
    # Sem reversão de dados — os campos são apenas repovoados.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("comercial", "0016_oportunidade_adultos_oportunidade_criancas_and_more"),
    ]

    operations = [
        migrations.RunPython(popular_adultos, reverter),
    ]
