"""
Popula o Frigobar: composição padrão por TipoUH (usa produtos com preço de venda),
garante um depósito central com saldo e registra uma conferência de exemplo numa
conta aberta (se houver). Uso: manage.py popular_frigobar [--limpar]
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.frigobar import services
from apps.frigobar.models import Conferencia, ItemComposicao
from apps.nucleo.models import (
    LocalEstoque,
    Produto,
    TipoUH,
    registrar_entrada,
    saldo,
)

Usuario = get_user_model()


class Command(BaseCommand):
    help = "Cria dados de exemplo para o Frigobar."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true")

    def handle(self, *args, **opts):
        op = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        if not op:
            self.stderr.write("Crie um superusuário antes.")
            return

        if opts["limpar"]:
            Conferencia.objects.all().delete()
            ItemComposicao.objects.all().delete()

        produtos = list(Produto.objects.filter(ativo=True, preco_venda__gt=0)[:3])
        if not produtos:
            self.stderr.write("Sem produtos com preço de venda — rode o seed de estoque.")
            return

        # Depósito central de frigobar + saldo.
        local, _ = LocalEstoque.objects.get_or_create(
            nome="Frigobar central", defaults={"modulo": "frigobar"}
        )
        for p in produtos:
            if saldo(p, local) < 50:
                registrar_entrada(p, local, 100, p.custo_medio or Decimal("1.00"), op)

        # Composição: cada tipo de quarto recebe o kit dos 3 produtos.
        n = 0
        for tipo in TipoUH.objects.all():
            for i, p in enumerate(produtos):
                ItemComposicao.objects.update_or_create(
                    tipo_uh=tipo, produto=p, defaults={"quantidade": 2 if i == 0 else 1}
                )
                n += 1

        # Conferência de exemplo numa conta aberta, se Reservas tiver alguma.
        conf_info = "nenhuma conta aberta"
        try:
            from apps.reservas.services import contas_abertas
            conta = next(iter(contas_abertas()), None)
        except Exception:
            conta = None
        if conta:
            consumos = [(produtos[0], 1), (produtos[1], 2)]
            conf = services.registrar_conferencia(op, conta, "arrumacao", consumos)
            conf_info = f"conferência #{conf.pk} (R$ {conf.total()}) no {conta.reserva.uh.numero}"

        self.stdout.write(self.style.SUCCESS(
            f"Frigobar: {n} itens de composição, depósito central abastecido, {conf_info}."
        ))
