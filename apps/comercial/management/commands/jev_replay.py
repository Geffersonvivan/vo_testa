"""Mede a previsão do gateway de decisão vs. o desfecho REAL, nas oportunidades já
fechadas (ganhas/perdidas). Read-only — não grava nada. Serve pra avaliar a Fase 0
(sombra) do piloto Jev antes de expor qualquer coisa na tela.

Uso:
    python manage.py jev_replay [--faturamento particular] [--limite 500]

Compara o score previsto (0–100 → prob 0–1) com o resultado (ganha=1, perdida=0):
- score médio previsto para GANHAS vs PERDIDAS (quanto maior a separação, melhor);
- Brier score (quanto menor, melhor calibrado);
- acurácia do canal sugerido não é medida aqui (não há "canal que converteu" gravado).
"""
from django.core.management.base import BaseCommand

from apps.comercial import services
from apps.comercial.decisao_gateway import get_decisao_gateway
from apps.comercial.models import Oportunidade


class Command(BaseCommand):
    help = "Replay do gateway de decisão nas oportunidades fechadas (avaliação da Fase 0)."

    def add_arguments(self, parser):
        parser.add_argument("--faturamento", default="", help="filtra por faturamento")
        parser.add_argument("--limite", type=int, default=1000, help="máx. de oportunidades")

    def handle(self, *args, **opts):
        gw = get_decisao_gateway()
        qs = Oportunidade.objects.filter(
            status__in=[Oportunidade.Status.GANHA, Oportunidade.Status.PERDIDA]
        ).select_related("pessoa", "pagina_captacao").order_by("-fechado_em")
        if opts["faturamento"]:
            qs = qs.filter(faturamento=opts["faturamento"])
        qs = qs[: opts["limite"]]

        n = n_ganha = n_perd = 0
        soma_ganha = soma_perd = 0.0
        brier = 0.0
        sem_score = 0
        for op in qs:
            res = None
            try:
                res = gw.avaliar_lead(services.features_lead(op))
            except Exception:  # noqa: BLE001
                res = None
            if not res or res.get("score") is None:
                sem_score += 1
                continue
            n += 1
            pred = res["score"] / 100.0
            ganhou = 1.0 if op.status == Oportunidade.Status.GANHA else 0.0
            brier += (pred - ganhou) ** 2
            if ganhou:
                n_ganha += 1
                soma_ganha += res["score"]
            else:
                n_perd += 1
                soma_perd += res["score"]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nReplay — gateway '{gw.nome}' · {n} oportunidades avaliadas "
            f"(sem score: {sem_score})"))
        if not n:
            self.stdout.write("Nada a medir (sem oportunidades fechadas com score).")
            return
        media_g = soma_ganha / n_ganha if n_ganha else 0
        media_p = soma_perd / n_perd if n_perd else 0
        self.stdout.write(f"  Ganhas   : {n_ganha:>4}  · score médio previsto {media_g:5.1f}")
        self.stdout.write(f"  Perdidas : {n_perd:>4}  · score médio previsto {media_p:5.1f}")
        self.stdout.write(f"  Separação (ganhas − perdidas): {media_g - media_p:+.1f} "
                          "(quanto maior, melhor)")
        self.stdout.write(f"  Brier score: {brier / n:.4f}  (0 = perfeito; quanto menor, melhor)")
