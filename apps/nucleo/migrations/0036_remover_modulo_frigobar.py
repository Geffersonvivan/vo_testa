"""Remove 100% o módulo Frigobar (a pousada não trabalha com frigobar).

Já estava dormente (desativado na 0029). Aqui: tira 'frigobar' das choices de
ModuloContratado.codigo, apaga a linha do módulo, e **dropa as tabelas** do app
(que saiu do INSTALLED_APPS neste mesmo commit — por isso a limpeza mora no núcleo
via RunSQL, não num DeleteModel do app removido). Sem FK externa para essas tabelas,
o DROP é seguro. Reverse é no-op (não recria dados).
"""
from django.db import migrations, models


def deletar_modulo(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="frigobar").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0035_alter_modulocontratado_codigo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="modulocontratado",
            name="codigo",
            field=models.CharField(
                choices=[
                    ("reservas", "Reservas"), ("governanca", "Governança"),
                    ("manutencao", "Manutenção"), ("escala", "Escala"),
                    ("estoque", "Estoque"), ("loja", "Loja"),
                    ("restaurante", "Restaurante Piscina"), ("lavanderia", "Lavanderia"),
                    ("pagamentos", "Pagamentos Online"), ("appsite", "APP/Site"),
                    ("crm_hospede", "CRM do Hóspede"), ("canais", "Canais/OTAs"),
                    ("fiscal", "Fiscal"), ("auditoria", "Auditoria"),
                    ("relatorios", "Relatórios"), ("comercial", "Comercial"),
                    ("marketing", "Marketing"),
                ],
                max_length=20, unique=True, verbose_name="módulo",
            ),
        ),
        migrations.RunPython(deletar_modulo, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS frigobar_itemconferencia CASCADE;",
                "DROP TABLE IF EXISTS frigobar_itemcomposicao CASCADE;",
                "DROP TABLE IF EXISTS frigobar_conferencia CASCADE;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DELETE FROM django_migrations WHERE app = 'frigobar';",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
