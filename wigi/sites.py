"""Custom Domain Virtual Hosting & Website Builder engine for WiGi Server / WiGi OS.

Allows creating multi-file websites inside the server workspace and hosting them
under ANY custom domain (e.g. `myshop.ua`, `vitaliy.dev`, `cyber.wigi`) via:
  1. HTTP `Host` header virtual hosting (including zero-config `<slug>.localhost:<port>`
     and `<slug>.<lan_ip>.nip.io:<port>`, plus `/etc/hosts` or real DNS).
  2. Built-in WiGi OS Browser native domain resolution (`https://<domain>`).
  3. Universal public gateway `/s/<domain>/...` (works behind cloud proxies too).
"""

from __future__ import annotations

from datetime import datetime
import html
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shutil
from typing import Any

from wigi.workspace import resolve_safe_path, to_rel_posix

SITES_FILENAME = ".wigi_sites.json"

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")

TEMPLATE_CHOICES = ("landing", "store", "portfolio", "blog", "webapp", "blank")


def normalize_domain(raw_domain: str, allow_single_label: bool = False) -> str:
    """Validate and normalize any custom domain like `myshop.ua` or `app.wigi`."""
    cleaned = raw_domain.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.split("/", 1)[0].split(":", 1)[0].strip(".")
    if not cleaned:
        raise ValueError("Вкажи доменне ім'я (наприклад: myshop.ua або project.dev).")
    if "." not in cleaned and not allow_single_label:
        cleaned = f"{cleaned}.wigi"
    label_ok = bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", cleaned))
    if (not _DOMAIN_RE.fullmatch(cleaned) and not (allow_single_label and label_ok)) or _IPV4_RE.fullmatch(cleaned):
        raise ValueError(
            f"Некоректний формат домену '{raw_domain}'. Приклад: myshop.ua, studio.dev, app.wigi"
        )
    if cleaned in ("localhost", "127.0.0.1", "0.0.0.0"):
        raise ValueError("Цей системний хост зарезервовано сервером.")
    return cleaned


def domain_to_slug(domain: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")[:48] or "site"


def build_localhost_alias(domain: str) -> str:
    """Return a zero-config RFC 6761 `.localhost` domain that Chrome/Edge/Firefox resolve to 127.0.0.1."""
    if domain.endswith(".localhost"):
        return domain
    slug = domain_to_slug(domain)
    return f"{slug}.localhost"


def _load_raw_sites(workspace_dir: Path) -> list[dict[str, Any]]:
    path = workspace_dir / SITES_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sites"), list):
            return data["sites"]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _save_raw_sites(workspace_dir: Path, sites: list[dict[str, Any]]) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = workspace_dir / SITES_FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sites": sites}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_sites(workspace_dir: Path) -> list[dict[str, Any]]:
    sites = _load_raw_sites(workspace_dir)
    for s in sites:
        dom = str(s.get("domain", ""))
        s.setdefault("localhost_alias", build_localhost_alias(dom))
        s.setdefault("visits", 0)
        s.setdefault("enabled", True)
    return sites


def get_site_by_domain(workspace_dir: Path, domain_or_alias: str) -> dict[str, Any] | None:
    needle = domain_or_alias.strip().lower().split(":", 1)[0].rstrip(".")
    if not needle:
        return None
    if needle.startswith("www."):
        needle_no_www = needle[4:]
    else:
        needle_no_www = needle

    for site in list_sites(workspace_dir):
        dom = str(site.get("domain", "")).lower()
        alias = str(site.get("localhost_alias", "")).lower()
        base_label = dom.split(".", 1)[0]
        if needle in (dom, alias) or needle_no_www == dom:
            return site
        # Support `<base>.localhost` if unambiguous and `<slug>.<ip>.nip.io`
        if needle == f"{base_label}.localhost":
            return site
        if (needle.endswith(".nip.io") or needle.endswith(".sslip.io")) and (
            needle.startswith(f"{domain_to_slug(dom)}.") or needle.startswith(f"{base_label}.")
        ):
            return site
    return None


def resolve_vhost_request(workspace_dir: Path, host_header: str, server_hostname: str = "") -> dict[str, Any] | None:
    """Check if HTTP `Host` header targets a hosted custom domain rather than the server admin UI."""
    if not host_header:
        return None
    host = host_header.strip().lower().split(":", 1)[0].rstrip(".")
    if not host or host in ("localhost", "127.0.0.1", "0.0.0.0", server_hostname.lower()):
        return None
    if _IPV4_RE.match(host) or host.endswith(".e2b.app") or host.endswith(".e2b.dev"):
        return None
    return get_site_by_domain(workspace_dir, host)


def record_site_visit(workspace_dir: Path, site_id: str) -> None:
    sites = _load_raw_sites(workspace_dir)
    changed = False
    for s in sites:
        if s.get("id") == site_id:
            s["visits"] = int(s.get("visits", 0)) + 1
            s["last_visit_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            changed = True
            break
    if changed:
        _save_raw_sites(workspace_dir, sites)


def is_site_accessible(site: dict[str, Any], peer_ip: str, forwarded_ip: str = "") -> bool:
    """A local binding needs loopback at the socket and, if forwarded, at the original client."""
    if not site.get("local_only", False):
        return True
    try:
        return ipaddress.ip_address(peer_ip).is_loopback and (
            not forwarded_ip or ipaddress.ip_address(forwarded_ip).is_loopback
        )
    except ValueError:
        return False


def create_site(
    workspace_dir: Path,
    domain: str,
    title: str = "",
    template: str = "landing",
    folder: str = "",
    accent: str = "#38bdf8",
    entry_file: str = "",
    local_only: bool = False,
) -> dict[str, Any]:
    clean_domain = normalize_domain(domain, allow_single_label=bool(entry_file.strip()))
    sites = list_sites(workspace_dir)
    for existing in sites:
        if existing["domain"].lower() == clean_domain:
            raise ValueError(f"Домен '{clean_domain}' вже зайнятий іншим сайтом на сервері.")

    tpl = template.strip().lower() if template else "landing"
    if tpl not in TEMPLATE_CHOICES:
        tpl = "landing"

    slug = domain_to_slug(clean_domain)
    # Selecting an HTML file mounts that exact file as /, without creating or copying it.
    if entry_file.strip():
        chosen = resolve_safe_path(workspace_dir, entry_file)
        rel_entry = to_rel_posix(workspace_dir, chosen)
        if (not chosen.is_file() or chosen.suffix.lower() not in (".html", ".htm")
                or not rel_entry or any(part.startswith(".") for part in Path(rel_entry).parts)):
            raise ValueError("Обери існуючий HTML-файл у робочій папці сервера.")
        target_dir = chosen.parent
        tpl = "file"
        local_only = True  # file bindings are always private to this machine
    else:
        rel_folder = folder.strip().strip("/\\") or f"sites/{slug}"
        target_dir = resolve_safe_path(workspace_dir, rel_folder)
        if target_dir == workspace_dir.resolve() or any(part.startswith('.') for part in Path(rel_folder).parts):
            raise ValueError("Для сайту обери окрему публічну папку без прихованих системних файлів.")
        chosen = target_dir / "index.html"

    candidate_alias = build_localhost_alias(clean_domain)
    if any(candidate_alias == old.get("localhost_alias") or clean_domain == old.get("localhost_alias") for old in sites):
        raise ValueError("Локальний alias цього домену вже зайнято.")
    if not entry_file.strip():
        target_dir.mkdir(parents=True, exist_ok=True)
        if not chosen.exists():
            _scaffold_site_files(target_dir, clean_domain, title.strip() or clean_domain, tpl, accent=accent)

    clean_title = title.strip() or clean_domain
    site_record = {
        "id": "site_" + secrets.token_hex(4),
        "domain": clean_domain,
        "localhost_alias": build_localhost_alias(clean_domain),
        "title": clean_title,
        "folder": to_rel_posix(workspace_dir, target_dir),
        "entry": to_rel_posix(workspace_dir, chosen),
        "local_only": local_only,
        "template": tpl,
        "accent": accent,
        "enabled": True,
        "visits": 0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    sites.append(site_record)
    _save_raw_sites(workspace_dir, sites)
    return site_record


def update_site(
    workspace_dir: Path,
    site_id: str,
    domain: str | None = None,
    title: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    sites = list_sites(workspace_dir)
    target: dict[str, Any] | None = None
    for s in sites:
        if s.get("id") == site_id:
            target = s
            break
    if target is None:
        raise ValueError("Сайт не знайдено.")

    if domain is not None and domain.strip():
        new_dom = normalize_domain(domain, allow_single_label=target.get("template") == "file")
        for other in sites:
            if other.get("id") != site_id and other.get("domain") == new_dom:
                raise ValueError(f"Домен '{new_dom}' вже використовується.")
        alias = build_localhost_alias(new_dom)
        if any(other.get("id") != site_id and (alias == other.get("localhost_alias") or new_dom == other.get("localhost_alias")) for other in sites):
            raise ValueError("Локальний alias цього домену вже зайнято.")
        target["domain"] = new_dom
        target["localhost_alias"] = build_localhost_alias(new_dom)

    if title is not None and title.strip():
        target["title"] = title.strip()

    if enabled is not None:
        target["enabled"] = bool(enabled)

    _save_raw_sites(workspace_dir, sites)
    return target


def delete_site(workspace_dir: Path, site_id: str, delete_files: bool = False) -> bool:
    sites = list_sites(workspace_dir)
    target: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for s in sites:
        if s.get("id") == site_id:
            target = s
        else:
            remaining.append(s)
    if target is None:
        return False

    _save_raw_sites(workspace_dir, remaining)
    if delete_files and target.get("folder") and target.get("template") != "file":
        try:
            folder_path = resolve_safe_path(workspace_dir, str(target["folder"]))
            if folder_path != workspace_dir.resolve() and folder_path.exists():
                shutil.rmtree(folder_path, ignore_errors=True)
        except ValueError:
            pass
    return True


def serve_site_file(workspace_dir: Path, site: dict[str, Any], sub_path: str) -> tuple[int, str, bytes]:
    """Return `(http_status, filename_for_mime, body_bytes)` for a request to `site`."""
    if not site.get("enabled", True):
        offline_html = f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8"/><title>{html.escape(site['domain'])} — Офлайн</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#090d16;color:#e2e8f0;font-family:system-ui,sans-serif;text-align:center;}}
.card{{background:#11192b;border:1px solid #263554;padding:32px;border-radius:16px;max-width:440px;}}</style></head>
<body><div class="card"><h2>⏸ {html.escape(site['domain'])}</h2><p style="color:#94a3b8;line-height:1.5;">Цей домен зареєстровано на сервері WiGi, але сайт зараз у режимі чернетки (вимкнений власником).</p></div></body></html>"""
        return 503, "offline.html", offline_html.encode("utf-8")

    site_root = resolve_safe_path(workspace_dir, str(site["folder"]))
    from urllib.parse import unquote

    rel = unquote(sub_path or "").strip().lstrip("/")
    if any(part.startswith(".") for part in Path(rel).parts) or "\\" in rel:
        return 404, "404.html", b"Not found"
    try:
        cand = resolve_safe_path(site_root, rel) if rel else resolve_safe_path(workspace_dir, str(site["entry"]))
    except ValueError:
        return 404, "404.html", b"Not found"

    if cand.is_dir():
        cand = cand / "index.html"
    elif not cand.exists() and not cand.suffix:
        # Clean URL fallback: /about -> /about.html or /about/index.html
        if (cand.with_suffix(".html")).exists():
            cand = cand.with_suffix(".html")
        elif (cand / "index.html").exists():
            cand = cand / "index.html"

    if site_root.resolve() not in cand.resolve().parents:
        return 404, "404.html", b"Not found"
    # Single-file bindings expose only the chosen HTML plus ordinary static assets.
    if site.get("template") == "file":
        entry = resolve_safe_path(workspace_dir, str(site["entry"]))
        static_extensions = {".css", ".js", ".mjs", ".json", ".png", ".jpg", ".jpeg", ".gif",
                             ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf",
                             ".mp3", ".mp4", ".webm", ".wav", ".avif"}
        if cand.resolve() != entry and (site_root.resolve() == workspace_dir.resolve()
                                        or cand.suffix.lower() not in static_extensions):
            return 404, "404.html", b"Not found"

    if not cand.exists() or not cand.is_file():
        custom_404 = site_root / "404.html"
        if custom_404.exists() and site_root.resolve() in custom_404.resolve().parents:
            return 404, "404.html", custom_404.read_bytes()
        not_found = f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8"/><title>404 — {html.escape(site['domain'])}</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#090d16;color:#e2e8f0;font-family:system-ui,sans-serif;text-align:center;}}</style></head>
<body><div><h1 style="font-size:52px;margin:0;color:#38bdf8;">404</h1><p style="color:#94a3b8;">Сторінку не знайдено на домені <strong>{html.escape(site['domain'])}</strong></p><a href="./" style="color:#38bdf8;">На головну</a></div></body></html>"""
        return 404, "404.html", not_found.encode("utf-8")

    if rel == "" or (cand.name == "index.html" and rel == "index.html"):
        record_site_visit(workspace_dir, str(site["id"]))

    return 200, cand.name, cand.read_bytes()


# ---------------------------------------------------------------------------
# Multi-file Website Template Generators
# ---------------------------------------------------------------------------

def _scaffold_site_files(
    target_dir: Path,
    domain: str,
    title: str,
    template: str,
    accent: str = "#38bdf8",
) -> None:
    safe_title = html.escape(title)
    safe_dom = html.escape(domain)

    if template == "store":
        (target_dir / "style.css").write_text(
            f""":root {{ --accent: {accent}; --bg: #080c15; --card: #121a2d; --border: #233252; --text: #f1f5f9; --muted: #94a3b8; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
header {{ position: sticky; top: 0; background: rgba(8,12,21,0.88); backdrop-filter: blur(14px); border-bottom: 1px solid var(--border); padding: 16px 28px; display: flex; justify-content: space-between; align-items: center; z-index: 20; }}
.logo {{ font-size: 20px; font-weight: 800; letter-spacing: -0.02em; }}
.logo span {{ color: var(--accent); }}
.cart-btn {{ background: var(--accent); color: #04121f; border: none; padding: 9px 16px; border-radius: 99px; font-weight: 700; cursor: pointer; }}
.hero {{ max-width: 1080px; margin: 36px auto 20px; padding: 0 24px; display: flex; justify-content: space-between; align-items: center; gap: 20px; flex-wrap: wrap; }}
.filters {{ max-width: 1080px; margin: 0 auto 20px; padding: 0 24px; display: flex; gap: 8px; flex-wrap: wrap; }}
.f-btn {{ background: var(--card); color: var(--muted); border: 1px solid var(--border); padding: 7px 14px; border-radius: 99px; cursor: pointer; font-weight: 600; }}
.f-btn.active {{ border-color: var(--accent); color: var(--text); }}
.grid {{ max-width: 1080px; margin: 0 auto 60px; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fill, minmax(235px, 1fr)); gap: 18px; }}
.item {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 18px; display: flex; flex-direction: column; gap: 10px; transition: transform .15s; }}
.item:hover {{ transform: translateY(-3px); border-color: var(--accent); }}
.thumb {{ height: 120px; border-radius: 12px; background: linear-gradient(135deg, rgba(56,189,248,0.18), rgba(168,85,247,0.18)); display: flex; align-items: center; justify-content: center; font-size: 40px; }}
.price {{ font-size: 18px; font-weight: 800; color: var(--accent); }}
.buy {{ background: #1e293b; color: #fff; border: 1px solid var(--border); padding: 9px; border-radius: 10px; cursor: pointer; font-weight: 700; margin-top: auto; }}
.buy:hover {{ background: var(--accent); color: #04121f; }}
.drawer {{ position: fixed; right: 0; top: 0; bottom: 0; width: 340px; max-width: 100%; background: #0e1526; border-left: 1px solid var(--border); padding: 22px; display: flex; flex-direction: column; gap: 12px; z-index: 50; transform: translateX(100%); transition: transform .22s; }}
.drawer.open {{ transform: translateX(0); }}
""",
            encoding="utf-8",
        )
        (target_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title} — Інтернет-магазин</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <header>
    <div class="logo">{safe_title} <span>• {safe_dom}</span></div>
    <button class="cart-btn" id="openCart">Кошик (<span id="cartCount">0</span>)</button>
  </header>
  <section class="hero">
    <div>
      <h1 style="font-size:34px; margin-bottom:8px;">Сучасні гаджети та девайси</h1>
      <p style="color:var(--muted);">Працює на власному домені <strong>{safe_dom}</strong> у середовищі WiGi Server.</p>
    </div>
  </section>
  <div class="filters" id="filters"></div>
  <main class="grid" id="catalog"></main>
  <aside class="drawer" id="drawer">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h3>Ваш кошик</h3>
      <button id="closeCart" style="background:none;border:none;color:#fff;font-size:20px;cursor:pointer;">✕</button>
    </div>
    <div id="cartItems" style="flex:1; overflow-y:auto;"></div>
    <div style="border-top:1px solid var(--border); padding-top:12px;">
      <div style="display:flex; justify-content:space-between; margin-bottom:12px; font-weight:800;">
        <span>Разом:</span><span id="cartTotal">0 ₴</span>
      </div>
      <button class="cart-btn" id="checkoutBtn" style="width:100%;">Оформити замовлення</button>
    </div>
  </aside>
  <script src="app.js"></script>
</body>
</html>
""",
            encoding="utf-8",
        )
        (target_dir / "app.js").write_text(
            """const PRODUCTS = [
  { id: 1, name: "Механічна клавіатура Pro", cat: "Периферія", price: 3499, icon: "⌨️" },
  { id: 2, name: "Бездротові навушники Studio", cat: "Аудіо", price: 4299, icon: "🎧" },
  { id: 3, name: "Ультраширокий монітор 34 дюйми", cat: "Дисплеї", price: 16999, icon: "🖥" },
  { id: 4, name: "Ігрова миша Ultralight", cat: "Периферія", price: 2199, icon: "🖱" },
  { id: 5, name: "USB-C Док-станція 12-в-1", cat: "Аксесуари", price: 2899, icon: "🔌" },
  { id: 6, name: "Стрімінговий мікрофон Wave", cat: "Аудіо", price: 3899, icon: "🎙" }
];
let activeCat = "Усі";
const cart = [];

function render() {
  const cats = ["Усі", ...new Set(PRODUCTS.map(p => p.cat))];
  const fEl = document.getElementById("filters");
  fEl.innerHTML = "";
  cats.forEach(c => {
    const b = document.createElement("button");
    b.className = "f-btn" + (c === activeCat ? " active" : "");
    b.textContent = c;
    b.onclick = () => { activeCat = c; render(); };
    fEl.appendChild(b);
  });

  const catEl = document.getElementById("catalog");
  catEl.innerHTML = "";
  PRODUCTS.filter(p => activeCat === "Усі" || p.cat === activeCat).forEach(p => {
    const d = document.createElement("div");
    d.className = "item";
    d.innerHTML = `<div class="thumb">${p.icon}</div><div style="font-size:12px;color:#94a3b8;">${p.cat}</div><strong>${p.name}</strong><div class="price">${p.price} ₴</div><button class="buy">У кошик</button>`;
    d.querySelector(".buy").onclick = () => { cart.push(p); updateCart(); };
    catEl.appendChild(d);
  });
}

function updateCart() {
  document.getElementById("cartCount").textContent = cart.length;
  const box = document.getElementById("cartItems");
  box.innerHTML = cart.length ? "" : "<p style='color:#94a3b8;'>Кошик порожній</p>";
  let sum = 0;
  cart.forEach((it, idx) => {
    sum += it.price;
    const r = document.createElement("div");
    r.style.cssText = "display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1e293b;font-size:14px;";
    r.innerHTML = `<span>${it.name}</span><span>${it.price} ₴ <button data-i="${idx}" style="background:none;border:none;color:#ef4444;cursor:pointer;">×</button></span>`;
    r.querySelector("button").onclick = () => { cart.splice(idx, 1); updateCart(); };
    box.appendChild(r);
  });
  document.getElementById("cartTotal").textContent = sum + " ₴";
}

document.getElementById("openCart").onclick = () => document.getElementById("drawer").classList.add("open");
document.getElementById("closeCart").onclick = () => document.getElementById("drawer").classList.remove("open");
document.getElementById("checkoutBtn").onclick = () => {
  if (!cart.length) return alert("Додайте товари у кошик!");
  alert("Замовлення прийнято! Дякуємо за покупку.");
  cart.length = 0;
  updateCart();
  document.getElementById("drawer").classList.remove("open");
};
render();
updateCart();
""",
            encoding="utf-8",
        )
        return

    if template == "portfolio":
        (target_dir / "style.css").write_text(
            f""":root {{ --accent: {accent}; --bg: #070b14; --card: #101829; --border: #22304f; --text: #e2e8f0; --muted: #94a3b8; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, sans-serif; background: radial-gradient(circle at top right, rgba(56,189,248,0.14), var(--bg) 55%); color: var(--text); line-height: 1.6; }}
.wrap {{ max-width: 960px; margin: 0 auto; padding: 48px 24px; }}
.badge {{ display: inline-block; padding: 5px 12px; border-radius: 99px; background: rgba(56,189,248,0.14); color: var(--accent); font-size: 13px; font-weight: 700; margin-bottom: 14px; }}
h1 {{ font-size: 44px; line-height: 1.12; margin-bottom: 14px; }}
.bento {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 34px; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 22px; }}
.tag {{ display: inline-block; background: #1a2640; padding: 4px 10px; border-radius: 8px; font-size: 12.5px; margin: 4px 4px 0 0; }}
""",
            encoding="utf-8",
        )
        (target_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title} — Портфоліо</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <div class="wrap">
    <span class="badge">● Online на {safe_dom}</span>
    <h1>Привіт, це {safe_title}</h1>
    <p style="color:var(--muted); max-width:620px; font-size:18px;">Full-Stack розробка, Python-сервери, автоматизація та сучасні веб-інтерфейси.</p>
    <div class="bento">
      <div class="card"><h3>🚀 Проєкт Alpha</h3><p style="color:var(--muted);margin-top:6px;">Власне хмарне середовище та віртуальний хостинг доменів.</p></div>
      <div class="card"><h3>⚡ Стек технологій</h3><div style="margin-top:8px;"><span class="tag">Python</span><span class="tag">JavaScript</span><span class="tag">HTML5/CSS3</span><span class="tag">GitHub</span><span class="tag">Linux / WSL</span></div></div>
      <div class="card"><h3>📬 Зв'язок</h3><p style="color:var(--muted);margin-top:6px;">Напиши мені для співпраці або замов розробку під ключ.</p><button id="pingBtn" style="margin-top:12px;background:var(--accent);color:#04121f;border:none;padding:9px 16px;border-radius:9px;font-weight:700;cursor:pointer;">Надіслати привіт</button><div id="msg" style="margin-top:8px;color:#86efac;font-size:13px;"></div></div>
    </div>
  </div>
  <script src="app.js"></script>
</body>
</html>
""",
            encoding="utf-8",
        )
        (target_dir / "app.js").write_text(
            """document.getElementById("pingBtn").addEventListener("click", () => {
  document.getElementById("msg").textContent = "Дякую! Повідомлення отримано ✓";
});
""",
            encoding="utf-8",
        )
        return

    if template == "blog":
        (target_dir / "style.css").write_text(
            f""":root {{ --accent: {accent}; --bg: #0a0f1c; --card: #131c31; --border: #243456; --text: #f1f5f9; --muted: #94a3b8; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); }}
.wrap {{ max-width: 820px; margin: 0 auto; padding: 40px 20px; }}
input {{ width: 100%; background: var(--card); border: 1px solid var(--border); color: var(--text); padding: 12px 16px; border-radius: 12px; margin: 22px 0; font-size: 15px; }}
article {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 22px; margin-bottom: 14px; }}
""",
            encoding="utf-8",
        )
        (target_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="uk">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>{safe_title} — Блог</title><link rel="stylesheet" href="style.css"/></head>
<body>
  <div class="wrap">
    <h1>{safe_title}</h1>
    <p style="color:var(--muted);">Авторський блог на власному домені <strong>{safe_dom}</strong></p>
    <input id="q" type="text" placeholder="Пошук статей..." />
    <div id="posts"></div>
  </div>
  <script src="app.js"></script>
</body></html>
""",
            encoding="utf-8",
        )
        (target_dir / "app.js").write_text(
            """const POSTS = [
  { t: "Як ми запустили власну веб-ОС на Python", d: "Сьогодні", b: "Повноцінний робочий стіл, файли, GitHub і мульти-доменний хостинг прямо з ноутбука." },
  { t: "Чому власний сервер — це свобода розробника", d: "Вчора", b: "Повний контроль над кодом, доменами та даними без зайвих залежностей." },
  { t: "Швидкий старт проєктів у WSL / Ubuntu", d: "Огляд", b: "Одна команда з GitHub піднімає все середовище за лічені секунди." }
];
const box = document.getElementById("posts");
function draw(q) {
  box.innerHTML = "";
  POSTS.filter(p => (p.t + p.b).toLowerCase().includes(q.toLowerCase())).forEach(p => {
    const a = document.createElement("article");
    a.innerHTML = `<div style="font-size:12px;color:#38bdf8;margin-bottom:4px;">${p.d}</div><h3 style="margin-bottom:8px;">${p.t}</h3><p style="color:#94a3b8;line-height:1.55;">${p.b}</p>`;
    box.appendChild(a);
  });
}
document.getElementById("q").oninput = (e) => draw(e.target.value);
draw("");
""",
            encoding="utf-8",
        )
        return

    if template == "webapp":
        (target_dir / "style.css").write_text(
            f""":root {{ --accent: {accent}; --bg: #070b14; --card: #11192c; --border: #233354; --text: #e2e8f0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 28px; }}
.top {{ max-width: 980px; margin: 0 auto 22px; display: flex; justify-content: space-between; align-items: center; }}
.panel {{ max-width: 980px; margin: 0 auto; background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 22px; }}
canvas {{ width: 100%; height: 220px; background: #090f1d; border-radius: 12px; margin-top: 14px; }}
""",
            encoding="utf-8",
        )
        (target_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>{safe_title} — Web App</title><link rel="stylesheet" href="style.css"/></head>
<body>
  <div class="top"><h2>📊 {safe_title} <span style="color:var(--accent);font-size:14px;">({safe_dom})</span></h2><button id="regen" style="background:var(--accent);color:#04121f;border:none;padding:9px 16px;border-radius:9px;font-weight:700;cursor:pointer;">Оновити метрики</button></div>
  <div class="panel">
    <p style="color:#94a3b8;">Інтерактивний Canvas-графік у реальному часі:</p>
    <canvas id="chart" width="900" height="220"></canvas>
  </div>
  <script src="app.js"></script>
</body></html>
""",
            encoding="utf-8",
        )
        (target_dir / "app.js").write_text(
            """const cv = document.getElementById("chart");
const ctx = cv.getContext("2d");
function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 3;
  ctx.beginPath();
  for (let i = 0; i <= 12; i++) {
    const x = (cv.width / 12) * i;
    const y = 35 + Math.random() * 150;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}
document.getElementById("regen").onclick = draw;
draw();
""",
            encoding="utf-8",
        )
        return

    if template == "blank":
        (target_dir / "style.css").write_text(
            "body { font-family: system-ui, sans-serif; margin: 40px; background: #0b1120; color: #f8fafc; }\n",
            encoding="utf-8",
        )
        (target_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <title>{safe_title}</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <h1>{safe_title}</h1>
  <p>Домен: {safe_dom}</p>
  <script src="app.js"></script>
</body>
</html>
""",
            encoding="utf-8",
        )
        (target_dir / "app.js").write_text("console.log('Site ready');\n", encoding="utf-8")
        return

    # Default: `landing` — Modern SaaS / Product Landing Page
    (target_dir / "style.css").write_text(
        f""":root {{
  --accent: {accent};
  --bg: #070b14;
  --panel: #11192c;
  --border: rgba(96, 132, 190, 0.25);
  --text: #f1f5f9;
  --muted: #94a3b8;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  background:
    radial-gradient(circle at 20% 10%, rgba(56, 189, 248, 0.20), transparent 40%),
    radial-gradient(circle at 80% 30%, rgba(168, 85, 247, 0.18), transparent 45%),
    var(--bg);
  color: var(--text);
  min-height: 100vh;
}}
nav {{
  max-width: 1080px;
  margin: 0 auto;
  padding: 22px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.brand {{ font-weight: 800; font-size: 20px; display: flex; align-items: center; gap: 8px; }}
.pill {{
  display: inline-block;
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.14);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: var(--accent);
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 18px;
}}
.hero {{
  max-width: 840px;
  margin: 48px auto 56px;
  padding: 0 24px;
  text-align: center;
}}
h1 {{
  font-size: clamp(34px, 5vw, 56px);
  line-height: 1.08;
  letter-spacing: -0.03em;
  margin-bottom: 18px;
}}
.lead {{ color: var(--muted); font-size: 18px; line-height: 1.6; max-width: 620px; margin: 0 auto 28px; }}
.cta-row {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }}
.btn {{
  background: var(--accent);
  color: #04121f;
  border: none;
  padding: 13px 24px;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  text-decoration: none;
}}
.btn-sec {{
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--border);
}}
.features {{
  max-width: 1080px;
  margin: 0 auto 70px;
  padding: 0 24px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
  gap: 18px;
}}
.f-card {{
  background: rgba(17, 25, 44, 0.82);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
}}
.f-card h3 {{ margin: 10px 0 8px; font-size: 18px; }}
.f-card p {{ color: var(--muted); font-size: 14.5px; line-height: 1.55; }}
footer {{ text-align: center; padding: 28px; color: var(--muted); border-top: 1px solid var(--border); font-size: 13.5px; }}
""",
        encoding="utf-8",
    )
    (target_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <nav>
    <div class="brand">⚡ {safe_title}</div>
    <span style="color:var(--muted); font-size:13.5px;">Домен: <strong style="color:var(--text);">{safe_dom}</strong></span>
  </nav>

  <section class="hero">
    <div class="pill">● Запущено у WiGi Hosting</div>
    <h1>Новий рівень твоїх ідей разом із {safe_title}</h1>
    <p class="lead">Цей сайт працює напряму з твого Python-сервера під власним доменом <strong>{safe_dom}</strong>. Редагуй код у реальному часі через Code Studio!</p>
    <div class="cta-row">
      <button class="btn" id="demoBtn">Запустити інтерактив</button>
      <a class="btn btn-sec" href="#features">Переваги платформи</a>
    </div>
    <div id="statusBox" style="margin-top:16px; color:#86efac; font-weight:600; min-height:22px;"></div>
  </section>

  <section id="features" class="features">
    <div class="f-card">
      <div style="font-size:26px;">🌐</div>
      <h3>Будь-який власний домен</h3>
      <p>Миттєва маршрутизація за HTTP Host-заголовком, підтримка .localhost субдоменів, локальної мережі та вбудованого DNS у WiGi OS.</p>
    </div>
    <div class="f-card">
      <div style="font-size:26px;">⚡</div>
      <h3>Миттєве редагування коду</h3>
      <p>Відкривай index.html, style.css та app.js у Code Studio й одразу бач оновлення без жодного перезавантаження сервера.</p>
    </div>
    <div class="f-card">
      <div style="font-size:26px;">🛡</div>
      <h3>Повний контроль</h3>
      <p>Вмикай та вимикай публічний доступ до сайту в один клік і відстежуй статистику переглядів у реальному часі.</p>
    </div>
  </section>

  <footer>© 2026 {safe_title} ({safe_dom}) • Powered by WiGi Server</footer>
  <script src="app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )
    (target_dir / "app.js").write_text(
        """let count = 0;
document.getElementById("demoBtn").addEventListener("click", () => {
  count += 1;
  document.getElementById("statusBox").textContent =
    `Інтерактив працює! Відгук #${count} • ${new Date().toLocaleTimeString("uk-UA")}`;
});
""",
        encoding="utf-8",
    )
