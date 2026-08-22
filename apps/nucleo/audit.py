"""
Auditoria — camada automática ("toda ação do atendente fica registrada").

Duas peças:
  1. `AuditContextMiddleware` guarda, por requisição, QUEM está agindo e de qual IP
     (num threadlocal), para que qualquer service — mesmo sem `request` em mãos —
     saiba a quem atribuir a ação.
  2. Signals `post_save`/`post_delete` nos models de negócio gravam automaticamente
     criar/editar/excluir com o diff dos campos. É o piso: nada de escrita escapa.

Regras:
  - Só registra quando há um usuário real no contexto (requisição autenticada). Seed,
    migrations, shell e cron sem usuário setado NÃO poluem a trilha.
  - Trilha é append-only (a própria TrilhaAuditoria nunca é auditada — evita loop).
  - Leituras (GET/listagens) não entram aqui; isto é trilha de ESCRITA.
"""
from __future__ import annotations

import threading
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models.signals import post_delete, post_save, pre_save

_contexto = threading.local()

# Campos que nunca entram no diff (ruído, automáticos ou sensíveis).
CAMPOS_IGNORADOS = {
    "criado_em", "atualizado_em", "modificado_em", "last_login", "password",
}

# Denylist: por PADRÃO auditamos TODOS os models dos nossos apps (apps.*) —
# qualquer escrita de qualquer usuário, independente de permissão, vira registro.
# Aqui ficam só os que NÃO devem ser auditados (técnicos/loop/trilhas próprias).
MODELOS_EXCLUIDOS = {
    "nucleo.TrilhaAuditoria",       # a própria trilha — evita loop infinito
    "pagamentos.EventoPagamento",   # já é a trilha de webhooks do gateway
}


def _modelos_para_auditar():
    """Todos os models dos apps `apps.*`, menos os excluídos e tabelas M2M."""
    modelos = []
    for modelo in django_apps.get_models():
        if not modelo._meta.app_config.name.startswith("apps."):
            continue  # ignora Django/contrib
        if getattr(modelo._meta, "auto_created", False):
            continue  # tabelas intermediárias (M2M) automáticas
        rotulo = f"{modelo._meta.app_label}.{modelo.__name__}"
        if rotulo not in MODELOS_EXCLUIDOS:
            modelos.append((rotulo, modelo))
    return modelos


# ---------------------------------------------------------------- contexto (quem/IP)
def definir_contexto(usuario=None, ip=None):
    _contexto.usuario = usuario if (usuario and getattr(usuario, "is_authenticated", False)) else None
    _contexto.ip = ip


def limpar_contexto():
    _contexto.usuario = None
    _contexto.ip = None


def usuario_atual():
    return getattr(_contexto, "usuario", None)


def ip_atual():
    return getattr(_contexto, "ip", None)


def _ip_da_requisicao(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditContextMiddleware:
    """Publica o usuário/IP da requisição no threadlocal durante o processamento."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        definir_contexto(getattr(request, "user", None), _ip_da_requisicao(request))
        try:
            return self.get_response(request)
        finally:
            limpar_contexto()


# ------------------------------------------------------------------- diff dos campos
def _serializa(valor):
    if valor is None or isinstance(valor, (int, float, bool, str)):
        return valor
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return str(valor)


def _snapshot(instance) -> dict:
    dados = {}
    for campo in instance._meta.concrete_fields:
        if campo.name in CAMPOS_IGNORADOS or campo.primary_key:
            continue
        dados[campo.attname] = _serializa(getattr(instance, campo.attname, None))
    return dados


def _pre_save(sender, instance, **kwargs):
    """Guarda o estado anterior (do banco) para calcular o diff no post_save."""
    if not instance.pk:
        instance._audit_anterior = None
        return
    anterior = sender.objects.filter(pk=instance.pk).first()
    instance._audit_anterior = _snapshot(anterior) if anterior else None


def _post_save(sender, instance, created, **kwargs):
    usuario = usuario_atual()
    if usuario is None:
        return  # sem ator real → não registra (seed/migration/cron sem usuário)
    from apps.nucleo.models import registrar_auditoria

    if created:
        registrar_auditoria(usuario, "criar", instance, {"valores": _snapshot(instance)})
        return
    anterior = getattr(instance, "_audit_anterior", None) or {}
    atual = _snapshot(instance)
    alteracoes = {
        campo: [anterior.get(campo), novo]
        for campo, novo in atual.items()
        if anterior.get(campo) != novo
    }
    if not alteracoes:
        return  # save sem mudança de campo → nada a registrar
    registrar_auditoria(usuario, "editar", instance, {"alteracoes": alteracoes})


def _post_delete(sender, instance, **kwargs):
    usuario = usuario_atual()
    if usuario is None:
        return
    from apps.nucleo.models import registrar_auditoria

    registrar_auditoria(usuario, "excluir", instance, {"valores": _snapshot(instance)})


# ------------------------------------------------------------------ login/logout
def _logou(sender, request, user, **kwargs):
    from apps.nucleo.models import registrar_auditoria

    ip = _ip_da_requisicao(request) if request is not None else None
    registrar_auditoria(user, "login", user, {"username": user.get_username()}, ip=ip)


def _deslogou(sender, request, user, **kwargs):
    if user is None:  # sessão expirada sem usuário — nada a registrar
        return
    from apps.nucleo.models import registrar_auditoria

    ip = _ip_da_requisicao(request) if request is not None else None
    registrar_auditoria(user, "logout", user, {"username": user.get_username()}, ip=ip)


def conectar_auditoria_automatica():
    """Liga os signals para cada model auditado. Chamado no AppConfig.ready()."""
    from django.contrib.auth.signals import user_logged_in, user_logged_out

    for rotulo, modelo in _modelos_para_auditar():
        uid = f"audit_{rotulo}"
        pre_save.connect(_pre_save, sender=modelo, dispatch_uid=uid + "_pre")
        post_save.connect(_post_save, sender=modelo, dispatch_uid=uid + "_post")
        post_delete.connect(_post_delete, sender=modelo, dispatch_uid=uid + "_del")

    # Entrar/sair fecham a linha do tempo do operador ("Peterson entrou 14:03…").
    user_logged_in.connect(_logou, dispatch_uid="audit_login")
    user_logged_out.connect(_deslogou, dispatch_uid="audit_logout")
