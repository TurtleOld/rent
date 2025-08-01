"""Django views for EPD parser application."""

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView

from .forms import EpdDocumentForm, EpdUploadForm
from .models import EpdDocument, ServiceCharge
from .parser import EpdParser, EpdParserError

logger = logging.getLogger(__name__)


class EpdDocumentListView(ListView):
    """View for listing EPD documents."""
    
    model = EpdDocument
    template_name = 'epd_parser/document_list.html'
    context_object_name = 'documents'
    paginate_by = 20
    
    def get_queryset(self) -> Any:
        """Get queryset with related service charges."""
        return EpdDocument.objects.prefetch_related('service_charges').order_by('-created_at')
    
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add additional context data."""
        context = super().get_context_data(**kwargs)
        context['total_documents'] = EpdDocument.objects.count()
        context['total_amount'] = sum(
            doc.total_with_insurance for doc in context['documents']
        )
        return context


class EpdDocumentDetailView(DetailView):
    """View for displaying EPD document details."""
    
    model = EpdDocument
    template_name = 'epd_parser/document_detail.html'
    context_object_name = 'document'
    
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add service charges to context."""
        context = super().get_context_data(**kwargs)
        context['service_charges'] = self.object.service_charges.all().order_by('order')
        return context


@require_http_methods(['GET', 'POST'])
def upload_epd(request: HttpRequest) -> HttpResponse:
    """View for uploading and parsing EPD PDF files."""
    
    if request.method == 'POST':
        upload_form = EpdUploadForm(request.POST, request.FILES)
        
        if upload_form.is_valid():
            try:
                # Get parsed data from the form
                parsed_data = upload_form.parsed_data
                
                # Create document form with parsed data
                # Always create form with parsed_data for initial display
                document_form = EpdDocumentForm(
                    data=request.POST,
                    files=request.FILES,
                    parsed_data=parsed_data
                )
                
                # If form is invalid, create a new form with initial data for display
                if not document_form.is_valid():
                    # Create a new form with initial data for display
                    display_form = EpdDocumentForm(
                        data=request.POST,
                        files=request.FILES,
                        parsed_data=parsed_data
                    )
                    # The form will automatically show errors when rendered
                    document_form = display_form
                
                if document_form.is_valid():
                    # Save the document and service charges
                    with transaction.atomic():
                        document = document_form.save(commit=False)
                        document.pdf_file = upload_form.cleaned_data['pdf_file']
                        document.save()
                        
                        # Create service charges
                        service_charges = parsed_data.get('service_charges', [])
                        for charge_data in service_charges:
                            ServiceCharge.objects.create(
                                document=document,
                                **charge_data
                            )
                    
                    messages.success(
                        request,
                        _('EPD document successfully uploaded and parsed!')
                    )
                    return redirect('epd_parser:document_detail', pk=document.pk)
                else:
                    # If document form is invalid, show errors
                    messages.error(
                        request,
                        _('Please correct the errors below.')
                    )
                    # Keep the document form for re-display
                    document_form = document_form
            except Exception as e:
                logger.error(f"Error saving EPD document: {e}")
                messages.error(
                    request,
                    _('An error occurred while saving the document. Please try again.')
                )
                document_form = None
        else:
            # If upload form is invalid, show errors
            messages.error(
                request,
                _('Please correct the errors below.')
            )
            document_form = None
    else:
        upload_form = EpdUploadForm()
        document_form = None
    
    return render(
        request,
        'epd_parser/upload.html',
        {
            'upload_form': upload_form,
            'document_form': document_form,
        }
    )


@require_http_methods(['GET', 'POST'])
def edit_epd(request: HttpRequest, pk: int) -> HttpResponse:
    """View for editing EPD document data."""
    
    document = get_object_or_404(EpdDocument, pk=pk)
    
    if request.method == 'POST':
        form = EpdDocumentForm(request.POST, instance=document)
        
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _('EPD document successfully updated!')
            )
            return redirect('epd_parser:document_detail', pk=document.pk)
        else:
            messages.error(
                request,
                _('Please correct the errors below.')
            )
    else:
        form = EpdDocumentForm(instance=document)
    
    return render(
        request,
        'epd_parser/edit.html',
        {
            'form': form,
            'document': document,
        }
    )


@require_http_methods(['POST'])
def delete_epd(request: HttpRequest, pk: int) -> HttpResponse:
    """View for deleting EPD documents."""
    
    document = get_object_or_404(EpdDocument, pk=pk)
    
    try:
        # Delete the PDF file
        if document.pdf_file:
            pdf_path = Path(document.pdf_file.path)
            if pdf_path.exists():
                pdf_path.unlink()
        
        # Delete the document (service charges will be deleted automatically)
        document.delete()
        
        messages.success(
            request,
            _('EPD document successfully deleted!')
        )
        
    except Exception as e:
        logger.error(f"Error deleting EPD document {pk}: {e}")
        messages.error(
            request,
            _('An error occurred while deleting the document.')
        )
    
    return redirect('epd_parser:document_list')


@require_http_methods(['GET'])
def download_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """View for downloading the original PDF file."""
    
    from django.http import FileResponse
    from django.conf import settings
    
    document = get_object_or_404(EpdDocument, pk=pk)
    
    if not document.pdf_file:
        messages.error(request, _('PDF file not found.'))
        return redirect('epd_parser:document_detail', pk=pk)
    
    try:
        pdf_path = Path(document.pdf_file.path)
        if not pdf_path.exists():
            messages.error(request, _('PDF file not found on disk.'))
            return redirect('epd_parser:document_detail', pk=pk)
        
        response = FileResponse(
            open(pdf_path, 'rb'),
            content_type='application/pdf'
        )
        response['Content-Disposition'] = f'attachment; filename="{document.pdf_file.name}"'
        return response
        
    except Exception as e:
        logger.error(f"Error downloading PDF for document {pk}: {e}")
        messages.error(request, _('An error occurred while downloading the file.'))
        return redirect('epd_parser:document_detail', pk=pk)


@require_http_methods(['GET'])
def search_epd(request: HttpRequest) -> HttpResponse:
    """View for searching EPD documents."""
    
    query = request.GET.get('q', '').strip()
    account_number = request.GET.get('account', '').strip()
    
    documents = EpdDocument.objects.all()
    
    if query:
        documents = documents.filter(
            models.Q(full_name__icontains=query) |
            models.Q(address__icontains=query) |
            models.Q(payment_period__icontains=query)
        )
    
    if account_number:
        documents = documents.filter(account_number__icontains=account_number)
    
    documents = documents.prefetch_related('service_charges').order_by('-created_at')
    
    return render(
        request,
        'epd_parser/search.html',
        {
            'documents': documents,
            'query': query,
            'account_number': account_number,
        }
    )


@require_http_methods(['GET'])
def statistics(request: HttpRequest) -> HttpResponse:
    """View for displaying EPD statistics."""
    
    from django.db.models import Sum, Count, Avg
    from django.utils import timezone
    
    # Get date range from request
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timezone.timedelta(days=days)
    
    # Get statistics
    recent_documents = EpdDocument.objects.filter(created_at__gte=start_date)
    
    stats = {
        'total_documents': EpdDocument.objects.count(),
        'recent_documents': recent_documents.count(),
        'total_amount': EpdDocument.objects.aggregate(
            total=Sum('total_with_insurance')
        )['total'] or Decimal('0.00'),
        'recent_amount': recent_documents.aggregate(
            total=Sum('total_with_insurance')
        )['total'] or Decimal('0.00'),
        'avg_amount': EpdDocument.objects.aggregate(
            avg=Avg('total_with_insurance')
        )['avg'] or Decimal('0.00'),
        'total_service_charges': ServiceCharge.objects.count(),
        'unique_accounts': EpdDocument.objects.values('account_number').distinct().count(),
    }
    
    # Get top services
    top_services = ServiceCharge.objects.values('service_name').annotate(
        count=Count('id'),
        total_amount=Sum('total')
    ).order_by('-total_amount')[:10]
    
    return render(
        request,
        'epd_parser/statistics.html',
        {
            'stats': stats,
            'top_services': top_services,
            'days': days,
        }
    ) 