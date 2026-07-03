from .models import modulos_ativos
from .modulos import APRESENTACAO, Modulo


def menu_modulos(request):
    """Itens do menu lateral: apenas módulos contratados e ativos."""
    if not request.user.is_authenticated:
        return {"menu_modulos": []}
    itens = []
    for codigo in modulos_ativos():
        apres = APRESENTACAO.get(codigo, {})
        itens.append(
            {
                "codigo": codigo,
                "nome": Modulo(codigo).label,
                "icone": apres.get("icone", "▪️"),
                # url é preenchida conforme cada módulo for implementado
                "url": None,
            }
        )
    return {"menu_modulos": itens}
