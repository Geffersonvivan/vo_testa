"""Sitemap do site público (só páginas indexáveis). O domínio vem do request —
sem depender do framework Sites."""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class PaginasEstaticas(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return ["core:home", "core:reservar"]

    def location(self, item):
        return reverse(item)
