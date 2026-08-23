"""
Preenche a vitrine dos quartos com PADRÕES POR TIPO (ponto de partida para revisão):
- nome temático na voz da marca (ofícios de outrora, como os 6 quartos originais);
- qualidades padrão por tipo (vista lago, varanda, pet, ar, tipo de cama);
- foto: usa uma imagem que REALMENTE existe no storage (cicla as disponíveis),
  corrigindo cards com foto quebrada; nunca sobrescreve uma foto válida já definida.
O tour 360° NÃO é tocado (não temos os links). Nome/qualidades só em quartos AINDA NÃO
editados (nome_tematico vazio) — o que a recepção ajustar na tela é preservado.

Uso: manage.py popular_vitrine
"""
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from apps.nucleo.models import UH, TipoUH
from apps.site.models import VitrineQuarto

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

_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _pool_fotos():
    """Imagens que existem em media/quartos/ — usadas para não deixar card quebrado."""
    try:
        _, arquivos = default_storage.listdir("quartos")
    except Exception:
        return []
    return sorted("quartos/" + f for f in arquivos if f.lower().endswith(_EXTS))


def _foto_ok(nome):
    return bool(nome) and default_storage.exists(nome)


class Command(BaseCommand):
    help = "Nome temático, qualidades e foto padrão por tipo (só quartos não editados; corrige fotos quebradas)."

    def handle(self, *args, **opts):
        pool = _pool_fotos()
        nomeados = qualif = fotos = 0
        k = 0  # índice global para ciclar as fotos disponíveis
        for tipo in TipoUH.objects.filter(modalidade=TipoUH.Modalidade.HOSPEDAGEM):
            nomes = list(NOMES_POR_TIPO.get(tipo.nome, []))
            padrao = PADROES_POR_TIPO.get(tipo.nome, {})
            uhs = UH.objects.filter(tipo=tipo, status=UH.Status.ATIVA).order_by("numero")
            for i, uh in enumerate(uhs):
                # Nome + qualidades: só em quarto ainda não editado.
                if not uh.nome_tematico:
                    campos = ["nome_tematico"]
                    uh.nome_tematico = nomes[i] if i < len(nomes) else f"Quarto {uh.numero}"
                    for campo, valor in padrao.items():
                        setattr(uh, campo, valor)
                        campos.append(campo)
                    uh.save(update_fields=campos)
                    nomeados += 1
                    if padrao:
                        qualif += 1

                vitrine, _ = VitrineQuarto.objects.get_or_create(uh=uh)
                mudou = []
                # Foto: corrige quebrada/ausente sem sobrescrever foto válida.
                if pool and not _foto_ok(vitrine.foto_principal.name if vitrine.foto_principal else ""):
                    vitrine.foto_principal = pool[k % len(pool)]
                    mudou.append("foto_principal")
                    fotos += 1
                if vitrine.descricao_curta in ("", f"Quarto {uh.numero}") and uh.nome_tematico:
                    vitrine.descricao_curta = uh.nome_tematico
                    mudou.append("descricao_curta")
                if mudou:
                    vitrine.save(update_fields=mudou)
                k += 1

        self.stdout.write(self.style.SUCCESS(
            f"Vitrine: {nomeados} nome(s) temático(s), {qualif} com qualidades padrão, "
            f"{fotos} foto(s) corrigida(s) de {len(pool)} disponível(is). Tour 360° não tocado."
        ))
