from django.contrib import admin
from django.urls import path, include
from routing.views import HealthCheckView

urlpatterns = [
    path('', HealthCheckView.as_view(), name='root-health'),
    path('admin/', admin.site.urls),
    path('api/', include('routing.urls')),
]
