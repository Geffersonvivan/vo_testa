"""Popular o Marketing com campanhas de exemplo (para ver o quadro como o protótipo).

Uso: manage.py popular_marketing [--limpar]
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.marketing import services
from apps.marketing.models import Campanha, EtapaCampanha, PecaCampanha

Usuario = get_user_model()

PESSOAS = ["Bruna Lisboa", "Rafael Prado", "Ana Vasques"]

# (nome, fase, canais, verba, responsavel_idx, dias_inicio, dur, aprovada)
CAMPANHAS = [
    ("Réveillon na Pousada", "ideia", ["Instagram", "Meta Ads"], "4200", 0, 40, 20, False),
    ("Day use de primavera", "proposta", ["Instagram", "WhatsApp"], "2600", 0, 10, 30, False),
    ("Pacote Dia das Crianças", "aprovacao", ["Meta Ads", "E-mail"], "3800", 1, 5, 20, False),
    ("Feriadão de setembro", "estruturacao", ["Google"], "5200", 2, -2, 15, True),
    ("Café colonial de domingo", "producao", ["Instagram"], "3400", 2, -5, 25, True),
    ("Lua de mel — sempre no ar", "noar", ["Meta Ads", "Instagram"], "1800", 0, -20, 60, True),
    ("Inverno nas cabanas", "encerrada", ["Google", "Meta Ads"], "4000", 1, -60, 30, True),
]

# Peças por campanha (nome, canal, dias_relativos_a_hoje, status). Espelha o protótipo:
# só 1 "sai hoje" + 2 até domingo (Próximos) e 2 vencidas (Atrasado). "af"=a_fazer,
# "ep"=em_producao, "pr"=pronta. As demais ficam fora da semana p/ não poluir a faixa.
PECAS = {
    "Lua de mel — sempre no ar": [
        ("Legenda do carrossel", "Instagram", 0, "ep"),   # sai hoje
        ("Vídeo depoimento", "Meta Ads", 6, "af"),        # até domingo
    ],
    "Feriadão de setembro": [
        ("Busca por marca", "Google", 4, "af"),           # até domingo
        ("Três estáticos", "Meta Ads", -2, "af"),         # atrasada — há 2 dias
    ],
    "Café colonial de domingo": [
        ("Stories do café", "Instagram", -1, "af"),       # atrasada — há 1 dia
        ("Reels do brunch", "Instagram", 12, "af"),
    ],
    "Day use de primavera": [("Post de abertura", "Instagram", 11, "af")],
    "Pacote Dia das Crianças": [("Convite família", "Meta Ads", 9, "af")],
    "Réveillon na Pousada": [("Teaser Réveillon", "Instagram", 30, "af")],
    "Inverno nas cabanas": [("Retrospectiva", "Google", -40, "pr")],
}
_ST = {"af": PecaCampanha.Status.A_FAZER, "ep": PecaCampanha.Status.EM_PRODUCAO,
       "pr": PecaCampanha.Status.PRONTA}


class Command(BaseCommand):
    help = "Cria campanhas de marketing de exemplo (visual do protótipo)."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true", help="Apaga as campanhas antes.")

    def handle(self, *args, **opts):
        if opts["limpar"]:
            Campanha.objects.all().delete()

        autor = (Usuario.objects.filter(is_superuser=True).first()
                 or Usuario.objects.first())
        if autor is None:
            self.stderr.write("Crie um usuário antes.")
            return

        pessoas = []
        for nome in PESSOAS:
            username = nome.lower().replace(" ", ".")
            u, _ = Usuario.objects.get_or_create(
                username=username, defaults={"first_name": nome.split()[0],
                                             "last_name": nome.split()[-1]})
            pessoas.append(u)

        hoje = timezone.localdate()
        mes = hoje.strftime("%Y-%m")
        services.definir_teto(mes, "18000")

        for nome, fase, canais, verba, ridx, di, dur, aprovada in CAMPANHAS:
            ini = hoje + timedelta(days=di)
            # O gestor (autor) não executa: pede só as iniciais; as demais são pedidas
            # por quem responde por elas. Assim o "Só os meus" do gestor não vira tudo.
            solic = autor if fase in ("ideia", "proposta") else pessoas[ridx]
            c = Campanha.objects.create(
                nome=nome, fase=fase, canais=canais,
                objetivo="Aumentar reservas no período.", publico="Casais e famílias",
                verba_prevista=Decimal(verba), responsavel=pessoas[ridx], solicitante=solic,
                inicio=ini, fim=ini + timedelta(days=dur))
            services.garantir_itens(c)
            # marca os itens manuais do portão da fase atual
            for it in list(c.checks.all()):
                services.marcar_item(it, autor, feito=True)
            EtapaCampanha.objects.create(campanha=c, texto="Briefing", feito=True)
            # uma tarefa aberta do gestor (mostra "1 tarefa sua" no Só os meus)
            EtapaCampanha.objects.create(
                campanha=c, texto="Aprovar arte", feito=False,
                dono=autor if nome == "Feriadão de setembro" else None)
            # peças espelhando o protótipo (Próximos = 1 hoje + 2 até domingo; Atrasado = 2)
            for pnome, pcanal, poffset, pst in PECAS.get(nome, []):
                PecaCampanha.objects.create(
                    campanha=c, nome=pnome, canal=pcanal,
                    data=hoje + timedelta(days=poffset), status=_ST[pst])
            if aprovada:
                c.anuncio = services._garantir_anuncio(c, autor)
                c.verba_travada = c.verba_prevista
                c.aprovada_por = autor
                c.aprovada_em = timezone.now()
                c.save()
                services.lancar_gasto(c, hoje, str(int(Decimal(verba) * Decimal("0.4"))), autor)

        self.stdout.write(self.style.SUCCESS(
            f"{len(CAMPANHAS)} campanhas de exemplo criadas. Abra /crm/marketing/."))
