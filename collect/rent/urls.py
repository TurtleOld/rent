from django.urls import path

from collect.rent.views import RentView

app_name = 'rent'
urlpatterns = [
    path('', RentView.as_view(), name='list'),
]
