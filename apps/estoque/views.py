from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.nucleo.models import (
    CategoriaProduto,
    Inventario,
    ItemInventario,
    LocalEstoque,
    Produto,
    ajustar,
    posicao_estoque,
    registrar_entrada,
    registrar_saida,
    saldo,
    transferir,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_modulo

from .forms import (
    AbrirInventarioForm,
    AjusteForm,
    CategoriaProdutoForm,
    EntradaForm,
    LocalEstoqueForm,
    ProdutoForm,
    SaidaForm,
    TransferenciaForm,
)

# ---------- Posição de estoque (home do módulo) ----------


@requer_modulo(Modulo.ESTOQUE)
def posicao(request):
    local_id = request.GET.get("local", "")
    local = None
    if local_id:
        local = get_object_or_404(LocalEstoque, pk=local_id)
    linhas = posicao_estoque(local)
    if request.GET.get("alerta"):
        linhas = [linha for linha in linhas if linha["abaixo_minimo"]]
    return render(
        request,
        "estoque/posicao.html",
        {
            "linhas": linhas,
            "locais": LocalEstoque.objects.filter(ativo=True),
            "local": local,
            "so_alerta": bool(request.GET.get("alerta")),
            "alertas": sum(1 for lin in posicao_estoque(local) if lin["abaixo_minimo"]),
        },
    )


# ---------- Produtos ----------


@requer_modulo(Modulo.ESTOQUE)
def produtos(request):
    busca = request.GET.get("q", "").strip()
    lista = Produto.objects.select_related("categoria")
    if busca:
        lista = lista.filter(
            Q(nome__icontains=busca) | Q(codigo_barras__icontains=busca)
        )
    return render(request, "estoque/produtos.html", {"produtos": lista, "busca": busca})


@requer_modulo(Modulo.ESTOQUE)
def produto_form(request, pk=None):
    produto = get_object_or_404(Produto, pk=pk) if pk else None
    form = ProdutoForm(request.POST or None, instance=produto)
    if request.method == "POST" and form.is_valid():
        produto = form.save()
        messages.success(request, f"Produto “{produto.nome}” salvo.")
        return redirect("estoque:produtos")
    return render(
        request,
        "estoque/form_simples.html",
        {"form": form, "titulo": "Produto", "voltar": "estoque:produtos"},
    )


@requer_modulo(Modulo.ESTOQUE)
def kardex(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    movimentos = produto.movimentos.select_related("local")[:300]
    return render(
        request,
        "estoque/kardex.html",
        {
            "produto": produto,
            "movimentos": movimentos,
            "saldo": saldo(produto),
        },
    )


# ---------- Categorias e locais ----------


@requer_modulo(Modulo.ESTOQUE)
def categorias(request):
    form = CategoriaProdutoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoria salva.")
        return redirect("estoque:categorias")
    return render(
        request,
        "estoque/categorias.html",
        {"categorias": CategoriaProduto.objects.all(), "form": form},
    )


@requer_modulo(Modulo.ESTOQUE)
def locais(request):
    form = LocalEstoqueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Local salvo.")
        return redirect("estoque:locais")
    return render(
        request,
        "estoque/locais.html",
        {"locais": LocalEstoque.objects.all(), "form": form},
    )


# ---------- Movimentações ----------


def _tela_movimento(request, form, titulo, executar, sucesso):
    if request.method == "POST" and form.is_valid():
        try:
            executar(form.cleaned_data)
            messages.success(request, sucesso)
            return redirect("estoque:posicao")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return render(
        request,
        "estoque/form_simples.html",
        {"form": form, "titulo": titulo, "voltar": "estoque:posicao"},
    )


@requer_modulo(Modulo.ESTOQUE)
def entrada(request):
    form = EntradaForm(request.POST or None)

    def executar(d):
        registrar_entrada(
            d["produto"], d["local"], d["quantidade"], d["custo_unitario"],
            request.user, documento=d["documento"], observacao=d["observacao"],
        )

    return _tela_movimento(
        request, form, "Entrada por compra", executar,
        "Entrada registrada — saldo e custo médio atualizados.",
    )


@requer_modulo(Modulo.ESTOQUE)
def saida(request):
    form = SaidaForm(request.POST or None)

    def executar(d):
        registrar_saida(
            d["produto"], d["local"], d["quantidade"], request.user,
            tipo=d["tipo"], observacao=d["observacao"],
        )

    return _tela_movimento(
        request, form, "Saída de estoque", executar, "Saída registrada."
    )


@requer_modulo(Modulo.ESTOQUE)
def transferencia(request):
    form = TransferenciaForm(request.POST or None)

    def executar(d):
        transferir(
            d["produto"], d["origem"], d["destino"], d["quantidade"],
            request.user, observacao=d["observacao"],
        )

    return _tela_movimento(
        request, form, "Transferência entre locais", executar,
        "Transferência registrada nos dois locais.",
    )


@requer_modulo(Modulo.ESTOQUE)
def ajuste(request):
    form = AjusteForm(request.POST or None)

    def executar(d):
        ajustar(
            d["produto"], d["local"], d["quantidade"], request.user, motivo=d["motivo"]
        )

    return _tela_movimento(
        request, form, "Ajuste de saldo", executar,
        "Ajuste registrado — operação auditada.",
    )


# ---------- Inventário ----------


@requer_modulo(Modulo.ESTOQUE)
def inventarios(request):
    form = AbrirInventarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        local = form.cleaned_data["local"]
        inv = Inventario.objects.create(local=local, criado_por=request.user)
        for produto in Produto.objects.filter(ativo=True):
            atual = saldo(produto, local)
            ItemInventario.objects.create(
                inventario=inv, produto=produto,
                saldo_sistema=atual, quantidade_contada=atual,
            )
        messages.success(request, "Inventário aberto — faça a contagem.")
        return redirect("estoque:inventario", pk=inv.pk)
    return render(
        request,
        "estoque/inventarios.html",
        {"inventarios": Inventario.objects.select_related("local"), "form": form},
    )


@requer_modulo(Modulo.ESTOQUE)
def inventario(request, pk):
    inv = get_object_or_404(
        Inventario.objects.select_related("local"), pk=pk
    )
    if request.method == "POST" and inv.status == Inventario.Status.ABERTO:
        for item in inv.itens.all():
            valor = request.POST.get(f"item_{item.pk}")
            if valor is not None:
                try:
                    item.quantidade_contada = valor.replace(",", ".")
                    item.save(update_fields=["quantidade_contada"])
                except (ValueError, Exception):
                    pass
        if "aplicar" in request.POST:
            try:
                inv.aplicar(request.user)
                messages.success(
                    request, "Inventário aplicado — ajustes gerados e auditados."
                )
                return redirect("estoque:posicao")
            except ValidationError as erro:
                messages.error(request, " ".join(erro.messages))
        else:
            messages.success(request, "Contagem salva.")
        return redirect("estoque:inventario", pk=inv.pk)
    return render(
        request,
        "estoque/inventario.html",
        {"inventario": inv, "itens": inv.itens.select_related("produto")},
    )
