from .models import modulos_ativos
from .modulos import APRESENTACAO, Modulo


def menu_modulos(request):
    """Itens do menu lateral: módulos ativos QUE o usuário pode acessar."""
    if not request.user.is_authenticated:
        return {"menu_modulos": []}

    if request.user.is_superuser:
        permitidos = None  # superusuário vê todos os ativos
    else:
        permitidos = set(
            request.user.modulos.filter(ativo=True).values_list("codigo", flat=True)
        )

    itens = []
    for codigo in modulos_ativos():
        if permitidos is not None and codigo not in permitidos:
            continue
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
