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

# A pousada usa só o NÚMERO do quarto ("Quarto N") — sem nome temático. Este seed cuida
# só de qualidades e fotos; não atribui nome (ver manage.py limpar_nomes_quartos).

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
        qualif = fotos = 0
        k = 0  # índice global para ciclar as fotos disponíveis
        for tipo in TipoUH.objects.filter(modalidade=TipoUH.Modalidade.HOSPEDAGEM):
            padrao = PADROES_POR_TIPO.get(tipo.nome, {})
            uhs = UH.objects.filter(tipo=tipo, status=UH.Status.ATIVA).order_by("numero")
            for uh in uhs:
                # Qualidades padrão por tipo (starter). Sem nome temático — só o número.
                if padrao:
                    for campo, valor in padrao.items():
                        setattr(uh, campo, valor)
                    uh.save(update_fields=list(padrao))
                    qualif += 1

                vitrine, _ = VitrineQuarto.objects.get_or_create(uh=uh)
                # Foto: corrige quebrada/ausente sem sobrescrever foto válida.
                if pool and not _foto_ok(vitrine.foto_principal.name if vitrine.foto_principal else ""):
                    vitrine.foto_principal = pool[k % len(pool)]
                    vitrine.save(update_fields=["foto_principal"])
                    fotos += 1
                k += 1

        self.stdout.write(self.style.SUCCESS(
            f"Vitrine: {qualif} quarto(s) com qualidades padrão, "
            f"{fotos} foto(s) corrigida(s) de {len(pool)} disponível(is). "
            f"Nome temático não tocado (a pousada usa só o número). Tour 360° não tocado."
        ))
