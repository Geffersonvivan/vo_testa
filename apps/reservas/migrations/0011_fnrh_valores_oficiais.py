"""Converte os valores antigos das fichas FNRH para os códigos oficiais da API
(GET /dominios/…), agora usados diretamente como valor dos choices."""

from django.db import migrations

MOTIVO = {
    "lazer": "LAZER_FERIAS", "negocios": "NEGOCIOS", "evento": "CONGRESSO_FEIRA",
    "saude": "SAUDE", "estudo": "ESTUDOS_CURSOS", "religiao": "RELIGIAO",
    "compras": "COMPRAS", "outro": "PARENTES_AMIGOS",
}
TRANSPORTE = {
    "carro": "AUTOMOVEL", "onibus": "ONIBUS", "aviao": "AVIAO", "moto": "MOTO",
    "outro": "AUTOMOVEL",
}
SEXO = {"F": "MULHER", "M": "HOMEM", "O": "OUTRO"}
DOCUMENTO = {
    "cpf": "CPF", "rg": "CPF", "cnh": "CPF", "certidao": "CPF",
    "passaporte": "PASSAPORTE", "outro": "CPF",
}


def para_oficiais(apps, schema_editor):
    FichaFNRH = apps.get_model("reservas", "FichaFNRH")
    for f in FichaFNRH.objects.all():
        f.motivo_viagem = MOTIVO.get(f.motivo_viagem, f.motivo_viagem or "")
        f.meio_transporte = TRANSPORTE.get(f.meio_transporte, f.meio_transporte or "")
        f.sexo = SEXO.get(f.sexo, f.sexo or "")
        f.documento_tipo = DOCUMENTO.get(f.documento_tipo, "CPF")
        f.save(update_fields=["motivo_viagem", "meio_transporte", "sexo", "documento_tipo"])


def desfazer(apps, schema_editor):
    pass  # sem volta: os códigos oficiais passam a ser o padrão


class Migration(migrations.Migration):

    dependencies = [
        ("reservas", "0010_alter_fichafnrh_documento_tipo_and_more"),
    ]

    operations = [
        migrations.RunPython(para_oficiais, desfazer),
    ]
