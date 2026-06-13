// navbarscript.js

// Dynamic show/hide
function show(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "";
}
function hide(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}

function logout() {
  // Close mobile menu if open
  const navCollapse = document.getElementById('navbarNavDropdown');
  const bsCollapse = bootstrap.Collapse.getInstance(navCollapse);
  if (bsCollapse) {
    bsCollapse.hide();
  }
  
  localStorage.removeItem("token");
  location.href = "index.html";
}
function updateNavbarLinks() {
  const loggedIn = Boolean(localStorage.getItem("token"));

  // Always visible
  show("navGraph");
  show("navTable");
  show("navSubmit");

  if (loggedIn) {
    show("navCetaraGPT");
    show("navLogout");
    hide("navAccountLoggedOut");
  } else {
    hide("navCetaraGPT");
    hide("navLogout");
    show("navAccountLoggedOut");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  requestAnimationFrame(() => {
    const navbar = document.querySelector(".navbar");
    const hero = document.getElementById("heroSection") || document.querySelector("main") || document.body;
    if (navbar && hero) {
      const navHeight = navbar.offsetHeight;
      const currentPadding = parseFloat(window.getComputedStyle(hero).paddingTop || "0");
      if (currentPadding < navHeight) {
        hero.style.paddingTop = `${navHeight}px`;
      }
    }
  });
  
  updateNavbarLinks();

// Smooth scrolling for in-page anchors
document.querySelectorAll('a[href^="#"]:not([href="#"])').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    e.preventDefault();
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      target.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    }
  });
});

  // Navbar background on scroll
  window.addEventListener('scroll', () => {
    const navbar = document.querySelector('.navbar');
    if (window.scrollY > 100) {
      navbar.style.background = 'rgba(2, 30, 38, 0.7)';
    } else {
      navbar.style.background = 'transparent';
    }
  });

  // Close mobile menu when clicking a link (except dropdown toggles)
  const navbarCollapse = document.getElementById('navbarNavDropdown');
  if (navbarCollapse) {
    navbarCollapse.addEventListener('click', function(event) {
      const clickedLink = event.target.closest('.nav-link:not(.dropdown-toggle)');
      const clickedDropdownItem = event.target.closest('.dropdown-item');
      
      if (clickedLink || clickedDropdownItem) {
        const bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
        if (bsCollapse) {
          bsCollapse.hide();
        }
      }
    });
  }

  // Close mobile menu when clicking outside
  document.addEventListener('click', function(event) {
    const navbarCollapse = document.getElementById('navbarNavDropdown');
    const navbarToggler = document.querySelector('.navbar-toggler');
    const navbar = document.querySelector('.navbar');
    
    if (navbarCollapse && navbarCollapse.classList.contains('show')) {
      if (!navbar.contains(event.target)) {
        const bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
        if (bsCollapse) {
          bsCollapse.hide();
        }
      }
    }
  });
});

