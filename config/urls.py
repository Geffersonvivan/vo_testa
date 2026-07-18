from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path


def healthz(_request):
    """Probe do Railway (HTTP, sem redirect SSL)."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz, name="healthz"),

    # Público (hóspede) — permanece na raiz, fora do /crm.
    path("hospede/", include("apps.portal.urls")),

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
    path("crm/frigobar/", include("apps.frigobar.urls")),
    path("crm/escala/", include("apps.escala.urls")),
    path("crm/pagamentos/", include("apps.pagamentos.urls")),
    path("crm/fiscal/", include("apps.fiscal.urls")),
    path("crm/auditoria/", include("apps.auditoria.urls")),
    path("crm/relatorios/", include("apps.relatorios.urls")),
    path("crm/comercial/", include("apps.comercial.urls")),
    path("crm/nps/", include("apps.nps.urls")),

    # Site público — assume a raiz "/".
    path("", include("apps.site.urls")),
]

# Mídia (fotos do site). Em produção Railway ainda sem S3/CDN — serve pelo app.
# Trocar por storage externo no cutover definitivo.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
