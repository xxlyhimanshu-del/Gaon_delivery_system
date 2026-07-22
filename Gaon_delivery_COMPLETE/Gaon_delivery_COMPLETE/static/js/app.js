document.addEventListener("DOMContentLoaded", () => {
  const inputs = [...document.querySelectorAll(".qty-input")];
  const subtotalEl = document.getElementById("subtotal");
  const deliveryEl = document.getElementById("delivery-charge");
  const discountEl = document.getElementById("discount");
  const grandTotalEl = document.getElementById("grand-total");
  const couponInput = document.getElementById("coupon-code");

  function updateTotals() {
    let subtotal = 0;
    inputs.forEach(input => {
      subtotal += (Number(input.value) || 0) * (Number(input.dataset.price) || 0);
    });

    let deliveryCharge = 0;
    if (subtotal > 0 && subtotal < Number(window.freeDeliveryAbove || 500)) {
      deliveryCharge = Math.max(
        Number(window.minimumDeliveryCharge || 5),
        Math.round(subtotal * Number(window.deliveryPercent || 10) / 100)
      );
    }

    let discount = 0;
    if (couponInput && couponInput.value.trim().toUpperCase() === String(window.couponCode || "").toUpperCase()) {
      discount = Math.min(50, Math.round(subtotal * Number(window.couponPercent || 10) / 100));
    }

    if (subtotalEl) subtotalEl.textContent = subtotal;
    if (deliveryEl) deliveryEl.textContent = deliveryCharge;
    if (discountEl) discountEl.textContent = discount;
    if (grandTotalEl) grandTotalEl.textContent = Math.max(0, subtotal + deliveryCharge - discount);
  }

  document.querySelectorAll(".qty-control").forEach(control => {
    const input = control.querySelector(".qty-input");
    const max = Number(control.dataset.max) || 0;
    control.querySelector(".qty-minus").addEventListener("click", () => {
      input.value = Math.max(0, Number(input.value) - 1);
      updateTotals();
    });
    control.querySelector(".qty-plus").addEventListener("click", () => {
      input.value = Math.min(max, Number(input.value) + 1);
      updateTotals();
    });
  });

  if (couponInput) couponInput.addEventListener("input", updateTotals);

  const wishlist = new Set(JSON.parse(localStorage.getItem("wishlist") || "[]"));
  document.querySelectorAll(".wishlist-btn").forEach(button => {
    const id = button.dataset.id;
    if (wishlist.has(id)) button.classList.add("active");
    button.addEventListener("click", () => {
      if (wishlist.has(id)) wishlist.delete(id); else wishlist.add(id);
      button.classList.toggle("active");
      localStorage.setItem("wishlist", JSON.stringify([...wishlist]));
    });
  });

  let deferredPrompt;
  const installButton = document.getElementById("install-app");
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    deferredPrompt = event;
    if (installButton) installButton.hidden = false;
  });
  if (installButton) {
    installButton.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      installButton.hidden = true;
    });
  }

  updateTotals();
});
