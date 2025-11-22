// static/js/auth_script.js

document.addEventListener("DOMContentLoaded", () => {
    const container   = document.querySelector(".container");
    const signUpLink  = document.querySelector(".SignUpLink");
    const signInLink  = document.querySelector(".SignInLink");
    const adminToggle = document.getElementById("adminToggle");
    const adminCodeBox = document.getElementById("adminCodeBox");
    const flashCloseButtons = document.querySelectorAll(".flash-close");
    const flashes = document.querySelectorAll(".flash");

    // --- Toggle Login / Register (keeps all CSS animations) ---
    if (signUpLink) {
        signUpLink.addEventListener("click", (e) => {
            e.preventDefault();
            container.classList.add("active");
        });
    }

    if (signInLink) {
        signInLink.addEventListener("click", (e) => {
            e.preventDefault();
            container.classList.remove("active");
        });
    }

    // --- Admin toggle: show/hide Admin Code field ---
    if (adminToggle && adminCodeBox) {
        const updateAdminCodeVisibility = () => {
            if (adminToggle.checked) {
                adminCodeBox.style.display = "block";
            } else {
                adminCodeBox.style.display = "none";
            }
        };

        adminToggle.addEventListener("change", updateAdminCodeVisibility);
        updateAdminCodeVisibility(); // initial state
    }

    // --- Flash messages: close button ---
    flashCloseButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const flash = btn.closest(".flash");
            if (!flash) return;
            flash.classList.add("fade-out");
            setTimeout(() => flash.remove(), 500);
        });
    });

    // --- Auto fade-out flashes after a few seconds ---
    flashes.forEach(flash => {
        setTimeout(() => {
            flash.classList.add("fade-out");
            setTimeout(() => flash.remove(), 500);
        }, 4000);
    });
});
