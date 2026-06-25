from django.urls import path
from . import views

app_name = "fiber_match_api"

urlpatterns = [
    path("", views.infer, name="infer"),
]
