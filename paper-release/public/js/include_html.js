function includeHTML(callback) {
  const elements = document.querySelectorAll('[w3-include-html]');
  let total = elements.length;
  if (total === 0) {
    if (callback) callback();
    return;
  }

  elements.forEach((el) => {
    const file = el.getAttribute('w3-include-html');
    if (file) {
      fetch(file)
        .then(res => res.text())
        .then(data => {
          el.innerHTML = data;

          // ✅ Run all <script> tags inside the included content
          el.querySelectorAll("script").forEach((oldScript) => {
            const newScript = document.createElement("script");
            if (oldScript.src) {
              newScript.src = oldScript.src;
              newScript.async = false;
            } else {
              newScript.textContent = oldScript.textContent;
            }
            document.body.appendChild(newScript);
          });

          el.removeAttribute('w3-include-html');
          total--;
          if (total === 0 && callback) callback();
        });
    }
  });
}

