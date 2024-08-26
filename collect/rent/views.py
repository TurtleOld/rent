import os
import tempfile


from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView, FormView, ListView

from collect.custom_mixins import CustomNoPermissionMixin
from collect.rent.forms import UploadFileForm
from collect.rent.models import Rent, ServiceInfo

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
    template_name = 'rent/download_payslips.html'
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
        with tempfile.TemporaryDirectory(dir=tempfile.gettempdir()) as tmpdir:
            tmp_file = os.path.join(tmpdir, 'tmpfile.pdf')
            with open(tmp_file, 'wb') as f:
                f.write(file.read())
            docx_file = convert_pdf_to_docx(tmp_file)
            format_rent(docx_file)
            return super().form_valid(form)


class ListUserPaySlips(CustomNoPermissionMixin, SuccessMessageMixin, ListView):
    template_name = 'rent/list_payslips.html'
    model = ServiceInfo
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)

        user_id = self.kwargs['id']
        payslips = ServiceInfo.objects.filter(rent_id=user_id)

        payslip_date = (
            payslips.filter(rent_id=user_id).values('date').distinct().order_by('date')
        )
        group_payslips = {
            date['date']: payslips.filter(date=date['date']) for date in payslip_date
        }

        context['payslips'] = group_payslips

        return context
