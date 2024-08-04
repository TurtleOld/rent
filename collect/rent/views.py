import tempfile


from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView, FormView

from collect.custom_mixins import CustomNoPermissionMixin
from collect.rent.forms import UploadFileForm
from collect.rent.models import Rent

from collect.rent.services import format_rent, convert_pdf_to_docx


class RentView(CustomNoPermissionMixin, SuccessMessageMixin, TemplateView):
    template_name = 'rent/index.html'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Привет!'
        context['accounts'] = Rent.objects.all()
        return context


class FileFieldFormView(CustomNoPermissionMixin, SuccessMessageMixin, FormView):
    template_name = 'rent/payslips.html'
    form_class = UploadFileForm
    success_url = reverse_lazy('rent:list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        return context

    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def form_valid(self, form):
        file = form.cleaned_data['file']
        with tempfile.NamedTemporaryFile(mode='w+b') as tempf:
            tempf.write(file.read())
            docx_file = convert_pdf_to_docx(tempf)
            format_rent(docx_file)
            return super().form_valid(form)
