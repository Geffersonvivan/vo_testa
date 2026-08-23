"""
Envia a mídia local (pasta media/) para o object storage padrão (Cloudflare R2).
Idempotente: pula arquivos que já existem no bucket. Rode UMA vez após configurar as
variáveis R2_* no ambiente (o storage padrão vira S3/R2).

Uso: manage.py migrar_media_r2 [--dry-run]
"""
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copia a mídia local (media/) para o object storage padrão (R2)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Só lista o que seria enviado, sem gravar.")

    def handle(self, *args, **opts):
        backend = settings.STORAGES["default"]["BACKEND"].lower()
        if "s3" not in backend:
            raise CommandError(
                "O storage padrão não é S3/R2 — configure as variáveis R2_* no ambiente "
                "primeiro (R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
                "R2_ENDPOINT_URL, R2_PUBLIC_DOMAIN)."
            )
        root = Path(settings.BASE_DIR) / "media"
        if not root.exists():
            raise CommandError(f"Pasta local de mídia não encontrada: {root}")

        enviados = pulados = 0
        for arquivo in sorted(root.rglob("*")):
            if not arquivo.is_file():
                continue
            nome = arquivo.relative_to(root).as_posix()  # ex.: quartos/foo.jpg
            if default_storage.exists(nome):
                pulados += 1
                continue
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] enviaria: {nome}")
                enviados += 1
                continue
            with arquivo.open("rb") as fh:
                default_storage.save(nome, File(fh))
            self.stdout.write(f"↑ {nome}")
            enviados += 1

        self.stdout.write(self.style.SUCCESS(
            f"R2: {enviados} enviado(s), {pulados} já existia(m)."
        ))
