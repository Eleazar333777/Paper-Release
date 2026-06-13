document.addEventListener('DOMContentLoaded', function () {
  // Apply dark mode if saved in localStorage
  const isDark = localStorage.getItem('darkMode') === 'true';
  if (isDark) {
    document.documentElement.classList.add('dark-mode');
  }

  // Toggle behavior
  function toggleDarkMode() {
    const root = document.documentElement;
    const icon = document.getElementById('darkModeIcon');
    const button = document.getElementById('darkModeToggle');
    const dark = root.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', dark);

    icon.className = dark ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    button.className = dark ? 'btn btn-dark shadow' : 'btn btn-light shadow';
  }

  // Inject dark mode styles
  const style = document.createElement('style');
  style.textContent = `
    .dark-mode {
      background-color: #121212 !important;
      color: #f1f1f1 !important;
    }

    .dark-mode body {
      background-color: #121212 !important;
      color: #f1f1f1 !important;
    }

    .dark-mode .navbar {
      background-color: #1f1f1f !important;
    }

    .dark-mode .navbar-brand,
    .dark-mode .nav-link {
      color: #f1f1f1 !important;
    }

    .dark-mode .navbar-toggler {
      border-color: #444 !important;
    }

    .dark-mode .navbar-toggler-icon {
      background-image: url("data:image/svg+xml;charset=utf8,<svg viewBox='0 0 30 30' xmlns='http://www.w3.org/2000/svg'><path stroke='rgba(255,255,255,0.8)' stroke-width='2' stroke-linecap='round' stroke-miterlimit='10' d='M4 7h22M4 15h22M4 23h22'/></svg>") !important;
    }


    .dark-mode .bg-light {
      background-color: #1e1e1e !important;
      color: #f1f1f1 !important;
    }

    .dark-mode #loginSection,
    .dark-mode #dataSection,
    .dark-mode .filters,
    .dark-mode .table-responsive {
      background-color: #1e1e1e;
      color: #f1f1f1 ;
      border-radius: 0.5rem;
    }

    .dark-mode #loginSection h2,
    .dark-mode #dataSection h2 {
      color: #109CCC !important;
    }

    .dark-mode .login-container {
      background-color: #2b2b2b;
      color: #f1f1f1;
    }

    .dark-mode .login-container input[type="text"],
    .dark-mode .login-container input[type="password"],
    .dark-mode .form-control,
    .dark-mode .form-select {
      background-color: #2b2b2b;
      color: #f1f1f1;
      border-color: #444;
    }

    .dark-mode .form-control::placeholder,
    .dark-mode .login-container input::placeholder {
      color: #aaa;
    }

    .dark-mode .table {
      background-color: #1e1e1e;
      color: #f1f1f1;
    }

    .dark-mode .table-striped tbody tr:nth-of-type(odd) {
      background-color: #2a2a2a;
    }

    .dark-mode .table-striped tbody tr:nth-of-type(even) {
      background-color: #232323;
    }

    .dark-mode th,
    .dark-mode td {
      border-color: #444;
    }

    .dark-mode .dropdown-menu {
      background-color: #2b2b2b;
      color: #f1f1f1;
    }

    .dark-mode .dropdown-menu .dropdown-item {
      color: #f1f1f1 !important;
    }

    .dark-mode .dropdown-item:hover,
    .dark-mode .dropdown-item:focus {
      background-color: #3a3a3a !important;
    }

    .dark-mode .btn-light {
      background-color: #3a3a3a !important;
      color: #f1f1f1 !important;
    }

    .dark-mode .btn-dark {
      background-color: #f1f1f1 !important;
      color: #000 !important;
    }

    .dark-mode .form-section {
      background-color: #1e1e1e !important;
      color: #f1f1f1 !important;
    }

    .dark-mode .form-section label {
      color: #ccc !important;
    }

    .dark-mode .form-control::placeholder {
      color: #aaa !important;
    }

    .dark-mode #about {
      background-color: #1e1e1e !important;
      color: #f1f1f1 !important;
    }

    .dark-mode #about h2,
    .dark-mode #about h3,
    .dark-mode #about h4 {
      color: #109CCC !important;
    }

     .dark-mode #about h4 {
      color: #f1f1f1 !important;
    }


    .dark-mode #about p {
      color: #ddd !important;
    }

    .dark-mode .team-member img {
      border-color: #f1f1f1 !important;
    }

    .dark-mode #pfas {
      background-color: #1e1e1e;
      color: #f1f1f1;
    }
    .dark-mode #pfas h2,
    .dark-mode #pfas h3 {
      color: #109CCC;
    }
    .dark-mode #pfas p {
      color: #ddd;
    }


    @media (max-width: 576px) {
      .dark-mode .navbar-collapse {
        background-color: #1f1f1f !important;
      }
    }

    /* Dark mode styles for chatbot */
    .dark-mode .chat-header {
      background: #1f1f1f;
      color: #f1f1f1;
    }

    .dark-mode .chat-header .btn-clear {
      color: #109CCC;
    }

    .dark-mode .chat-header .btn-clear:hover {
      color: #ffffff;
    }

    .dark-mode #chat-container-ui {
      background: #121212;
      border-color: #333;
    }

    .dark-mode #chat-log-ui {
      background: #1e1e1e;
      color: #f1f1f1;
    }

    .dark-mode .message.user .bubble {
      background: #2d6a6a;
      color: #ffffff;
    }

    .dark-mode .message.bot .bubble {
      background: #2a2a2a;
      color: #f1f1f1;
    }

    .dark-mode .input-group {
      background: #1f1f1f;
      border-top: 1px solid #444;
    }

    .dark-mode #chat-input-ui {
      background-color: #2a2a2a;
      color: #f1f1f1;
      border-color: #444;
    }

    .dark-mode #chat-input-ui::placeholder {
      color: #aaa;
    }

    .dark-mode .btn-send {
      background-color: #333;
      color: #f1f1f1;
    }

    .dark-mode .container {
      background-color: #121212 !important;
      border: none !important;
      box-shadow: none !important;
    }

  `;
  document.head.appendChild(style);

  // Inject toggle button
  const button = document.createElement('button');
  button.id = 'darkModeToggle';
  button.className = isDark ? 'btn btn-dark shadow' : 'btn btn-light shadow';
  button.onclick = toggleDarkMode;

  button.style.position = 'fixed';
  button.style.bottom = '1rem';
  button.style.right = '1rem';
  button.style.zIndex = '1050';
  button.style.width = '3rem';
  button.style.height = '3rem';
  button.style.borderRadius = '50%';
  button.style.display = 'flex';
  button.style.alignItems = 'center';
  button.style.justifyContent = 'center';
  button.style.cursor = 'pointer';

  const icon = document.createElement('i');
  icon.id = 'darkModeIcon';
  icon.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-fill';

  button.appendChild(icon);
  document.body.appendChild(button);
});
