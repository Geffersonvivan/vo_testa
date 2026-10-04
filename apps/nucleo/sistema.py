"""Utilitários de infraestrutura compartilhados do núcleo."""
from django.contrib.auth import get_user_model


def usuario_de_sistema(username: str, nome: str):
    """Usuário "robô" para ações automáticas sem operador logado (portal, site, cron).
    Senha inutilizável — nunca é uma conta logável. Idempotente (get_or_create).
    Centraliza o padrão para as contas de sistema não divergirem entre apps."""
    user, criado = get_user_model().objects.get_or_create(
        username=username, defaults={"is_active": True, "first_name": nome})
    if criado:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def travar(obj):
    """Trava a linha do objeto no banco (SELECT … FOR UPDATE) e recarrega a instância
    passada do estado já travado — serializa escritas concorrentes (duplo POST/corrida)
    sem trocar a referência do chamador. Usar DENTRO de uma transação atômica."""
    type(obj).objects.select_for_update().get(pk=obj.pk)
    obj.refresh_from_db()
    return obj
