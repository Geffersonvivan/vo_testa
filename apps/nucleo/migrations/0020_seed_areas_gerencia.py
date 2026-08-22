"""Concede todas as áreas-core aos gerentes atuais (is_staff, não-super), para não
perderem acesso a Quartos/Estrutura ao passar de @login_required para @requer_area.
Superusuário acessa tudo por bypass, então não precisa."""

from django.db import migrations


def conceder_areas_aos_gerentes(apps, schema_editor):
    from apps.nucleo.areas import Area

    Usuario = apps.get_model("nucleo", "Usuario")
    todas = [c for c, _ in Area.choices]
    for u in Usuario.objects.filter(is_staff=True, is_superuser=False):
        u.areas = todas
        u.save(update_fields=["areas"])


def desfazer(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0019_usuario_areas"),
    ]

    operations = [
        migrations.RunPython(conceder_areas_aos_gerentes, desfazer),
    ]
