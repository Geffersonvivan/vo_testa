"""Context processors do módulo Comercial."""
from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo


def whatsapp_nao_lidas(request):
    """Total de conversas de WhatsApp com mensagem aguardando resposta (badge na sidebar).

    Só para quem tem acesso ao Comercial e com o módulo ativo — e não roda para anônimo.
    """
    u = getattr(request, "user", None)
    if not (u and u.is_authenticated) or not modulo_ativo(Modulo.COMERCIAL):
        return {}
    if not (u.is_superuser or u.modulos.filter(codigo=Modulo.COMERCIAL, ativo=True).exists()):
        return {}
    from .models import ConversaWhatsApp
    total = ConversaWhatsApp.objects.filter(nao_lidas__gt=0).count()
    return {"wpp_nao_lidas_total": total}
