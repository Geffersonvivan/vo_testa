"""Testes do motor de preço (Fase 6 — Manual §2 + taxas)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.nucleo.models import TipoUH
from apps.reservas import precos

CI = date(2027, 3, 2)   # segunda (fora de temporada → tarifa base)
CO = date(2027, 3, 4)   # 2 noites


@override_settings(
    PRECO_ISS_ALIQUOTA="4.0", PRECO_TAXA_TURISMO_DIARIA="4.00",
    PRECO_SINGLE_FATOR="0.70",
)
class MotorPrecoTests(TestCase):
    def setUp(self):
        self.tipo = TipoUH.objects.create(
            nome="Cabana Teste", capacidade=5, tarifa_base=Decimal("560.00"),
            pessoa_adicional=Decimal("250.00"))

    def cot(self, **kw):
        base = dict(tipo=self.tipo, checkin=CI, checkout=CO, adultos=2)
        base.update(kw)
        return precos.cotacao(**base)

    def test_base_2_pax_com_taxas(self):
        c = self.cot()
        self.assertEqual(c["hospedagem"], Decimal("1120.00"))   # 560 × 2 noites
        self.assertEqual(c["iss"], Decimal("44.80"))            # 4% por fora
        self.assertEqual(c["taxa_turismo"], Decimal("8.00"))    # R$4 × 2 noites
        self.assertEqual(c["total"], Decimal("1172.80"))

    def test_pessoa_adicional(self):
        c = self.cot(adultos=3)
        self.assertEqual(c["hospedagem"], Decimal("1620.00"))   # (560+250) × 2

    def test_single_70(self):
        c = self.cot(adultos=1)
        self.assertEqual(c["hospedagem"], Decimal("784.00"))    # 560×0.70 × 2

    def test_crianca_6_15_meia(self):
        c = self.cot(adultos=2, criancas_6_15=1)
        self.assertEqual(c["hospedagem"], Decimal("1370.00"))   # (560+125) × 2

    def test_crianca_ate_5_nao_paga(self):
        c = self.cot(adultos=2, criancas_0_5=2)
        self.assertEqual(c["hospedagem"], Decimal("1120.00"))   # igual a 2 pax

    def test_crianca_6_15_nao_dispara_single(self):
        # 1 adulto + 1 criança 6-15 não é "sozinho" → não aplica 70%.
        c = self.cot(adultos=1, criancas_6_15=1)
        self.assertEqual(c["hospedagem"], Decimal("1370.00"))   # (560+125) × 2

    def test_desmarcar_taxas(self):
        c = self.cot(cobra_iss=False, cobra_taxa_turismo=False)
        self.assertEqual(c["iss"], Decimal("0.00"))
        self.assertEqual(c["taxa_turismo"], Decimal("0.00"))
        self.assertEqual(c["total"], Decimal("1120.00"))

    def test_media_noite(self):
        c = self.cot(adultos=3)
        self.assertEqual(c["media_noite"], Decimal("810.00"))

    def test_nao_reembolsavel_desconta_12(self):
        c = self.cot(nao_reembolsavel=True, cobra_iss=False, cobra_taxa_turismo=False)
        # 1120 − 12% = 985,60; desconto 134,40.
        self.assertEqual(c["desconto_nao_reembolsavel"], Decimal("134.40"))
        self.assertEqual(c["hospedagem"], Decimal("985.60"))
        self.assertEqual(c["total"], Decimal("985.60"))

    def test_day_use_por_pessoa(self):
        day = TipoUH.objects.create(
            nome="Day Teste", capacidade=10, tarifa_base=Decimal("0.00"),
            modalidade=TipoUH.Modalidade.DAY_USE, preco_day_use=Decimal("180.00"))
        c = precos.cotacao(tipo=day, checkin=CI, checkout=CI,
                           adultos=2, criancas_6_15=1, criancas_0_5=1)
        # 2 adultos × 180 + 1 criança 6-15 × meia (90) = 450; ≤5 grátis.
        self.assertEqual(c["hospedagem"], Decimal("450.00"))
        self.assertEqual(c["taxa_turismo"], Decimal("4.00"))    # 1 diária
        self.assertEqual(c["iss"], Decimal("18.00"))            # 4% de 450
        self.assertEqual(c["total"], Decimal("472.00"))
