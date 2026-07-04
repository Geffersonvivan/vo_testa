from .models import modulos_ativos
from .modulos import APRESENTACAO, Modulo


def menu_modulos(request):
    """Menu lateral agrupado por área, apenas com módulos que o usuário acessa."""
    if not request.user.is_authenticated:
        return {"menu_modulos": []}

    if request.user.is_superuser:
        permitidos = None  # superusuário vê todos os ativos
    else:
        permitidos = set(
            request.user.modulos.filter(ativo=True).values_list("codigo", flat=True)
        )

    grupos: dict[str, list] = {}
    for codigo in modulos_ativos():
        if permitidos is not None and codigo not in permitidos:
            continue
        apres = APRESENTACAO.get(codigo, {})
        grupos.setdefault(apres.get("grupo", "Outros"), []).append(
            {
                "codigo": codigo,
                "nome": Modulo(codigo).label,
                # url é preenchida conforme cada módulo for implementado
                "url": None,
            }
        )
    return {
        "menu_modulos": [
            {"titulo": titulo, "itens": itens} for titulo, itens in grupos.items()
        ]
    }
