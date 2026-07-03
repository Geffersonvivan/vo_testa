from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.nucleo import views as nucleo_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", nucleo_views.dashboard, name="dashboard"),
]
