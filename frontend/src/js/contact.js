import { api } from "./api.js";

const form = document.getElementById("contact-form");
const alertBox = document.getElementById("contact-alert");
const submit = document.getElementById("contact-submit");

function show(message, kind) {
  alertBox.hidden = false;
  alertBox.className = `alert alert-${kind}`;
  alertBox.textContent = message;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  if (!data.name.trim() || !form.email.checkValidity()) {
    show("Please enter your name and a valid email address.", "error");
    return;
  }
  submit.disabled = true;
  try {
    await api("/public/contact", { method: "POST", body: data, auth: false });
    form.reset();
    show("Thanks, your request has been received. We'll be in touch soon.", "ok");
  } catch (err) {
    show(err.message, "error");
  } finally {
    submit.disabled = false;
  }
});
