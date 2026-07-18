"""
Popula o CRM com dados de teste coerentes para experimentar todos os módulos.

Uso:
    .venv/bin/python manage.py popular_demo

Catálogos (temporadas, tarifas, categorias, produtos, locais) usam get_or_create
e podem rodar várias vezes. Reservas, caixa, contas e recados só são criados uma
vez (marcados com "[demo]") — rodar de novo não duplica.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    Agencia,
    CategoriaFinanceira,
    CategoriaProduto,
    ContaPagarReceber,
    EntradaLogbook,
    FormaPagamento,
    Hospede,
    LancamentoFinanceiro,
    LocalEstoque,
    Pessoa,
    Produto,
    SessaoCaixa,
    Temporada,
    TipoUH,
    registrar_entrada,
)

D = Decimal


class Command(BaseCommand):
    help = "Popula o CRM com dados de teste para experimentar os módulos."

    def handle(self, *args, **options):
        self.user = self._usuario()
        self.hoje = timezone.localdate()
        self.stdout.write("Populando catálogos…")
        self._pessoas()
        self._temporadas_e_tarifas()
        self._categorias_financeiras()
        self._estoque()
        if Pessoa.objects.filter(reservas__observacoes__icontains="[demo]").exists():
            self.stdout.write(self.style.WARNING(
                "Reservas/caixa demo já existem — pulando (catálogos atualizados)."
            ))
        else:
            self.stdout.write("Criando reservas, caixa, contas e recados…")
            self._reservas_e_caixa()
            self._contas_e_lancamentos()
            self._recados()
        self.stdout.write(self.style.SUCCESS("Pronto! CRM populado para teste."))

    # ------------------------------------------------------------------

    def _usuario(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return (
            User.objects.filter(username="gvivan").first()
            or User.objects.filter(is_superuser=True).first()
        )

    def _pessoas(self):
        # Garante uma agência para faturamento e alguns hóspedes.
        ag, _ = Pessoa.objects.get_or_create(
            nome="Agência CVC", defaults={"tipo": Pessoa.Tipo.JURIDICA,
                                          "documento": "11.222.333/0001-44"}
        )
        Agencia.objects.get_or_create(pessoa=ag, defaults={"comissao_padrao": D("10")})
        for nome in ["Maria Silva", "João Pereira", "Ana Beatriz Costa",
                     "Carlos Eduardo Ramos"]:
            p, _ = Pessoa.objects.get_or_create(nome=nome)
            Hospede.objects.get_or_create(pessoa=p)

    def _temporadas_e_tarifas(self):
        from apps.reservas.models import Tarifa

        alta, _ = Temporada.objects.get_or_create(
            nome="Alta temporada (verão)",
            defaults={"classificacao": "alta",
                      "inicio": self.hoje - timedelta(days=10),
                      "fim": self.hoje + timedelta(days=60)},
        )
        Temporada.objects.get_or_create(
            nome="Feriado próximo",
            defaults={"classificacao": "feriado",
                      "inicio": self.hoje + timedelta(days=15),
                      "fim": self.hoje + timedelta(days=17)},
        )
        # Tarifa por tipo × classificação (+30% na alta, +60% no feriado).
        for tipo in TipoUH.objects.all():
            base = tipo.tarifa_base
            Tarifa.objects.get_or_create(
                tipo_uh=tipo, classificacao="alta",
                defaults={"valor": (base * D("1.30")).quantize(D("0.01"))},
            )
            Tarifa.objects.get_or_create(
                tipo_uh=tipo, classificacao="feriado",
                defaults={"valor": (base * D("1.60")).quantize(D("0.01"))},
            )

    def _categorias_financeiras(self):
        receitas = ["Hospedagem", "Loja", "Restaurante", "Lavanderia"]
        despesas = ["Insumos", "Salários", "Manutenção", "Utilidades (água/luz)"]
        for nome in receitas:
            CategoriaFinanceira.objects.get_or_create(nome=nome, tipo="receita")
        for nome in despesas:
            CategoriaFinanceira.objects.get_or_create(nome=nome, tipo="despesa")

    def _estoque(self):
        cats = {}
        for nome in ["Bebidas", "Alimentos", "Limpeza", "Frigobar"]:
            cats[nome], _ = CategoriaProduto.objects.get_or_create(nome=nome)
        locais = {"Almoxarifado central": "nucleo"}
        for nome, mod in [("Depósito da Loja", "loja"),
                          ("Frigobar central", "frigobar"),
                          ("Cozinha/Restaurante", "restaurante")]:
            locais[nome] = mod
        for nome, mod in locais.items():
            LocalEstoque.objects.get_or_create(nome=nome, defaults={"modulo": mod})
        almox = LocalEstoque.objects.get(nome="Almoxarifado central")

        produtos = [
            ("Água mineral 500ml", "Bebidas", "un", D("1.20"), D("4.00"), D("24"), 60),
            ("Refrigerante lata", "Bebidas", "un", D("2.50"), D("7.00"), D("24"), 48),
            ("Cerveja long neck", "Bebidas", "un", D("3.80"), D("12.00"), D("48"), 30),
            ("Barra de cereal", "Frigobar", "un", D("1.80"), D("6.00"), D("20"), 10),
            ("Amendoim pacote", "Frigobar", "pct", D("2.20"), D("8.00"), D("20"), 8),
            ("Detergente 5L", "Limpeza", "l", D("18.00"), D("0"), D("3"), 5),
            ("Café em grãos", "Alimentos", "kg", D("32.00"), D("0"), D("5"), 4),
        ]
        for nome, cat, un, custo, preco, minimo, qtd in produtos:
            p, criado = Produto.objects.get_or_create(
                nome=nome,
                defaults={"categoria": cats[cat], "unidade": un,
                          "preco_venda": preco, "estoque_minimo": D(minimo)},
            )
            if criado or not p.movimentos.exists():
                registrar_entrada(p, almox, D(qtd), custo, self.user,
                                  documento="NF demo")

    # ------------------------------------------------------------------

    @transaction.atomic
    def _reservas_e_caixa(self):
        from apps.reservas import services
        from apps.reservas.models import Reserva

        dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        pix = FormaPagamento.objects.get(tipo="pix")
        # Caixa aberto do operador para receber pagamentos/adiantamentos.
        SessaoCaixa.objects.get_or_create(
            operador=self.user, modulo="nucleo", status="aberta",
            defaults={"fundo_troco": D("200.00")},
        )

        def hosp(nome):
            return Pessoa.objects.filter(nome=nome).first()

        def quarto(num):
            return UH.objects.get(numero=f"Quarto {num:02d}")

        def cria(num, hospede, ini, fim, status=None, **extra):
            uh = quarto(num)
            diaria = services.diaria_media(
                uh.tipo, self.hoje + timedelta(days=ini), self.hoje + timedelta(days=fim)
            )
            r = Reserva.objects.create(
                uh=uh, hospede=hospede,
                checkin=self.hoje + timedelta(days=ini),
                checkout=self.hoje + timedelta(days=fim),
                valor_diaria=diaria, criado_por=self.user,
                observacoes="[demo]", **extra,
            )
            if status:
                r.status = status
                r.save()
            return r

        # Orçamento (não segura o quarto)
        cria(22, hosp("Maria Silva"), 20, 23, status=Reserva.Status.ORCAMENTO)
        # Pré-reserva futura
        cria(16, hosp("João Pereira"), 10, 13)
        # Confirmada com adiantamento
        r_conf = cria(14, hosp("Ana Beatriz Costa"), 5, 8,
                      status=Reserva.Status.CONFIRMADA)
        services.receber_adiantamento(r_conf, self.user, pix, D("300.00"))
        # Confirmada faturada por agência
        cria(17, hosp("Carlos Eduardo Ramos"), 6, 9,
             status=Reserva.Status.CONFIRMADA,
             faturamento=Reserva.Faturamento.AGENCIA,
             titular=Pessoa.objects.get(nome="Agência CVC"))
        # Hospedada (entrada feita, conta aberta com consumo)
        r_hosp = cria(9, hosp("Carlos Eduardo Ramos"), -2, 3,
                      status=Reserva.Status.CONFIRMADA)
        conta = r_hosp.fazer_checkin(self.user)
        services.lancar_na_conta(conta, "consumo", "consumo",
                                 "Frigobar — refrigerante", D("7.00"), self.user)
        services.receber_pagamento(conta, self.user, dinheiro, D("200.00"))
        # Saída concluída (paga e encerrada)
        r_out = cria(1, hosp("Maria Silva"), -3, -1,
                     status=Reserva.Status.CONFIRMADA)
        conta_out = r_out.fazer_checkin(self.user)
        services.receber_pagamento(conta_out, self.user, dinheiro, conta_out.saldo())
        r_out.fazer_checkout(self.user)
        # Cancelada e não compareceu
        r_can = cria(3, hosp("João Pereira"), 2, 4,
                     status=Reserva.Status.CONFIRMADA)
        r_can.cancelar(self.user, "Hóspede desistiu da viagem.")
        r_ns = cria(4, hosp("Ana Beatriz Costa"), -1, 1,
                    status=Reserva.Status.CONFIRMADA)
        r_ns.marcar_no_show(self.user)

        # Uma sessão de caixa fechada (para ver o histórico e a conferência).
        sess = SessaoCaixa.objects.create(
            operador=self.user, modulo="loja", fundo_troco=D("100.00")
        )
        from apps.nucleo.models import MovimentoCaixa
        MovimentoCaixa(sessao=sess, tipo="recebimento", forma_pagamento=dinheiro,
                       valor=D("45.00"), descricao="Venda balcão (demo)",
                       criado_por=self.user).save()
        sess.fechar(D("145.00"), self.user)

    def _contas_e_lancamentos(self):
        insumos = CategoriaFinanceira.objects.get(nome="Insumos", tipo="despesa")
        util = CategoriaFinanceira.objects.get(
            nome="Utilidades (água/luz)", tipo="despesa"
        )
        hosp = CategoriaFinanceira.objects.get(nome="Hospedagem", tipo="receita")
        forn = Pessoa.objects.filter(fornecedor__isnull=False).first()

        ContaPagarReceber.objects.get_or_create(
            descricao="[demo] Conta de luz", tipo="pagar", categoria=util,
            defaults={"valor": D("820.00"),
                      "vencimento": self.hoje - timedelta(days=2)},  # vencida
        )
        ContaPagarReceber.objects.get_or_create(
            descricao="[demo] Compra de hortifrúti", tipo="pagar", categoria=insumos,
            defaults={"valor": D("340.00"), "pessoa": forn,
                      "vencimento": self.hoje + timedelta(days=5)},
        )
        LancamentoFinanceiro.objects.get_or_create(
            descricao="[demo] Diárias recebidas na semana", tipo="receita",
            categoria=hosp,
            defaults={"valor": D("2450.00"), "centro": "reservas",
                      "criado_por": self.user},
        )

    def _recados(self):
        recados = [
            ("Ar-condicionado do Quarto 12 pingando — chamar manutenção.", True),
            ("Hóspede do 09 pediu late check-out para as 14h.", False),
            ("Chegou entrega de bebidas; conferir com a NF antes de guardar.", False),
        ]
        for texto, importante in recados:
            EntradaLogbook.objects.get_or_create(
                texto=texto, defaults={"autor": self.user, "importante": importante}
            )
