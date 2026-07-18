"""
Configurações do CRM Pousada Vô Testa.

Tudo que varia por ambiente vem de variáveis de ambiente (arquivo .env em
desenvolvimento, painel do Railway em produção). Ver .env.example.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "SECRET_KEY", "dev-inseguro-trocar-em-producao-x7k2m9"
)

DEBUG = os.environ.get("DEBUG", "0") == "1"

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
]
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
# Railway: domínio público injetado + wildcard dos *.up.railway.app
for _host in (
    os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip(),
    os.environ.get("RAILWAY_PRIVATE_DOMAIN", "").strip(),
):
    if _host and _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)
if not any(h == ".up.railway.app" or h.endswith(".up.railway.app") for h in ALLOWED_HOSTS):
    ALLOWED_HOSTS.append(".up.railway.app")

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # ExclusionConstraint (antioverbooking)
    # Módulos do sistema
    "apps.nucleo",
    "apps.reservas",
    "apps.estoque",
    "apps.loja",
    "apps.governanca",
    "apps.restaurante",
    "apps.manutencao",
    "apps.lavanderia",
    "apps.frigobar",
    "apps.escala",
    "apps.pagamentos",
    "apps.portal",
    "apps.nps",  # proposta NPS + API stub (fase CRM do Hóspede)
    "apps.site",  # site público (label 'core'), servido em "/"
    "apps.fiscal",
    "apps.auditoria",
    "apps.relatorios",
    "apps.comercial.apps.ComercialConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.nucleo.context_processors.menu_modulos",
                "apps.site.context_processors.reserva_passos",
                "apps.site.context_processors.prova_social",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default="postgres://localhost/crm_vo_testa",
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = "nucleo.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Mídia (fotos dos quartos, galeria) — vinda do site.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cookies com nome próprio: outros projetos rodando em localhost (portas
# diferentes) compartilham o domínio do cookie e derrubariam a sessão daqui.
SESSION_COOKIE_NAME = "vo_testa_sessionid"
CSRF_COOKIE_NAME = "vo_testa_csrftoken"

# Segurança em produção (atrás do proxy do Railway)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    # Healthcheck do Railway chega em HTTP — não redirecionar.
    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Pagamentos Online — gateway plugável. "simulado" (sandbox local) ou "safrapay".
PAGAMENTOS_GATEWAY = os.environ.get("PAGAMENTOS_GATEWAY", "simulado")
# Safrapay — 3 campos do portal /keys: ID, Código de Ativação, Token.
# SAFRAPAY_ENV: hml → payment-hml.safrapay.com.br | prod → payment.safrapay.com.br
SAFRAPAY_ENV = os.environ.get("SAFRAPAY_ENV", "hml")
SAFRAPAY_ID = os.environ.get("SAFRAPAY_ID", "")
SAFRAPAY_CODIGO_ATIVACAO = os.environ.get("SAFRAPAY_CODIGO_ATIVACAO", "")
SAFRAPAY_TOKEN = os.environ.get("SAFRAPAY_TOKEN", "")
_SAFRAPAY_BASE = {
    "hml": "https://payment-hml.safrapay.com.br",
    "prod": "https://payment.safrapay.com.br",
}
SAFRAPAY_GATEWAY_URL = os.environ.get(
    "SAFRAPAY_GATEWAY_URL",
    _SAFRAPAY_BASE.get(SAFRAPAY_ENV, _SAFRAPAY_BASE["hml"]),
)

# Retenção da pré-reserva vinda de canal (site): minutos que seguram o quarto
# antes de expirar automaticamente sem confirmação/pagamento.
RESERVA_RETENCAO_MINUTOS = int(os.environ.get("RESERVA_RETENCAO_MINUTOS", "30"))

# Frigobar: bloquear check-out até haver conferência (mesmo consumo zero). §5.9
FRIGOBAR_BLOQUEAR_CHECKOUT = os.environ.get("FRIGOBAR_BLOQUEAR_CHECKOUT", "1") == "1"

# Fiscal — gateway plugável: "simulado" (sandbox), "focus" (Focus NFe) ou "governo".
# Ver docs/Implementar_fiscal.md. Focus/Governo são stubs até ter credenciais/certificado.
FISCAL_GATEWAY = os.environ.get("FISCAL_GATEWAY", "simulado")

# Parâmetros fiscais confirmados pelo contador (jul/2026) — Pousada Vô Testa, Itá/SC.
# Regime Lucro Presumido; NFS-e pelo Emissor Nacional. NFC-e aguarda Inscrição Estadual.
FISCAL_REGIME = os.environ.get("FISCAL_REGIME", "lucro_presumido")
FISCAL_NFSE_CODIGO_SERVICO = os.environ.get("FISCAL_NFSE_CODIGO_SERVICO", "090101")  # hospedagem
FISCAL_NFSE_ISS_ALIQUOTA = os.environ.get("FISCAL_NFSE_ISS_ALIQUOTA", "4.0")  # % ISS Itá
FISCAL_NFCE_HABILITADA = os.environ.get("FISCAL_NFCE_HABILITADA", "0") == "1"  # depende da IE
# Segredo compartilhado com o Focus (campo "Chave de Autorização" do webhook). O Focus
# envia no header Authorization; o endpoint /crm/fiscal/webhook/ valida.
FISCAL_WEBHOOK_TOKEN = os.environ.get("FISCAL_WEBHOOK_TOKEN", "")

# E-mail — envio transacional (confirmação de reserva do site).
# Sem SMTP configurado (dev): imprime no terminal (console). Em produção, defina as
# variáveis EMAIL_HOST/USER/PASSWORD (ex.: Zoho — smtp.zoho.com:587, usuário naoresponda@).
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "Pousada Vô Testa <naoresponda@pousadavotesta.com.br>"
)
# URL pública do site (links em e-mail). Em produção: https://www.pousadavotesta.com.br
SITE_PUBLIC_URL = os.environ.get("SITE_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")

