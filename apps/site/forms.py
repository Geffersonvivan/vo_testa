import re
from datetime import date, timedelta

from django import forms

from apps.site.models import Hospede


def validar_cpf(cpf):
    """Valida CPF pelos dígitos verificadores. Retorna o CPF só com dígitos."""
    numeros = re.sub(r'\D', '', cpf or '')
    if len(numeros) != 11 or numeros == numeros[0] * 11:
        raise forms.ValidationError('Informe um CPF válido.')
    for i in (9, 10):
        soma = sum(int(numeros[n]) * ((i + 1) - n) for n in range(i))
        digito = (soma * 10) % 11 % 10
        if digito != int(numeros[i]):
            raise forms.ValidationError('CPF inválido — confira os números.')
    return numeros


def formatar_cpf(numeros):
    n = re.sub(r'\D', '', numeros or '')
    if len(n) != 11:
        return numeros or ''
    return f'{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}'


def _hospede_por_cpf(cpf):
    from django.db.models import Q

    digitos = re.sub(r'\D', '', cpf or '')
    if len(digitos) != 11:
        return None
    fmt = formatar_cpf(digitos)
    return Hospede.objects.filter(Q(cpf=fmt) | Q(cpf=digitos)).first()


def _hospede_por_email(email):
    email = (email or '').strip()
    if not email:
        return None
    return Hospede.objects.filter(email__iexact=email).first()


def _cpf_valido_cadastrado(cpf):
    digitos = re.sub(r'\D', '', cpf or '')
    return len(digitos) == 11


def encontrar_hospede(*, email='', cpf=''):
    """Localiza hóspede por CPF (identidade) ou e-mail — para atualizar em vez de duplicar.

    Se CPF e e-mail apontarem para cadastros diferentes, prevalece o do CPF
    (identidade). O formulário libera o e-mail do cadastro legado no save.
    """
    por_cpf = _hospede_por_cpf(cpf)
    por_email = _hospede_por_email(email)
    if por_cpf and por_email and por_cpf.pk != por_email.pk:
        return por_cpf
    return por_cpf or por_email


def liberar_email_hospede(hospede_legado, *, manter=None):
    """Libera o e-mail único do legado (necessário antes do validate_unique).

    Se `manter` já existe, move as reservas do legado para ele e apaga o legado
    quando possível; caso contrário só arquiva o e-mail.
    """
    if not hospede_legado or not hospede_legado.pk:
        return
    if manter and manter.pk and manter.pk != hospede_legado.pk:
        hospede_legado.reservas.update(hospede=manter)
        if not hospede_legado.reservas.exists():
            hospede_legado.delete()
            return
    hospede_legado.email = f'arquivado.{hospede_legado.pk}@invalid'
    if not _cpf_valido_cadastrado(hospede_legado.cpf):
        hospede_legado.cpf = None
    hospede_legado.save(update_fields=['email', 'cpf'])


class BuscaDisponibilidadeForm(forms.Form):
    """Busca de quartos / Dia na Pousada a partir das datas e nº de hóspedes."""

    checkin = forms.DateField(
        label='Check-in',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    checkout = forms.DateField(
        label='Check-out',
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
    )
    hospedes = forms.IntegerField(
        label='Hóspedes',
        min_value=1,
        initial=2,
    )
    modalidade = forms.ChoiceField(
        choices=[
            ('', 'Todas'),
            ('hospedagem', 'Hospedagem'),
            ('day_use', 'Dia na Pousada'),
        ],
        required=False,
        initial='',
    )

    def clean_checkin(self):
        checkin = self.cleaned_data['checkin']
        if checkin < date.today():
            raise forms.ValidationError('A data de check-in não pode ser no passado.')
        return checkin

    def clean(self):
        cleaned = super().clean()
        checkin = cleaned.get('checkin')
        checkout = cleaned.get('checkout')
        modalidade = cleaned.get('modalidade') or ''
        if modalidade == 'day_use' and checkin:
            # Day use = 1 dia no motor de reservas (checkout = dia seguinte).
            cleaned['checkout'] = checkin + timedelta(days=1)
        elif checkin and checkout and checkout <= checkin:
            self.add_error('checkout', 'O check-out deve ser depois do check-in.')
        elif checkin and not checkout:
            self.add_error('checkout', 'Informe a data de check-out.')
        return cleaned


_CAMPO = (
    'w-full rounded-xl border border-madeira/15 px-3 py-2.5 '
    'text-madeira bg-white focus:border-lampiao outline-none'
)


class DadosHospedeForm(forms.ModelForm):
    """Dados do hóspede para finalizar a reserva."""

    class Meta:
        model = Hospede
        fields = ['nome', 'email', 'telefone', 'cpf', 'observacoes']
        widgets = {
            'nome': forms.TextInput(attrs={
                'class': _CAMPO, 'placeholder': 'Nome completo',
                'autocomplete': 'name',
            }),
            'email': forms.EmailInput(attrs={
                'class': _CAMPO, 'placeholder': 'voce@email.com',
                'autocomplete': 'email',
            }),
            'cpf': forms.TextInput(attrs={
                'class': _CAMPO,
                'placeholder': '000.000.000-00',
                'inputmode': 'numeric',
                'autocomplete': 'off',
                'maxlength': '14',
                'data-mask': 'cpf',
            }),
            'telefone': forms.TextInput(attrs={
                'class': _CAMPO,
                'placeholder': '(00) 00000-0000',
                'inputmode': 'tel',
                'autocomplete': 'tel',
                'maxlength': '15',
                'data-mask': 'telefone',
            }),
            'observacoes': forms.Textarea(attrs={
                'rows': 3, 'class': _CAMPO,
                'placeholder': 'Pedidos especiais (opcional)',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cpf'].required = True
        self.fields['observacoes'].required = False

    def clean_cpf(self):
        return formatar_cpf(validar_cpf(self.cleaned_data.get('cpf')))

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            return email
        outro = Hospede.objects.filter(email__iexact=email)
        if self.instance.pk:
            outro = outro.exclude(pk=self.instance.pk)
        outro = outro.first()
        if not outro:
            return email
        # Cadastro duplicado (e-mail num, CPF noutro): unifica no instance e
        # libera o e-mail agora — validate_unique roda depois deste clean_*.
        if not _cpf_valido_cadastrado(outro.cpf):
            liberar_email_hospede(outro, manter=self.instance if self.instance.pk else None)
            return email
        raise forms.ValidationError(
            'Este e-mail já está ligado a outro CPF. Use o e-mail desse cadastro '
            'ou fale com a pousada.'
        )

    def clean_telefone(self):
        digitos = re.sub(r'\D', '', self.cleaned_data.get('telefone') or '')
        if len(digitos) < 10 or len(digitos) > 11:
            raise forms.ValidationError('Informe um WhatsApp válido com DDD.')
        if len(digitos) == 10:
            return f'({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}'
        return f'({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}'


class PropostaSiteForm(forms.Form):
    """Captura de lead no site → Comercial (origem=site)."""

    TIPO_CHOICES = [
        ('hospedagem', 'Hospedagem'),
        ('evento', 'Evento / confraternização'),
        ('day_use', 'Dia na Pousada'),
    ]

    nome = forms.CharField(label='Nome', max_length=120)
    email = forms.EmailField(label='E-mail', required=False)
    telefone = forms.CharField(label='WhatsApp', max_length=30)
    tipo_interesse = forms.ChoiceField(
        label='Interesse', choices=TIPO_CHOICES, initial='hospedagem', required=False,
    )
    checkin = forms.DateField(
        label='Check-in', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    checkout = forms.DateField(
        label='Check-out', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    hospedes = forms.IntegerField(label='Pessoas', min_value=1, initial=2, required=False)
    mensagem = forms.CharField(
        label='Mensagem', required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': (
                'Preferências de quarto, datas flexíveis '
                'ou outros detalhes da estadia.'
            ),
        }),
    )

    def clean(self):
        cleaned = super().clean()
        checkin, checkout = cleaned.get('checkin'), cleaned.get('checkout')
        if checkin and checkout and checkout <= checkin:
            self.add_error('checkout', 'O check-out deve ser depois do check-in.')
        if not cleaned.get('email') and not cleaned.get('telefone'):
            raise forms.ValidationError('Informe e-mail ou WhatsApp para retorno.')
        if not cleaned.get('tipo_interesse'):
            cleaned['tipo_interesse'] = 'hospedagem'
        return cleaned
