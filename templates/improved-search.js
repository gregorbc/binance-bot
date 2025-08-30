// Add this to your JavaScript in index.html
function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// Replace direct filterPositions with debounced version
document.getElementById('position-search').addEventListener('input', 
    debounce(filterPositions, 300)
);

// Replace direct filterTrades with debounced version
document.getElementById('trade-search').addEventListener('input',
    debounce(filterTrades, 300)
);