document
  .getElementById("registerForm")
  .addEventListener("submit", async function (event) {
    event.preventDefault();

    const formData = {
      firstName: document.getElementById("firstName").value,
      lastName: document.getElementById("lastName").value,
      email: document.getElementById("email").value,
      phone: document.getElementById("phone").value,
      institution: document.getElementById("institution").value || "N/A",
      password: document.getElementById("password").value,
      username: document.getElementById("username").value, // Add this line
    };

    console.log(formData); // Add this to check the form data

    const response = await fetch("https://5f6sz3-3001.csb.app/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formData),
    });

    const result = await response.json(); // Get the full response as JSON
    console.log(result); // Log the response for more details

    if (response.ok) {
      // Optional: show success message briefly
      document.getElementById("status").innerText =
        "Registration successful! Redirecting to login...";

      // Wait 1.5 seconds, then redirect to login page
      setTimeout(() => {
        window.location.href = "index.html"; // or whatever your login page is named
      }, 1500);
    } else {
      document.getElementById("status").innerText =
        result.error || "Error registering account.";
    }
  });