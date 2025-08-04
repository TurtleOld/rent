/**
 * Upload form handling with loading indicators
 */

document.addEventListener('DOMContentLoaded', function() {
    initUploadForm();
});

function initUploadForm() {
    const form = document.querySelector('form[enctype="multipart/form-data"]');
    const submitBtn = document.getElementById('submitBtn');
    const backBtn = document.getElementById('backBtn');
    const fileInput = document.querySelector('input[type="file"]');
    
    if (!form || !submitBtn) return;
    
    form.addEventListener('submit', function(e) {
        // Check if file is selected
        if (!fileInput.files.length) {
            e.preventDefault();
            showAlert('Пожалуйста, выберите PDF файл для загрузки', 'warning');
            return;
        }
        
        // Show loading state immediately
        setLoadingState(true);
        
        // Show progress indicator
        showProgressIndicator(true);
        
        // Show initial progress message
        showProgressMessage('Начинаем обработку документа...');
        updateProgressBar(10, 'Открываем документ...');
        
        // Simulate sequential progress updates (since we can't get real-time progress from server)
        let currentProgress = 10;
        const progressSteps = [
            { progress: 25, message: 'Анализируем содержимое...' },
            { progress: 40, message: 'Извлекаем данные...' },
            { progress: 60, message: 'Парсим страницы...' },
            { progress: 80, message: 'Сохраняем в базу данных...' },
            { progress: 95, message: 'Завершаем обработку...' }
        ];
        
        let stepIndex = 0;
        const progressInterval = setInterval(() => {
            if (stepIndex < progressSteps.length) {
                const step = progressSteps[stepIndex];
                currentProgress = step.progress;
                showProgressMessage(step.message);
                updateProgressBar(currentProgress, step.message);
                stepIndex++;
            } else {
                // If we've gone through all steps, gradually increase to 95%
                currentProgress = Math.min(95, currentProgress + 5);
                updateProgressBar(currentProgress, 'Завершаем обработку...');
            }
        }, 12000); // Increased to 5 seconds to match real processing time
        
        // Store interval ID to clear it later
        form.dataset.progressInterval = progressInterval;
        
        // Allow form to submit normally
        // The page will reload/redirect after successful submission
    });
    
    // Handle page errors or navigation away
    window.addEventListener('error', function() {
        // Reset loading state if there's an error
        setLoadingState(false);
    });
    
    // Handle form submission errors
    form.addEventListener('error', function() {
        setLoadingState(false);
        showAlert('Произошла ошибка при загрузке файла. Попробуйте еще раз.', 'danger');
    });
    
    // Note: Removed beforeunload handler to prevent browser confirmation dialog
    // during normal form submission
}

function setLoadingState(isLoading) {
    const submitBtn = document.getElementById('submitBtn');
    const backBtn = document.getElementById('backBtn');
    const btnContent = submitBtn.querySelector('.btn-content');
    const btnLoading = submitBtn.querySelector('.btn-loading');
    
    if (isLoading) {
        btnContent.style.display = 'none';
        btnLoading.style.display = 'inline-flex';
        submitBtn.disabled = true;
        submitBtn.classList.add('loading');
        
        // Disable back button to prevent navigation during upload
        if (backBtn) {
            backBtn.style.pointerEvents = 'none';
            backBtn.style.opacity = '0.6';
        }
    } else {
        btnContent.style.display = 'inline-flex';
        btnLoading.style.display = 'none';
        submitBtn.disabled = false;
        submitBtn.classList.remove('loading');
        
        // Re-enable back button
        if (backBtn) {
            backBtn.style.pointerEvents = 'auto';
            backBtn.style.opacity = '1';
        }
        
        // Hide progress indicator
        showProgressIndicator(false);
    }
}

function showProgressMessage(message) {
    const submitBtn = document.getElementById('submitBtn');
    const loadingText = submitBtn.querySelector('.loading-text');
    
    if (loadingText) {
        loadingText.textContent = message;
    }
}

function showProgressIndicator(show) {
    const progressContainer = document.getElementById('uploadProgress');
    if (progressContainer) {
        progressContainer.style.display = show ? 'block' : 'none';
    }
}

function updateProgressBar(percentage, message) {
    const progressBar = document.querySelector('#uploadProgress .progress-bar');
    const progressText = document.getElementById('progressText');
    
    if (progressBar) {
        progressBar.style.width = percentage + '%';
        progressBar.setAttribute('aria-valuenow', percentage);
    }
    
    if (progressText) {
        progressText.textContent = message;
    }
}

function showAlert(message, type = 'info') {
    // Use existing EPDApp.showAlert if available, otherwise create simple alert
    if (window.EPDApp && window.EPDApp.showAlert) {
        window.EPDApp.showAlert(message, type);
    } else {
        // Create simple alert
        const alertContainer = document.querySelector('.card-body') || document.body;
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
}

// Handle file input change to show selected file
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            const file = this.files[0];
            if (file) {
                // Show file info
                const fileInfo = document.createElement('div');
                fileInfo.className = 'alert alert-success mt-2';
                fileInfo.innerHTML = `
                    <i class="bi bi-check-circle"></i>
                    <strong>Выбран файл:</strong> ${file.name} (${formatFileSize(file.size)})
                `;
                
                // Remove existing file info
                const existingInfo = this.parentNode.querySelector('.alert-success');
                if (existingInfo) {
                    existingInfo.remove();
                }
                
                this.parentNode.appendChild(fileInfo);
            }
        });
    }
});

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
} 