from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "Plataforma de cultivo — administración"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ingresar/", auth_views.LoginView.as_view(), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("cultivo.urls")),
]

# En desarrollo Django sirve las fotos; en producción las sirve el servidor web.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
