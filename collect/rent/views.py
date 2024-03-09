from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from collect.custom_mixins import CustomNoPermissionMixin


class RentView(CustomNoPermissionMixin, SuccessMessageMixin, TemplateView):
    template_name = 'rent/index.html'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Привет!'
        return context
