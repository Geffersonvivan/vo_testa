"""
Seed inicial para a Escala: preenche **setor** (a partir do cargo) e **sexo**
(heurística pelo primeiro nome) dos funcionários, para o gerador e a regra de
domingo funcionarem.

Uso:
  manage.py preparar_escala            # só preenche o que está em branco
  manage.py preparar_escala --force    # refaz tudo (útil p/ dados de demo)
  manage.py preparar_escala --sem-sexo # não mexe no sexo (preenche à mão depois)

O SETOR vem do cargo (confiável). O SEXO é um CHUTE pelo nome — sempre revise em
Configurações → Equipe & Acessos (ou no admin). Nomes ambíguos ficam listados.
"""
from django.core.management.base import BaseCommand

from apps.nucleo.models import Funcionario

# palavra no cargo (minúsculo, sem acento não é tratado — cargos costumam vir com acento) -> setor
CARGO_SETOR = [
    ("recep", "Recepção"),
    ("camar", "Governança"), ("govern", "Governança"), ("arrum", "Governança"),
    ("faxin", "Governança"), ("limpeza", "Governança"), ("rouparia", "Governança"),
    ("cozinh", "Cozinha/Restaurante"), ("confeit", "Cozinha/Restaurante"),
    ("chef", "Cozinha/Restaurante"), ("garç", "Cozinha/Restaurante"),
    ("garc", "Cozinha/Restaurante"), ("restaur", "Cozinha/Restaurante"),
    ("copeir", "Cozinha/Restaurante"), ("bar", "Cozinha/Restaurante"),
    ("manuten", "Manutenção"), ("zelador", "Manutenção"), ("jardineir", "Manutenção"),
    ("gerent", "Gerência"), ("gestã", "Gerência"), ("coorden", "Gerência"),
    ("administ", "Gerência"),
]

# Exceções da regra "termina em A → feminino" (nomes comuns na região).
NOMES_F = {"ivone", "beatriz", "isabel", "isabela", "raquel", "ester", "miriam",
           "carmen", "eliane", "cleusa", "solange", "ines", "inês", "meire"}
NOMES_M = {"luca", "josue", "josué", "noe", "noé", "elias", "tobias", "jonas",
           "dida", "juca", "nica"}


def setor_do_cargo(cargo):
    c = (cargo or "").lower()
    for chave, setor in CARGO_SETOR:
        if chave in c:
            return setor
    return ""


def sexo_do_nome(nome):
    """Chute: retorna ('F'|'M', ambiguo?). ambiguo=True quando caiu só na
    regra do 'termina em a' (menos confiável)."""
    prim = (nome or "").strip().split(" ")[0].lower()
    if prim in NOMES_F:
        return "F", False
    if prim in NOMES_M:
        return "M", False
    if prim.endswith("a"):
        return "F", True
    return "M", True


class Command(BaseCommand):
    help = "Preenche setor (do cargo) e sexo (chute pelo nome) dos funcionários."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Sobrescreve valores já preenchidos.")
        parser.add_argument("--sem-sexo", action="store_true", help="Não mexe no sexo.")

    def handle(self, *args, **opts):
        force, sem_sexo = opts["force"], opts["sem_sexo"]
        setor_ok = setor_falta = sexo_ok = 0
        revisar_sexo, sem_setor = [], []

        for f in Funcionario.objects.select_related("pessoa").order_by("pk"):
            campos = []
            if force or not f.setor:
                s = setor_do_cargo(f.cargo)
                if s:
                    f.setor = s
                    campos.append("setor")
                    setor_ok += 1
                else:
                    setor_falta += 1
                    sem_setor.append(f"{f.pessoa.nome} ({f.cargo or '—'})")
            if not sem_sexo and (force or not f.sexo):
                sx, ambiguo = sexo_do_nome(f.pessoa.nome)
                f.sexo = sx
                campos.append("sexo")
                sexo_ok += 1
                if ambiguo:
                    revisar_sexo.append(f"{f.pessoa.nome} → {sx}")
            if campos:
                f.save(update_fields=campos)

        self.stdout.write(self.style.SUCCESS(
            f"Setor definido: {setor_ok}; sexo definido: {sexo_ok}."))
        if sem_setor:
            self.stdout.write(self.style.WARNING(
                "Sem setor (cargo não reconhecido) — defina à mão: " + "; ".join(sem_setor)))
        if revisar_sexo:
            self.stdout.write(self.style.WARNING(
                "Sexo é CHUTE pelo nome — revise: " + "; ".join(revisar_sexo)))
        self.stdout.write("Ajuste fino em Configurações → Equipe & Acessos.")
