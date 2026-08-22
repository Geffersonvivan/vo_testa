"""Nova área 'caixa' (operar o próprio caixa) separada de 'financeiro' (gestão).
Concede 'caixa' a quem já precisava receber dinheiro, para ninguém perder acesso:
  - gerentes (is_staff, não-super) — que tinham todas as áreas;
  - quem já tem a área 'financeiro';
  - operadores de módulos que recebem dinheiro (reservas, loja, restaurante).
Superusuário acessa tudo por bypass."""

from django.db import migrations

MODULOS_RECEBEM = ["reservas", "loja", "restaurante"]


def conceder_area_caixa(apps, schema_editor):
    Usuario = apps.get_model("nucleo", "Usuario")

    alvos = set()
    for u in Usuario.objects.filter(is_staff=True, is_superuser=False):
        alvos.add(u.pk)
    for u in Usuario.objects.all():
        if "financeiro" in (u.areas or []):
            alvos.add(u.pk)
    for u in Usuario.objects.filter(modulos__codigo__in=MODULOS_RECEBEM).distinct():
        alvos.add(u.pk)

    for u in Usuario.objects.filter(pk__in=alvos):
        areas = list(u.areas or [])
        if "caixa" not in areas:
            areas.append("caixa")
            u.areas = areas
            u.save(update_fields=["areas"])


def desfazer(apps, schema_editor):
    Usuario = apps.get_model("nucleo", "Usuario")
    for u in Usuario.objects.all():
        if "caixa" in (u.areas or []):
            u.areas = [a for a in u.areas if a != "caixa"]
            u.save(update_fields=["areas"])


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0021_trilhaauditoria_ip_and_more"),
    ]

    operations = [
        migrations.RunPython(conceder_area_caixa, desfazer),
    ]
