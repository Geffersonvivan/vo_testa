"""Gera placeholders JPEG no MEDIA_ROOT do ambiente (útil no Railway sem volume)."""

import io

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw, ImageFont

from apps.site.models import Experiencia, FotoGaleria, FotoQuarto, Quarto

CORES = ["#051C2C", "#4F2C1D", "#D7A048", "#2E483E"]


def _gerar(largura, altura, texto, cor_fundo, cor_texto="#EFDBB2"):
    img = Image.new("RGB", (largura, altura), cor_fundo)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), str(texto), font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((largura - tw) // 2, (altura - th) // 2), str(texto), fill=cor_texto, font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf


class Command(BaseCommand):
    help = "Regenera fotos placeholder dos quartos/galeria/experiências no disco."

    def handle(self, *args, **options):
        n = 0
        for i, q in enumerate(Quarto.objects.all()):
            cor = CORES[i % len(CORES)]
            nome = q.nome.replace(" ", "_").lower()[:40]
            buf = _gerar(800, 600, q.nome, cor)
            q.foto_principal.save(f"{nome}.jpg", ContentFile(buf.read()), save=True)
            n += 1
            if q.fotos.count() == 0:
                for j, label in enumerate(["Vista", "Detalhe", "Banheiro"]):
                    buf = _gerar(800, 600, f"{q.nome} {label}", cor)
                    FotoQuarto.objects.create(
                        quarto=q,
                        legenda=f"{label} — {q.nome}",
                        ordem=j,
                        imagem=ContentFile(
                            buf.read(), name=f"{nome}_{label.lower()}.jpg"
                        ),
                    )
                    n += 1

        for i, g in enumerate(FotoGaleria.objects.all()):
            cor = CORES[i % len(CORES)]
            buf = _gerar(1200, 800, g.legenda or f"Galeria {i}", cor)
            g.imagem.save(f"galeria_{i:02d}.jpg", ContentFile(buf.read()), save=True)
            n += 1

        for i, e in enumerate(Experiencia.objects.all()):
            cor = CORES[i % len(CORES)]
            titulo = getattr(e, "titulo", None) or getattr(e, "nome", None) or f"Exp {i}"
            img_field = getattr(e, "imagem", None) or getattr(e, "foto", None)
            if img_field is None:
                continue
            buf = _gerar(800, 600, titulo, cor)
            img_field.save(f"exp_{i:02d}.jpg", ContentFile(buf.read()), save=True)
            n += 1

        self.stdout.write(self.style.SUCCESS(f"Arquivos salvos: {n}"))
