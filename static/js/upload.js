document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('uploadForm');
    const submitBtn = document.getElementById('submitBtn');
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('pdf_file');
    
    // Only run on upload page
    if (!form || !submitBtn || !uploadArea || !fileInput) {
        return;
    }
    
    const uploadContent = uploadArea.querySelector('.upload-content');
    
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
    
    function handleFileSelect(file) {
        // Validate file type
        if (file.type !== 'application/pdf') {
            alert('Пожалуйста, выберите PDF файл.');
            return;
        }
        
        // Validate file size (10MB)
        if (file.size > 10 * 1024 * 1024) {
            alert('Размер файла должен быть меньше 10MB.');
            return;
        }
        
        // Update UI
        uploadArea.classList.add('has-file');
        uploadContent.innerHTML = `            <i class="bi bi-file-earmark-pdf display-1 text-success"></i>
            <h5 class="mt-3 text-success">${file.name}</h5>
            <p class="text-muted">Размер: ${(file.size / 1024 / 1024).toFixed(2)} MB</p>
            <small class="text-muted">Нажмите для выбора другого файла</small>
        `;
        
        // Enable submit button
        submitBtn.disabled = false;
    }
    
    // Form submission
    form.addEventListener('submit', function(e) {
        if (!fileInput.files.length) {
            alert('Пожалуйста, выберите PDF файл для загрузки.');
            e.preventDefault();
            return;
        }
        
        // Disable submit button to prevent double submission
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Загрузка...';
        
        // Let the form submit normally - no AJAX
        // The page will reload after server processing
    });
}); 