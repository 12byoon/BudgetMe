// Shared: profile dropdown toggle
function toggleProfileDropdown() {
    const dropdown = document.getElementById('profileDropdown');
    if (!dropdown) return;
    const shown = dropdown.style.display === 'block';
    dropdown.style.display = shown ? 'none' : 'block';
}

window.addEventListener('click', function (event) {
    if (!event.target.matches('.profile-button')) {
        const dropdown = document.getElementById('profileDropdown');
        if (dropdown && dropdown.style.display === 'block') {
            dropdown.style.display = 'none';
        }
    }
});
