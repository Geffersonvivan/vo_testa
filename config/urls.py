from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from apps.comercial import views_lp
from apps.site import views as site_views
from apps.site.sitemaps import PaginasEstaticas

sitemaps = {"paginas": PaginasEstaticas}


def healthz(_request):
    """Probe do Railway (HTTP, sem redirect SSL)."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz, name="healthz"),

    # SEO / robôs (raiz do domínio).
    path("robots.txt", site_views.robots_txt),
    path("llms.txt", site_views.llms_txt),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),

    # Público (hóspede) — permanece na raiz, fora do /crm.
    path("hospede/", include("apps.portal.urls")),

    # LP Fundador (HTML oficial em LPs/) — pública, fora do /crm.
    path("lp/", include("apps.comercial.urls_lp")),
    path("privacidade/", views_lp.privacidade, name="privacidade"),
    # LP antiga (templated) aposentada → redireciona para a nova.
    path("captacao/fundador/", RedirectView.as_view(url="/lp/fundador/", permanent=False)),

    # Páginas de Captação (Landing Pages) — públicas, fora do /crm.
    path("captacao/", include("apps.comercial.urls_publicas")),

    # Descadastro de e-mail marketing (LGPD) — público, fora do /crm.
    path("email/", include("apps.comercial.urls_email_publico")),

    # API NPS (stub 501 — proposta fase CRM do Hóspede). Ver docs/Proposta_NPS.md.
    path("api/nps/", include("apps.nps.api_urls")),

    # Sistema (equipe): todo o CRM sob /crm/.
    path("crm/admin/", admin.site.urls),
    path("crm/entrar/", auth_views.LoginView.as_view(), name="login"),
    path("crm/sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("crm/", include("apps.nucleo.urls")),
    path("crm/reservas/", include("apps.reservas.urls")),
    path("crm/estoque/", include("apps.estoque.urls")),
    path("crm/loja/", include("apps.loja.urls")),
    path("crm/governanca/", include("apps.governanca.urls")),
    path("crm/restaurante/", include("apps.restaurante.urls")),
    path("crm/manutencao/", include("apps.manutencao.urls")),
    path("crm/lavanderia/", include("apps.lavanderia.urls")),
    # Frigobar aposentado (a pousada não trabalha com frigobar) — rotas removidas;
    # app permanece em INSTALLED_APPS (código/tabelas dormentes).
    path("crm/escala/", include("apps.escala.urls")),
    path("crm/pagamentos/", include("apps.pagamentos.urls")),
    path("crm/fiscal/", include("apps.fiscal.urls")),
    path("crm/auditoria/", include("apps.auditoria.urls")),
    path("crm/relatorios/", include("apps.relatorios.urls")),
    path("crm/comercial/", include("apps.comercial.urls")),
    path("crm/nps/", include("apps.nps.urls")),

    # Raiz "/": LP Fundador quando HOME_MODO=lp_fundador; senão o site (home_root delega).
    path("", views_lp.home_root, name="raiz"),
    # Site público — demais páginas (/quartos/, etc.).
    path("", include("apps.site.urls")),
]

# Mídia (fotos do site). static() do Django só age com DEBUG=1; em produção
# (Railway, ainda sem S3) servimos com django.views.static.serve.
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
