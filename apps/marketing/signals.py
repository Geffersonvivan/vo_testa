"""Elo com o funil (Passo 7): o lead nasce com a campanha vigente do seu canal.

O marketing **ouve** o comercial (não o contrário — respeita a direção de dependência e não
refaz o funil). Quando um lead (Oportunidade) é criado SEM campanha, atribuímos a campanha
vigente pelo `anuncio`. Se não há vigente, fica 'Orgânico' — dado, não ausência de dado.
O campo continua editável: só agimos na criação e só quando está vazio.
"""


def atribuir_campanha_vigente(sender, instance, created, **kwargs):
    if not created or instance.campanha_id:
        return
    from .services import campanha_vigente
    rastreio = getattr(instance, "origem_rastreio", None) or {}
    canal = rastreio.get("utm_source") or None
    vig = campanha_vigente(canal, getattr(instance, "criado_em", None))
    if vig and vig.anuncio_id:
        # .update() não dispara post_save → sem recursão; só grava se ainda estiver vazio.
        sender.objects.filter(pk=instance.pk, campanha__isnull=True).update(
            campanha_id=vig.anuncio_id)
