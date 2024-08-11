from django.urls import path

from collect.rent.views import RentView, FileFieldFormView, ListUserPaySlips

app_name = 'rent'
urlpatterns = [
    path('', RentView.as_view(), name='list'),
    path('payslips/', FileFieldFormView.as_view(), name='payslips'),
    path('user/<int:id>', ListUserPaySlips.as_view(), name='user_payslips'),
]
