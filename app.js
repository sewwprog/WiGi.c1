"use strict";

document.documentElement.classList.add("js");

const menuButton = document.querySelector(".menu-button");
const mobileNav = document.querySelector("#mobile-nav");

function setMenuOpen(open) {
  if (!menuButton || !mobileNav) return;
  menuButton.setAttribute("aria-expanded", String(open));
  menuButton.setAttribute("aria-label", open ? "Закрити меню" : "Відкрити меню");
  mobileNav.classList.toggle("open", open);
  mobileNav.inert = !open;
  document.body.classList.toggle("menu-open", open);
}

if (menuButton && mobileNav) {
  menuButton.addEventListener("click", () => {
    setMenuOpen(menuButton.getAttribute("aria-expanded") !== "true");
  });
  mobileNav.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", () => setMenuOpen(false));
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && menuButton.getAttribute("aria-expanded") === "true") {
      setMenuOpen(false);
      menuButton.focus();
    }
  });
  document.addEventListener("click", event => {
    if (!menuButton.contains(event.target) && !mobileNav.contains(event.target)) setMenuOpen(false);
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 760) setMenuOpen(false);
  });
}

const tabs = [...document.querySelectorAll(".era-tab")];
const panels = [...document.querySelectorAll(".era-panel")];

function selectEra(target, focus = false) {
  const selected = tabs.find(tab => tab.dataset.target === target);
  if (!selected) return;
  tabs.forEach(tab => {
    const active = tab === selected;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  panels.forEach(panel => {
    panel.hidden = panel.dataset.panel !== target;
  });
  if (focus) selected.focus();
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectEra(tab.dataset.target));
  tab.addEventListener("keydown", event => {
    let next = index;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectEra(tabs[next].dataset.target, true);
  });
});

const joinForm = document.querySelector("#join-form");
const feedback = document.querySelector("#form-feedback");

async function copyApplication(message) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(message);
    return true;
  }
  const temp = document.createElement("textarea");
  temp.value = message;
  temp.setAttribute("readonly", "");
  temp.style.position = "fixed";
  temp.style.left = "-9999px";
  document.body.appendChild(temp);
  temp.select();
  const copied = document.execCommand("copy");
  temp.remove();
  return copied;
}

if (joinForm && feedback) {
  joinForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!joinForm.reportValidity()) return;

    const nickname = joinForm.elements.nickname.value.trim();
    const interest = joinForm.elements.interest.value;
    const motivation = joinForm.elements.motivation.value.trim();
    if (nickname.length < 2 || !interest) {
      feedback.textContent = "Вкажи нікнейм та обери напрям.";
      feedback.classList.add("is-error");
      return;
    }

    const message = [
      "Заявка до Імперії StoneLand II",
      "",
      "Нікнейм: " + nickname,
      "Напрям: " + interest,
      "Про себе: " + (motivation || "Не вказано")
    ].join("\n");

    try {
      const copied = await copyApplication(message);
      if (!copied) throw new Error("copy-failed");
      feedback.textContent = "Заявку скопійовано. Тепер надішли її представнику Імперії.";
      feedback.classList.remove("is-error");
    } catch (error) {
      feedback.textContent = "Браузер не дозволив копіювання. Виділи та скопіюй текст заявки нижче.";
      feedback.classList.add("is-error");
      let output = joinForm.querySelector(".copy-fallback");
      if (!output) {
        output = document.createElement("textarea");
        output.className = "copy-fallback";
        output.readOnly = true;
        output.setAttribute("aria-label", "Текст заявки для ручного копіювання");
        output.rows = 6;
        feedback.insertAdjacentElement("afterend", output);
      }
      output.value = message;
      output.focus();
      output.select();
    }
  });
}

const year = document.querySelector("#year");
if (year) year.textContent = String(new Date().getFullYear());

const reveals = document.querySelectorAll(".reveal");
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: "0px 0px -28px 0px" });
  reveals.forEach(element => observer.observe(element));
} else {
  reveals.forEach(element => element.classList.add("visible"));
}
