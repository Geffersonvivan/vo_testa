from apps.site.models import Reserva


def reserva_passos(request):
    """Passos do fluxo de reserva para o stepper (partial).

    'Pagamento' será reinserido quando a integração existir (Etapa B).
    """
    return {
        'reserva_passos': [
            (1, 'Datas'),
            (2, 'Quartos'),
            (3, 'Dados'),
            (4, 'Resumo'),
            (5, 'Confirmação'),
        ],
    }


def prova_social(request):
    """Reserva real mais recente para a notificação flutuante (só primeiro nome)."""
    ultima = (
        Reserva.objects
        .filter(status__in=['confirmada', 'checkin', 'finalizada'])
        .select_related('hospede', 'quarto')
        .order_by('-criado_em')
        .first()
    )
    if not ultima:
        return {'prova_social': None}
    primeiro_nome = ultima.hospede.nome.split()[0] if ultima.hospede.nome else 'Alguém'
    return {
        'prova_social': {
            'nome': primeiro_nome,
            'iniciais': primeiro_nome[:2].upper(),
            'quarto': ultima.quarto.nome,
            'quando': ultima.criado_em,
        }
    }
