"""
Serviços do Portal do Hóspede. Cada ação do hóspede é encaminhada ao service do
módulo dono (Restaurante, Governança, Manutenção, Pagamentos) e atribuída a um
usuário de sistema (_portal) para auditoria. Degrada com graça se um módulo
opcional estiver inativo.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.nucleo.models import UH, LocalEstoque, Produto, modulo_ativo, saldo
from apps.nucleo.modulos import Modulo

from .models import AcessoPortal, SolicitacaoPortal

Usuario = get_user_model()


def _usuario_sistema():
    user, criado = Usuario.objects.get_or_create(
        username="_portal", defaults={"is_active": True, "first_name": "Portal"}
    )
    if criado:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def get_acesso(reserva_id) -> AcessoPortal:
    return AcessoPortal.objects.get_or_create(reserva_id=reserva_id)[0]


def resolver(token):
    """Token → dados da estadia (ou None se inválido / estadia encerrada)."""
    from apps.reservas.services import dados_estadia
    acesso = AcessoPortal.objects.filter(token=token).first()
    if not acesso:
        return None
    return dados_estadia(acesso.reserva_id)


def _local_restaurante():
    return (
        LocalEstoque.objects.filter(modulo=Modulo.RESTAURANTE, ativo=True).first()
        or LocalEstoque.objects.filter(modulo=Modulo.LOJA, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


def cardapio():
    """Produtos vendáveis com saldo, para o hóspede pedir no restaurante."""
    local = _local_restaurante()
    if not local or not modulo_ativo(Modulo.RESTAURANTE):
        return []
    itens = []
    for p in Produto.objects.filter(ativo=True, preco_venda__gt=0):
        if saldo(p, local) > 0:
            itens.append({"id": p.pk, "nome": p.nome, "preco": p.preco_venda})
    return itens


def pedir_restaurante(estadia, pedidos):
    """`pedidos`: lista de (produto_id, quantidade). Abre uma comanda no quarto e
    lança os itens (a cozinha vê na lista de comandas)."""
    if not modulo_ativo(Modulo.RESTAURANTE):
        raise ValidationError("O restaurante não está disponível no momento.")
    from apps.restaurante import services as restaurante
    local = _local_restaurante()
    if not local:
        raise ValidationError("Restaurante indisponível.")
    op = _usuario_sistema()
    comanda = restaurante.abrir_comanda(op, local, rotulo=f"{estadia['uh']} · app")
    total_itens = 0
    for produto_id, qtd in pedidos:
        qtd = int(qtd or 0)
        if qtd <= 0:
            continue
        produto = Produto.objects.filter(pk=produto_id).first()
        if produto:
            restaurante.adicionar_item(comanda, produto, qtd, op)
            total_itens += qtd
    if total_itens == 0:
        comanda.delete()
        raise ValidationError("Escolha ao menos um item.")
    SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.RESTAURANTE,
        detalhe=f"Comanda #{comanda.pk} · {total_itens} item(ns)",
    )
    return comanda


def solicitar_limpeza(estadia):
    reg = SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.LIMPEZA, detalhe="Limpeza extra pedida pelo hóspede.",
    )
    if modulo_ativo(Modulo.GOVERNANCA):
        from apps.governanca import services as gov
        uh = UH.objects.filter(pk=estadia["uh_id"]).first()
        if uh:
            gov.abrir_faxina(uh, usuario=_usuario_sistema(), origem="portal")
    return reg


def solicitar_manutencao(estadia, descricao):
    descricao = (descricao or "").strip() or "Solicitação do hóspede pelo portal."
    reg = SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.MANUTENCAO, detalhe=descricao[:200],
    )
    if modulo_ativo(Modulo.MANUTENCAO):
        from apps.manutencao import services as manut
        uh = UH.objects.filter(pk=estadia["uh_id"]).first()
        if uh:
            manut.abrir_os(_usuario_sistema(), uh=uh,
                           titulo="Solicitação do hóspede (portal)", descricao=descricao)
    return reg


def cobrar_saldo(estadia, metodo="pix"):
    """Gera a cobrança do saldo da conta via Pagamentos e devolve a cobrança."""
    if not modulo_ativo(Modulo.PAGAMENTOS):
        raise ValidationError("Pagamento online indisponível — acerte na recepção.")
    saldo_conta = Decimal(estadia["saldo"])
    if saldo_conta <= 0:
        raise ValidationError("Não há saldo a pagar.")
    from apps.pagamentos import services as pag
    return pag.criar_cobranca(
        _usuario_sistema(), valor=saldo_conta, metodo=metodo,
        descricao=f"Saldo da hospedagem — {estadia['uh']}",
        finalidade=pag.FINALIDADE_SALDO, reserva_id=estadia["reserva_id"],
    )


def solicitar_checkout(estadia):
    return SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.CHECKOUT,
        detalhe="Check-out expresso solicitado pelo hóspede.",
    )
