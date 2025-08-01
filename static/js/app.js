/**
 * EPD Parser - Main JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all components
    initSearch();
    initFileUpload();
    initTooltips();
    initConfirmDialogs();
    initDataTables();
    initCharts();
});

/**
 * Search functionality
 */
function initSearch() {
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const searchForm = document.getElementById('searchForm');
    
    if (searchInput) {
        // Real-time search
        let searchTimeout;
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performSearch(this.value);
            }, 300);
        });
        
        // Search button click
        if (searchBtn) {
            searchBtn.addEventListener('click', function() {
                performSearch(searchInput.value);
            });
        }
        
        // Search form submit
        if (searchForm) {
            searchForm.addEventListener('submit', function(e) {
                e.preventDefault();
                performSearch(searchInput.value);
            });
        }
    }
}

function performSearch(query) {
    if (!query.trim()) {
        // Show all results if query is empty
        document.querySelectorAll('.document-row').forEach(row => {
            row.style.display = '';
        });
        return;
    }
    
    const rows = document.querySelectorAll('.document-row');
    const searchTerm = query.toLowerCase();
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        if (text.includes(searchTerm)) {
            row.style.display = '';
            highlightText(row, searchTerm);
        } else {
            row.style.display = 'none';
        }
    });
    
    // Update results count
    updateSearchResults();
}

function highlightText(element, searchTerm) {
    // Remove existing highlights
    element.querySelectorAll('.search-highlight').forEach(highlight => {
        const parent = highlight.parentNode;
        parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
        parent.normalize();
    });
    
    // Add new highlights
    const walker = document.createTreeWalker(
        element,
        NodeFilter.SHOW_TEXT,
        null,
        false
    );
    
    const textNodes = [];
    let node;
    while (node = walker.nextNode()) {
        textNodes.push(node);
    }
    
    textNodes.forEach(textNode => {
        const text = textNode.textContent;
        const regex = new RegExp(`(${searchTerm})`, 'gi');
        if (regex.test(text)) {
            const highlightedText = text.replace(regex, '<span class="search-highlight">$1</span>');
            const wrapper = document.createElement('span');
            wrapper.innerHTML = highlightedText;
            textNode.parentNode.replaceChild(wrapper, textNode);
        }
    });
}

function updateSearchResults() {
    const visibleRows = document.querySelectorAll('.document-row:not([style*="display: none"])');
    const resultsCount = document.getElementById('resultsCount');
    
    if (resultsCount) {
        resultsCount.textContent = visibleRows.length;
    }
}

/**
 * File upload functionality
 */
function initFileUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.querySelector('input[type="file"]');
    const uploadContent = uploadArea?.querySelector('.upload-content');
    const submitBtn = document.getElementById('submitBtn');
    
    if (uploadArea && fileInput) {
        // Drag and drop functionality
        uploadArea.addEventListener('dragover', function(e) {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        
        uploadArea.addEventListener('dragleave', function(e) {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
        });
        
        uploadArea.addEventListener('drop', function(e) {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                handleFileSelect(files[0]);
            }
        });
        
        // Click to select file
        uploadArea.addEventListener('click', function() {
            fileInput.click();
        });
        
        // File input change
        fileInput.addEventListener('change', function(e) {
            if (e.target.files.length > 0) {
                handleFileSelect(e.target.files[0]);
            }
        });
    }
}

function handleFileSelect(file) {
    const uploadArea = document.getElementById('uploadArea');
    const uploadContent = uploadArea?.querySelector('.upload-content');
    const submitBtn = document.getElementById('submitBtn');
    
    // Validate file type
    if (file.type !== 'application/pdf') {
        showAlert('Пожалуйста, выберите PDF файл.', 'danger');
        return;
    }
    
    // Validate file size (10MB)
    if (file.size > 10 * 1024 * 1024) {
        showAlert('Размер файла должен быть меньше 10MB.', 'danger');
        return;
    }
    
    // Update UI
    if (uploadArea) {
        uploadArea.classList.add('has-file');
    }
    
    if (uploadContent) {
        uploadContent.innerHTML = `
            <i class="bi bi-file-earmark-pdf display-1 text-success"></i>
            <h5 class="mt-3 text-success">${file.name}</h5>
            <p class="text-muted">Размер: ${(file.size / 1024 / 1024).toFixed(2)} MB</p>
            <small class="text-muted">Нажмите для выбора другого файла</small>
        `;
    }
    
    // Enable submit button
    if (submitBtn) {
        submitBtn.disabled = false;
    }
}

/**
 * Tooltips initialization
 */
function initTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

/**
 * Confirmation dialogs
 */
function initConfirmDialogs() {
    const deleteButtons = document.querySelectorAll('.btn-delete');
    
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            const message = this.dataset.confirm || 'Вы уверены, что хотите удалить этот элемент?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });
}

/**
 * Data tables enhancement
 */
function initDataTables() {
    const tables = document.querySelectorAll('.table-sortable');
    
    tables.forEach(table => {
        const headers = table.querySelectorAll('th[data-sort]');
        
        headers.forEach(header => {
            header.addEventListener('click', function() {
                const column = this.dataset.sort;
                const direction = this.dataset.direction === 'asc' ? 'desc' : 'asc';
                
                // Update all headers
                headers.forEach(h => h.dataset.direction = '');
                this.dataset.direction = direction;
                
                // Sort table
                sortTable(table, column, direction);
            });
        });
    });
}

function sortTable(table, column, direction) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    rows.sort((a, b) => {
        const aValue = a.querySelector(`td[data-${column}]`)?.dataset[column] || '';
        const bValue = b.querySelector(`td[data-${column}]`)?.dataset[column] || '';
        
        if (direction === 'asc') {
            return aValue.localeCompare(bValue);
        } else {
            return bValue.localeCompare(aValue);
        }
    });
    
    // Reorder rows
    rows.forEach(row => tbody.appendChild(row));
}

/**
 * Charts initialization
 */
function initCharts() {
    // Initialize charts if Chart.js is available
    if (typeof Chart !== 'undefined') {
        const chartElements = document.querySelectorAll('[data-chart]');
        
        chartElements.forEach(element => {
            const chartType = element.dataset.chart;
            const chartData = JSON.parse(element.dataset.chartData || '{}');
            
            new Chart(element, {
                type: chartType,
                data: chartData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                }
            });
        });
    }
}

/**
 * Utility functions
 */
function showAlert(message, type = 'info') {
    const alertContainer = document.getElementById('alertContainer') || document.body;
    const alertId = 'alert-' + Date.now();
    
    const alertHtml = `
        <div id="${alertId}" class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
    
    alertContainer.insertAdjacentHTML('afterbegin', alertHtml);
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        const alert = document.getElementById(alertId);
        if (alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }
    }, 5000);
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB'
    }).format(amount);
}

function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('ru-RU');
}

// Export functions for global use
window.EPDApp = {
    showAlert,
    formatCurrency,
    formatDate,
    performSearch
}; 