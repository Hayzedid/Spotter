from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.HealthCheckView.as_view(), name='health-check'),
    path('routes/', views.CalculateRoutesView.as_view(), name='calculate-routes'),
]
