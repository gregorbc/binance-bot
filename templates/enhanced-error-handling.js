// Add this to your JavaScript in index.html
async function apiCall(endpoint, options = {}, button = null) {
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="loader"></span> Procesando...';
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        let responseData;
        
        try {
            responseData = await response.json();
        } catch (parseError) {
            throw new Error(`Error de formato en la respuesta: ${parseError.message}`);
        }
        
        if (!response.ok) {
            const errorMsg = responseData.message || `Error ${response.status}: ${response.statusText}`;
            throw new Error(errorMsg);
        }
        
        if (responseData.message) {
            showToast(responseData.message, 'success');
        }
        
        return responseData;
    } catch (error) {
        const errorMessage = error.message || 'Error desconocido';
        showToast(errorMessage, 'error');
        addLogEntry(`❌ Error en API (${endpoint}): ${errorMessage}`, 'error');
        
        // Show more detailed feedback for common issues
        if (errorMessage.includes('Failed to fetch') || errorMessage.includes('NetworkError')) {
            showToast('Problema de conexión. Verifica tu red.', 'error');
        } else if (errorMessage.includes('Timeout')) {
            showToast('La operación tardó demasiado. Inténtalo de nuevo.', 'error');
        }
        
        throw error;
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = button.dataset.originalText || 'Enviar';
        }
    }
}