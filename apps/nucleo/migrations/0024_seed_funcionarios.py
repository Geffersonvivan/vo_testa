"""Onda 1 de Pessoas/Funcionários:
  - todo Usuário operacional (não-super, não-sistema `_`) sem Funcionário ganha um
    Pessoa + Funcionario ligado — assim aparece na tela de Funcionários e o acesso
    passa a derivar dele;
  - a área 'funcionarios' é concedida a gerentes (como as demais em 0020).
Superusuário acessa tudo por bypass."""

from django.db import migrations


def semear(apps, schema_editor):
    Usuario = apps.get_model("nucleo", "Usuario")
    Pessoa = apps.get_model("nucleo", "Pessoa")
    Funcionario = apps.get_model("nucleo", "Funcionario")

    for u in Usuario.objects.filter(is_superuser=False).exclude(username__startswith="_"):
        if Funcionario.objects.filter(usuario=u).exists():
            continue
        nome = (u.first_name or "").strip() or u.username
        pessoa = Pessoa.objects.create(nome=nome, email=(u.email or ""))
        Funcionario.objects.create(pessoa=pessoa, cargo="—", usuario=u)

    for u in Usuario.objects.filter(is_staff=True, is_superuser=False):
        areas = list(u.areas or [])
        if "funcionarios" not in areas:
            areas.append("funcionarios")
            u.areas = areas
            u.save(update_fields=["areas"])


def desfazer(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0023_alter_funcionario_options_funcionario_carga_semanal_and_more"),
    ]

    operations = [
        migrations.RunPython(semear, desfazer),
    ]
