"""
Preenche a vitrine dos quartos com PADRÕES POR TIPO (ponto de partida para revisão):
- nome temático na voz da marca (ofícios de outrora, como os 6 quartos originais);
- qualidades padrão por tipo (vista lago, varanda, pet, ar, tipo de cama);
- foto herdada do card do tipo (a mesma que já aparece no site).
O tour 360° NÃO é tocado (não temos os links). Só altera quartos AINDA NÃO editados
(nome_tematico vazio) — assim, o que a recepção ajustar na tela é preservado.

Uso: manage.py popular_vitrine
"""
from django.core.management.base import BaseCommand

from apps.nucleo.models import UH, TipoUH
from apps.site.models import Quarto, VitrineQuarto

# Nomes temáticos por tipo (mesmo espírito de Cabine do Navegador, Oficina do
# Relojoeiro, Torre do Astrônomo…). São SUGESTÕES — a recepção renomeia à vontade.
NOMES_POR_TIPO = {
    "Cabana Hobbit": [
        "Toca do Lenhador", "Refúgio do Jardineiro", "Casa do Contador de Histórias",
    ],
    "Cabana Intermediária": [
        "Cabine do Navegador", "Torre do Astrônomo", "Estância do Pescador",
        "Mirante do Faroleiro", "Recanto do Apicultor", "Morada do Ceramista",
    ],
    "Intermediário": [
        "Oficina do Relojoeiro", "Ateliê do Ferreiro", "Estúdio da Cartógrafa",
        "Gabinete do Inventor",
    ],
    "Padrão": [
        "Vagão do Maquinista", "Quarto do Tipógrafo", "Casa do Boticário",
        "Sótão do Alfaiate", "Loja do Perfumista", "Camarim do Luthier",
        "Forja do Ourives", "Celeiro do Moleiro", "Oficina do Tecelão",
        "Ateliê do Marceneiro", "Quarto do Cronista",
    ],
}

# Qualidades padrão por tipo (starter — a recepção corrige por quarto).
PADROES_POR_TIPO = {
    "Padrão": dict(ar_condicionado=True, tipo_cama="casal"),
    "Intermediário": dict(ar_condicionado=True, varanda=True, tipo_cama="queen"),
    "Cabana Intermediária": dict(
        ar_condicionado=True, varanda=True, vista_lago=True,
        aceita_pet=True, tipo_cama="queen",
    ),
    "Cabana Hobbit": dict(
        varanda=True, vista_lago=True, aceita_pet=True, tipo_cama="casal",
    ),
}

QUALIDADES = ["vista_lago", "varanda", "aceita_pet", "ar_condicionado", "tipo_cama"]


class Command(BaseCommand):
    help = "Aplica nome temático, qualidades e foto padrão por tipo (só quartos não editados)."

    def handle(self, *args, **opts):
        nomeados = qualif = fotos = 0
        for tipo in TipoUH.objects.filter(modalidade=TipoUH.Modalidade.HOSPEDAGEM):
            nomes = list(NOMES_POR_TIPO.get(tipo.nome, []))
            padrao = PADROES_POR_TIPO.get(tipo.nome, {})
            # Foto do card do tipo (a que já aparece hoje no site), se houver.
            card = Quarto.objects.filter(tipo_uh=tipo).exclude(foto_principal="").first()
            foto = card.foto_principal.name if card else ""

            uhs = UH.objects.filter(
                tipo=tipo, status=UH.Status.ATIVA,
            ).order_by("numero")
            for i, uh in enumerate(uhs):
                if uh.nome_tematico:
                    continue  # já editado — preserva
                campos = []
                nome = nomes[i] if i < len(nomes) else f"Quarto {uh.numero}"
                uh.nome_tematico = nome
                campos.append("nome_tematico")
                for campo, valor in padrao.items():
                    setattr(uh, campo, valor)
                    campos.append(campo)
                uh.save(update_fields=campos)
                nomeados += 1
                if padrao:
                    qualif += 1

                vitrine, _ = VitrineQuarto.objects.get_or_create(uh=uh)
                mudou = []
                if foto and not vitrine.foto_principal:
                    vitrine.foto_principal = foto
                    mudou.append("foto_principal")
                    fotos += 1
                if vitrine.descricao_curta in ("", f"Quarto {uh.numero}"):
                    vitrine.descricao_curta = nome
                    mudou.append("descricao_curta")
                if mudou:
                    vitrine.save(update_fields=mudou)

        self.stdout.write(self.style.SUCCESS(
            f"Vitrine populada: {nomeados} nome(s) temático(s), {qualif} com qualidades "
            f"padrão, {fotos} foto(s) herdada(s) do tipo. Tour 360° não tocado."
        ))
