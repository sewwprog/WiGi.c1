"""WiGi OS — HTML5 Web Desktop Operating System extension for WiGi servers.

Provides a full windowed desktop environment directly connected to the server's
real filesystem, Python runtime, shell, Git/GitHub repositories, task board,
process monitor, and live HTML app runner.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wigi.server import WiGiHTTPServer


def render_webos_html(srv: "WiGiHTTPServer") -> str:
    safe_name = html.escape(srv.profile.name)
    safe_host = html.escape(srv.hostname)
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_name} — WiGi OS</title>
  <style>
    :root {{
      --glass: rgba(14, 21, 36, 0.84);
      --glass-strong: rgba(11, 17, 30, 0.94);
      --panel: #11192b;
      --panel-2: #18233a;
      --panel-3: #0b101d;
      --border: rgba(96, 132, 190, 0.26);
      --border-active: rgba(56, 189, 248, 0.65);
      --text: #e8eef9;
      --muted: #8ea2c4;
      --accent: #38bdf8;
      --green: #22c55e;
      --amber: #f59e0b;
      --red: #ef4444;
      --purple: #a855f7;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 100%;
      height: 100%;
      overflow: hidden;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      color: var(--text);
      user-select: none;
      background: #070b14;
    }}
    input, textarea, select, pre, code, .selectable {{ user-select: text; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}

    /* Wallpaper Themes */
    #desktop {{
      position: fixed;
      inset: 0;
      bottom: 50px;
      overflow: hidden;
      transition: background 0.35s ease;
    }}
    body[data-theme="cyber"] #desktop {{
      background:
        radial-gradient(circle at 18% 20%, rgba(56, 189, 248, 0.22), transparent 42%),
        radial-gradient(circle at 82% 75%, rgba(168, 85, 247, 0.20), transparent 46%),
        linear-gradient(135deg, #060b16 0%, #0d172a 55%, #090e1c 100%);
    }}
    body[data-theme="cyber"] #desktop::before {{
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(56, 189, 248, 0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(56, 189, 248, 0.05) 1px, transparent 1px);
      background-size: 44px 44px;
      pointer-events: none;
    }}
    body[data-theme="nebula"] #desktop {{
      background:
        radial-gradient(circle at 25% 30%, rgba(236, 72, 153, 0.26), transparent 45%),
        radial-gradient(circle at 75% 25%, rgba(99, 102, 241, 0.28), transparent 48%),
        radial-gradient(circle at 60% 80%, rgba(14, 165, 233, 0.22), transparent 45%),
        linear-gradient(160deg, #090717 0%, #13112c 55%, #070b18 100%);
    }}
    body[data-theme="matrix"] #desktop {{
      background:
        radial-gradient(circle at 30% 25%, rgba(34, 197, 94, 0.22), transparent 45%),
        radial-gradient(circle at 80% 70%, rgba(16, 185, 129, 0.16), transparent 45%),
        linear-gradient(145deg, #040d09 0%, #091c14 55%, #040a08 100%);
    }}
    body[data-theme="sunset"] #desktop {{
      background:
        radial-gradient(circle at 20% 25%, rgba(249, 115, 22, 0.25), transparent 45%),
        radial-gradient(circle at 80% 35%, rgba(225, 29, 72, 0.24), transparent 48%),
        linear-gradient(155deg, #160912 0%, #1e1224 55%, #0b0d1a 100%);
    }}
    body[data-theme="slate"] #desktop {{
      background: linear-gradient(150deg, #0f172a 0%, #1e293b 100%);
    }}

    /* Lock Screen */
    #lockScreen {{
      position: fixed;
      inset: 0;
      z-index: 9000;
      backdrop-filter: blur(22px);
      background: rgba(6, 10, 20, 0.82);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    .lock-clock {{
      font-size: 58px;
      font-weight: 800;
      letter-spacing: -0.03em;
      text-shadow: 0 8px 30px rgba(0,0,0,0.5);
    }}
    .lock-date {{ color: var(--muted); font-size: 15px; margin-bottom: 28px; }}
    .lock-card {{
      width: 100%;
      max-width: 380px;
      background: var(--glass-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 24px;
      box-shadow: 0 24px 50px rgba(0,0,0,0.55);
      text-align: center;
    }}
    .avatar-ring {{
      width: 62px;
      height: 62px;
      border-radius: 50%;
      margin: 0 auto 12px;
      background: linear-gradient(135deg, var(--accent), var(--purple));
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 26px;
      font-weight: 800;
      color: #05101e;
    }}

    /* Desktop Icons Grid */
    .desktop-icons {{
      position: absolute;
      top: 16px;
      left: 16px;
      bottom: 16px;
      display: flex;
      flex-direction: column;
      flex-wrap: wrap;
      gap: 10px;
      align-content: flex-start;
      z-index: 5;
      pointer-events: none;
    }}
    .d-icon {{
      pointer-events: auto;
      width: 90px;
      padding: 10px 6px;
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 7px;
      cursor: pointer;
      border: 1px solid transparent;
      transition: background 0.14s, border-color 0.14s, transform 0.12s;
      text-align: center;
    }}
    .d-icon:hover {{
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.16);
      transform: translateY(-1px);
    }}
    .d-icon-box {{
      width: 44px;
      height: 44px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      box-shadow: 0 8px 18px rgba(0,0,0,0.35);
    }}
    .d-icon-label {{
      font-size: 11.8px;
      font-weight: 600;
      line-height: 1.22;
      text-shadow: 0 1px 4px rgba(0,0,0,0.9);
      color: #f1f5f9;
    }}

    /* Desktop Sticky Widget */
    .sticky-widget {{
      position: absolute;
      top: 18px;
      right: 18px;
      width: 270px;
      background: rgba(15, 23, 42, 0.72);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
      z-index: 6;
      box-shadow: 0 12px 30px rgba(0,0,0,0.35);
    }}
    .sticky-hdr {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 8px;
    }}
    #stickyArea {{
      width: 100%;
      background: rgba(8, 13, 24, 0.55);
      border: 1px solid rgba(96, 132, 190, 0.18);
      border-radius: 8px;
      color: var(--text);
      padding: 8px;
      font-size: 12.5px;
      line-height: 1.45;
      resize: vertical;
      min-height: 92px;
      outline: none;
    }}

    /* Windows */
    .os-win {{
      position: absolute;
      background: var(--glass-strong);
      backdrop-filter: blur(18px);
      border: 1px solid var(--border);
      border-radius: 13px;
      box-shadow: 0 22px 55px rgba(0, 0, 0, 0.6);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      min-width: 360px;
      min-height: 240px;
    }}
    .os-win.focused {{
      border-color: var(--border-active);
      box-shadow: 0 26px 65px rgba(0, 0, 0, 0.72), 0 0 0 1px rgba(56, 189, 248, 0.2);
    }}
    .os-win.maximized {{
      left: 0 !important;
      top: 0 !important;
      width: 100% !important;
      height: 100% !important;
      border-radius: 0;
    }}
    .win-bar {{
      height: 38px;
      background: rgba(22, 33, 56, 0.9);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 10px 0 13px;
      cursor: grab;
      flex-shrink: 0;
    }}
    .win-bar:active {{ cursor: grabbing; }}
    .win-title {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }}
    .win-ctrls {{ display: flex; align-items: center; gap: 5px; }}
    .w-btn {{
      width: 26px;
      height: 24px;
      border-radius: 6px;
      border: 1px solid transparent;
      background: rgba(255,255,255,0.05);
      color: var(--muted);
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .w-btn:hover {{ background: rgba(255,255,255,0.13); color: var(--text); }}
    .w-btn.close:hover {{ background: var(--red); color: #fff; }}
    .win-body {{
      flex: 1;
      overflow: auto;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .resize-grip {{
      position: absolute;
      right: 0;
      bottom: 0;
      width: 15px;
      height: 15px;
      cursor: nwse-resize;
      background: linear-gradient(135deg, transparent 50%, rgba(142, 162, 196, 0.45) 50%);
    }}

    /* Bottom Taskbar */
    #taskbar {{
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      height: 50px;
      background: rgba(9, 14, 26, 0.92);
      backdrop-filter: blur(20px);
      border-top: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 10px;
      gap: 10px;
      z-index: 7000;
    }}
    .tb-left, .tb-right {{ display: flex; align-items: center; gap: 7px; flex-shrink: 0; }}
    .tb-tasks {{
      flex: 1;
      display: flex;
      align-items: center;
      gap: 6px;
      overflow-x: auto;
      padding: 2px 0;
    }}
    .start-btn {{
      height: 36px;
      padding: 0 13px;
      border-radius: 10px;
      border: 1px solid rgba(56, 189, 248, 0.4);
      background: linear-gradient(135deg, rgba(56, 189, 248, 0.22), rgba(168, 85, 247, 0.22));
      color: #f8fafc;
      font-weight: 800;
      font-size: 13.5px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }}
    .start-btn:hover {{ border-color: var(--accent); }}
    .task-pill {{
      height: 34px;
      padding: 0 12px;
      border-radius: 9px;
      border: 1px solid var(--border);
      background: rgba(24, 35, 58, 0.72);
      color: var(--muted);
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      max-width: 190px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .task-pill.active {{
      background: rgba(56, 189, 248, 0.18);
      color: var(--text);
      border-color: rgba(56, 189, 248, 0.55);
    }}
    .tray-pill {{
      height: 34px;
      padding: 0 10px;
      border-radius: 9px;
      background: rgba(24, 35, 58, 0.65);
      border: 1px solid var(--border);
      font-size: 12px;
      color: var(--text);
      display: inline-flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
    }}

    /* Start Menu & Command Palette & Context Menu */
    #startMenu {{
      position: fixed;
      left: 10px;
      bottom: 58px;
      width: 420px;
      max-width: calc(100vw - 20px);
      background: var(--glass-strong);
      backdrop-filter: blur(22px);
      border: 1px solid var(--border-active);
      border-radius: 16px;
      padding: 16px;
      z-index: 8000;
      box-shadow: 0 24px 60px rgba(0,0,0,0.7);
    }}
    .sm-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 12px 0;
    }}
    .sm-item {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 11px;
      padding: 11px 8px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
      text-align: center;
    }}
    .sm-item:hover {{ border-color: var(--accent); background: rgba(56, 189, 248, 0.12); }}
    .sm-footer {{
      padding-top: 11px;
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }}

    #cmdPalette {{
      position: fixed;
      inset: 0;
      background: rgba(4, 8, 16, 0.6);
      backdrop-filter: blur(6px);
      z-index: 8500;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding-top: 10vh;
    }}
    .cmd-box {{
      width: 100%;
      max-width: 540px;
      background: var(--glass-strong);
      border: 1px solid var(--border-active);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 25px 60px rgba(0,0,0,0.75);
    }}
    .cmd-list {{ max-height: 300px; overflow-y: auto; margin-top: 10px; }}
    .cmd-row {{
      padding: 9px 11px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      font-size: 13px;
    }}
    .cmd-row:hover {{ background: rgba(56, 189, 248, 0.15); }}

    #ctxMenu {{
      position: fixed;
      width: 225px;
      background: var(--glass-strong);
      border: 1px solid var(--border-active);
      border-radius: 11px;
      padding: 6px;
      z-index: 8600;
      box-shadow: 0 18px 40px rgba(0,0,0,0.65);
    }}
    .ctx-item {{
      padding: 8px 11px;
      border-radius: 7px;
      font-size: 12.8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .ctx-item:hover {{ background: rgba(56, 189, 248, 0.16); }}

    /* Shared UI Inside Apps */
    input[type="text"], input[type="password"], input[type="number"], textarea, select {{
      background: var(--panel-3);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 8px;
      padding: 8px 11px;
      font-size: 13px;
      outline: none;
    }}
    input:focus, textarea:focus, select:focus {{ border-color: var(--accent); }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid transparent;
      border-radius: 8px;
      padding: 7px 13px;
      font-size: 12.5px;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: #041320;
      white-space: nowrap;
    }}
    .btn:hover {{ opacity: 0.92; }}
    .btn-ghost {{ background: var(--panel-2); color: var(--text); border-color: var(--border); }}
    .btn-ghost:hover {{ border-color: var(--accent); }}
    .btn-green {{ background: var(--green); color: #04210f; }}
    .btn-danger {{ background: rgba(239,68,68,0.16); color: #fca5a5; border-color: rgba(239,68,68,0.38); }}
    .toolbar {{
      padding: 8px 10px;
      background: rgba(17, 25, 43, 0.85);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 7px;
      flex-wrap: wrap;
    }}
    .muted {{ color: var(--muted); }}
    .hidden {{ display: none !important; }}

    /* Code Studio */
    .ide-layout {{ display: flex; flex: 1; min-height: 0; }}
    .ide-side {{
      width: 220px;
      border-right: 1px solid var(--border);
      background: rgba(11, 16, 29, 0.75);
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .ide-tree {{ flex: 1; overflow-y: auto; padding: 6px; }}
    .ide-entry {{
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 12.5px;
      cursor: pointer;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .ide-entry:hover {{ background: rgba(56, 189, 248, 0.12); }}
    .ide-main {{ flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }}
    .ide-tabs {{
      display: flex;
      background: #0a0f1c;
      border-bottom: 1px solid var(--border);
      overflow-x: auto;
      min-height: 33px;
    }}
    .ide-tab {{
      padding: 6px 11px;
      font-size: 12px;
      border-right: 1px solid var(--border);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      white-space: nowrap;
    }}
    .ide-tab.active {{ background: var(--panel); color: var(--accent); font-weight: 700; }}
    .ide-editor-wrap {{ flex: 1; display: flex; min-height: 0; position: relative; background: #070b14; }}
    .ide-gutter {{
      width: 44px;
      padding: 10px 6px;
      text-align: right;
      color: #4b5e80;
      background: #090e1a;
      border-right: 1px solid rgba(96,132,190,0.15);
      font-size: 12.5px;
      line-height: 1.5;
      overflow: hidden;
      white-space: pre;
    }}
    .ide-textarea {{
      flex: 1;
      background: transparent;
      border: none;
      color: #e2e8f0;
      padding: 10px 12px;
      font-size: 12.8px;
      line-height: 1.5;
      resize: none;
      outline: none;
      white-space: pre;
      overflow: auto;
    }}
    .ide-console {{
      height: 135px;
      border-top: 1px solid var(--border);
      background: #050811;
      padding: 8px 11px;
      font-size: 12px;
      color: #a7f3d0;
      overflow-y: auto;
      white-space: pre-wrap;
    }}

    /* Kanban */
    .kb-board {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      padding: 12px;
      flex: 1;
      overflow: auto;
    }}
    .kb-col {{
      background: rgba(11, 16, 29, 0.72);
      border: 1px solid var(--border);
      border-radius: 11px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-height: 220px;
    }}
    .kb-card {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 9px 10px;
      font-size: 12.8px;
    }}
    .kb-card.high {{ border-left: 3px solid var(--amber); }}

    .toast {{
      position: fixed;
      top: 16px;
      left: 50%;
      transform: translateX(-50%);
      background: #132038;
      border: 1px solid var(--accent);
      color: var(--text);
      padding: 8px 16px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      z-index: 9500;
      box-shadow: 0 12px 30px rgba(0,0,0,0.5);
    }}
  </style>
</head>
<body data-theme="cyber">

  <!-- LOCK SCREEN -->
  <div id="lockScreen" class="hidden">
    <div class="lock-clock" id="lockClock">00:00</div>
    <div class="lock-date" id="lockDate">—</div>
    <div class="lock-card">
      <div class="avatar-ring">W</div>
      <h2 style="font-size:19px; margin-bottom:4px;">{safe_name}</h2>
      <div class="muted" style="font-size:12.5px; margin-bottom:16px;">WiGi OS &bull; {safe_host}</div>
      <form id="unlockForm">
        <input id="unlockPw" type="password" placeholder="Введи пароль сервера..." style="width:100%; margin-bottom:10px;" required />
        <button class="btn" type="submit" style="width:100%; padding:10px;">Розблокувати WiGi OS</button>
        <div id="unlockErr" style="color:#fca5a5; font-size:12.5px; margin-top:8px; min-height:16px;"></div>
      </form>
    </div>
  </div>

  <!-- DESKTOP -->
  <div id="desktop">
    <div class="desktop-icons" id="desktopIcons"></div>

    <!-- Quick Sticky Note Widget -->
    <div class="sticky-widget" id="stickyWidget">
      <div class="sticky-hdr">
        <span>📌 Швидка нотатка сервера</span>
        <span id="stickySaved" class="muted" style="font-weight:400; font-size:11px;">автозбереження</span>
      </div>
      <textarea id="stickyArea" placeholder="Запиши ідею, команду або план..."></textarea>
    </div>

    <!-- Windows Layer -->
    <div id="windowsLayer"></div>
  </div>

  <!-- START MENU -->
  <div id="startMenu" class="hidden">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <div>
        <div style="font-weight:800; font-size:15px;">❖ WiGi OS Workstation</div>
        <div class="muted" style="font-size:12px;">Сервер: <span id="smServerName">{safe_name}</span></div>
      </div>
      <button id="smPaletteBtn" class="btn btn-ghost" type="button">🔍 Ctrl+K</button>
    </div>
    <div class="sm-grid" id="smAppsGrid"></div>
    <div class="sm-footer">
      <a id="classicPanelLink" class="btn btn-ghost" style="text-decoration:none;" href="./">↩ Панель сервера</a>
      <div style="display:flex; gap:6px;">
        <button id="lockOsBtn" class="btn btn-ghost" type="button">🔒 Блок</button>
        <button id="logoutOsBtn" class="btn btn-danger" type="button">Вийти</button>
      </div>
    </div>
  </div>

  <!-- COMMAND PALETTE (Ctrl+K) -->
  <div id="cmdPalette" class="hidden">
    <div class="cmd-box">
      <input id="cmdSearchInput" type="text" style="width:100%; font-size:14px; padding:10px 12px;" placeholder="Пошук додатків, файлів на сервері або швидких дій..." autocomplete="off" />
      <div class="cmd-list" id="cmdResults"></div>
    </div>
  </div>

  <!-- RIGHT-CLICK CONTEXT MENU -->
  <div id="ctxMenu" class="hidden">
    <div class="ctx-item" data-act="open-code">💻 Відкрити Code Studio</div>
    <div class="ctx-item" data-act="open-term">🖥 Відкрити Термінал</div>
    <div class="ctx-item" data-act="tpl-py">🐍 Створити Python-проєкт</div>
    <div class="ctx-item" data-act="tpl-html">🌐 Створити HTML веб-додаток</div>
    <div class="ctx-item" data-act="open-git">🐙 Керувати GitHub репами</div>
    <div class="ctx-item" data-act="cycle-theme">🎨 Змінити тему шпалер</div>
  </div>

  <!-- TASKBAR -->
  <div id="taskbar">
    <div class="tb-left">
      <button id="startBtn" class="start-btn" type="button">❖ WiGi</button>
      <button id="searchBarBtn" class="tray-pill" type="button" title="Швидкий пошук (Ctrl+K)">🔍 Пошук</button>
    </div>
    <div class="tb-tasks" id="taskList"></div>
    <div class="tb-right">
      <div id="sysTrayMonitor" class="tray-pill" title="Відкрити Монітор ОС">
        <span style="color:var(--green);">●</span>
        <span id="trayStats" class="mono">RAM —</span>
      </div>
      <div class="tray-pill" id="trayClockWrap">
        <span id="trayClock" class="mono" style="font-weight:700;">00:00:00</span>
      </div>
    </div>
  </div>

  <div id="toast" class="toast hidden"></div>

  <script>
    // Compute root API prefix cleanly whether opened at /os or /os/
    const ROOT = (() => {{
      let p = location.pathname;
      if (p.endsWith("/os/")) return p.slice(0, -4);
      if (p.endsWith("/os")) return p.slice(0, -3);
      return "";
    }})();
    document.getElementById("classicPanelLink").href = (ROOT || "") + "/";

    const TOKEN_KEY = "wigi_auth_token";
    function getToken() {{
      try {{ return sessionStorage.getItem(TOKEN_KEY) || ""; }} catch (_) {{ return window.__wigiToken || ""; }}
    }}
    function setToken(t) {{
      window.__wigiToken = t;
      try {{
        if (t) sessionStorage.setItem(TOKEN_KEY, t);
        else sessionStorage.removeItem(TOKEN_KEY);
      }} catch (_) {{}}
    }}
    function authHeaders(extra) {{
      const h = Object.assign({{ "Content-Type": "application/json" }}, extra || {{}});
      const t = getToken();
      if (t) h["Authorization"] = "Bearer " + t;
      return h;
    }}
    async function api(path, opts) {{
      const options = opts || {{}};
      options.headers = authHeaders(options.headers);
      const url = ROOT + "/" + path.replace(/^\\/+/, "");
      const res = await fetch(url, options);
      if (res.status === 401 && !path.endsWith("api/login")) {{
        showLockScreen();
        throw new Error("Unauthorized");
      }}
      const data = await res.json();
      return {{ res, data }};
    }}
    function toast(msg, isErr) {{
      const el = document.getElementById("toast");
      el.textContent = msg;
      el.style.borderColor = isErr ? "var(--red)" : "var(--accent)";
      el.classList.remove("hidden");
      clearTimeout(window.__osToast);
      window.__osToast = setTimeout(() => el.classList.add("hidden"), 2800);
    }}
    function esc(s) {{
      const d = document.createElement("div");
      d.textContent = s == null ? "" : String(s);
      return d.innerHTML;
    }}

    // Clock
    function tickClock() {{
      const now = new Date();
      const tFull = now.toLocaleTimeString("uk-UA", {{ hour12: false }});
      const tShort = now.toLocaleTimeString("uk-UA", {{ hour: "2-digit", minute: "2-digit", hour12: false }});
      const dStr = now.toLocaleDateString("uk-UA", {{ weekday: "long", day: "numeric", month: "long" }});
      document.getElementById("trayClock").textContent = tFull;
      document.getElementById("lockClock").textContent = tShort;
      document.getElementById("lockDate").textContent = dStr;
    }}
    setInterval(tickClock, 1000);
    tickClock();

    // App Registry
    const APPS = [
      {{ id: "code", title: "Code Studio", icon: "💻", bg: "linear-gradient(135deg,#0284c7,#38bdf8)", w: 860, h: 540 }},
      {{ id: "terminal", title: "Термінал", icon: "🖥", bg: "linear-gradient(135deg,#0f172a,#334155)", w: 680, h: 440, multi: true }},
      {{ id: "files", title: "Провідник", icon: "📁", bg: "linear-gradient(135deg,#d97706,#fbbf24)", w: 720, h: 470 }},
      {{ id: "git", title: "GitHub Studio", icon: "🐙", bg: "linear-gradient(135deg,#7c3aed,#a855f7)", w: 780, h: 510 }},
      {{ id: "kanban", title: "Задачі Kanban", icon: "📋", bg: "linear-gradient(135deg,#059669,#34d399)", w: 820, h: 490 }},
      {{ id: "notes", title: "Нотатки MD", icon: "📝", bg: "linear-gradient(135deg,#2563eb,#60a5fa)", w: 740, h: 470 }},
      {{ id: "browser", title: "Веб-Ранер HTML", icon: "🌐", bg: "linear-gradient(135deg,#0891b2,#22d3ee)", w: 780, h: 520 }},
      {{ id: "monitor", title: "Монітор ОС", icon: "📊", bg: "linear-gradient(135deg,#dc2626,#f87171)", w: 720, h: 480 }},
      {{ id: "settings", title: "Налаштування", icon: "⚙️", bg: "linear-gradient(135deg,#475569,#94a3b8)", w: 660, h: 480 }},
    ];

    // Render Desktop Icons & Start Menu Grid
    const dIconsEl = document.getElementById("desktopIcons");
    const smGridEl = document.getElementById("smAppsGrid");
    APPS.forEach(app => {{
      const d = document.createElement("div");
      d.className = "d-icon";
      d.innerHTML = `<div class="d-icon-box" style="background:${{app.bg}}">${{app.icon}}</div><div class="d-icon-label">${{esc(app.title)}}</div>`;
      d.addEventListener("click", () => openApp(app.id));
      dIconsEl.appendChild(d);

      const s = document.createElement("div");
      s.className = "sm-item";
      s.innerHTML = `<div style="font-size:22px;">${{app.icon}}</div><div>${{esc(app.title)}}</div>`;
      s.addEventListener("click", () => {{
        hidePopups();
        openApp(app.id);
      }});
      smGridEl.appendChild(s);
    }});

    // OS State (Theme, Sticky Note, Kanban Tasks)
    let osState = {{ theme: "cyber", sticky_note: "", tasks: [] }};
    async function loadOsState() {{
      const {{ data }} = await api("api/os/state");
      if (data.ok && data.state) {{
        osState = data.state;
        document.body.dataset.theme = osState.theme || "cyber";
        document.getElementById("stickyArea").value = osState.sticky_note || "";
      }}
    }}
    async function saveOsStatePatch(patch) {{
      Object.assign(osState, patch);
      const {{ data }} = await api("api/os/state", {{
        method: "POST",
        body: JSON.stringify(patch)
      }});
      if (data.ok && data.state) osState = data.state;
    }}

    let stickyTimer = null;
    document.getElementById("stickyArea").addEventListener("input", (e) => {{
      document.getElementById("stickySaved").textContent = "зберігаю...";
      clearTimeout(stickyTimer);
      stickyTimer = setTimeout(async () => {{
        await saveOsStatePatch({{ sticky_note: e.target.value }});
        document.getElementById("stickySaved").textContent = "збережено ✓";
      }}, 650);
    }});

    // Window Manager
    const windows = new Map();
    let zCounter = 20;
    let winSeq = 1;

    function focusWin(winId) {{
      const w = windows.get(winId);
      if (!w) return;
      w.minimized = false;
      w.el.classList.remove("hidden");
      zCounter += 1;
      w.el.style.zIndex = zCounter;
      windows.forEach((other, id) => other.el.classList.toggle("focused", id === winId));
      renderTaskbar();
    }}

    function closeWin(winId) {{
      const w = windows.get(winId);
      if (!w) return;
      if (w.cleanup) w.cleanup();
      w.el.remove();
      windows.delete(winId);
      renderTaskbar();
    }}

    function renderTaskbar() {{
      const bar = document.getElementById("taskList");
      bar.innerHTML = "";
      windows.forEach((w, id) => {{
        const pill = document.createElement("button");
        pill.type = "button";
        const isTop = w.el.classList.contains("focused") && !w.minimized;
        pill.className = "task-pill" + (isTop ? " active" : "");
        pill.innerHTML = `<span>${{w.app.icon}}</span><span>${{esc(w.title)}}</span>`;
        pill.addEventListener("click", () => {{
          if (isTop) {{
            w.minimized = true;
            w.el.classList.add("hidden");
            w.el.classList.remove("focused");
            renderTaskbar();
          }} else {{
            focusWin(id);
          }}
        }});
        bar.appendChild(pill);
      }});
    }}

    function openApp(appId, params) {{
      const app = APPS.find(a => a.id === appId);
      if (!app) return;

      if (!app.multi) {{
        for (const [id, w] of windows.entries()) {{
          if (w.app.id === appId) {{
            focusWin(id);
            if (w.onParams && params) w.onParams(params);
            return;
          }}
        }}
      }}

      const winId = "win_" + (winSeq++);
      const desk = document.getElementById("desktop");
      const maxW = desk.clientWidth;
      const maxH = desk.clientHeight;
      const wWidth = Math.min(app.w, maxW - 24);
      const wHeight = Math.min(app.h, maxH - 24);
      const offset = ((windows.size % 6) * 26);
      const left = Math.max(12, Math.min(maxW - wWidth - 12, 118 + offset));
      const top = Math.max(10, Math.min(maxH - wHeight - 10, 26 + offset));

      const el = document.createElement("div");
      el.className = "os-win";
      el.style.width = wWidth + "px";
      el.style.height = wHeight + "px";
      el.style.left = left + "px";
      el.style.top = top + "px";
      el.innerHTML = `
        <div class="win-bar">
          <div class="win-title"><span>${{app.icon}}</span><span class="win-title-txt">${{esc(app.title)}}</span></div>
          <div class="win-ctrls">
            <button class="w-btn snap-l" title="Прикріпити ліворуч (50%)" type="button">◧</button>
            <button class="w-btn snap-r" title="Прикріпити праворуч (50%)" type="button">◨</button>
            <button class="w-btn min" title="Згорнути" type="button">—</button>
            <button class="w-btn max" title="Розгорнути" type="button">□</button>
            <button class="w-btn close" title="Закрити" type="button">✕</button>
          </div>
        </div>
        <div class="win-body"></div>
        <div class="resize-grip"></div>
      `;

      el.addEventListener("pointerdown", () => focusWin(winId));

      const bar = el.querySelector(".win-bar");
      bar.addEventListener("dblclick", (e) => {{
        if (e.target.closest(".win-ctrls")) return;
        el.classList.toggle("maximized");
      }});

      // Dragging
      bar.addEventListener("pointerdown", (e) => {{
        if (e.target.closest(".win-ctrls") || el.classList.contains("maximized")) return;
        const startX = e.clientX;
        const startY = e.clientY;
        const origL = el.offsetLeft;
        const origT = el.offsetTop;
        bar.setPointerCapture(e.pointerId);
        const onMove = (ev) => {{
          const nx = Math.max(-wWidth + 120, Math.min(desk.clientWidth - 80, origL + (ev.clientX - startX)));
          const ny = Math.max(0, Math.min(desk.clientHeight - 38, origT + (ev.clientY - startY)));
          el.style.left = nx + "px";
          el.style.top = ny + "px";
        }};
        const onUp = () => {{
          bar.removeEventListener("pointermove", onMove);
          bar.removeEventListener("pointerup", onUp);
        }};
        bar.addEventListener("pointermove", onMove);
        bar.addEventListener("pointerup", onUp);
      }});

      // Resizing
      const grip = el.querySelector(".resize-grip");
      grip.addEventListener("pointerdown", (e) => {{
        e.stopPropagation();
        if (el.classList.contains("maximized")) return;
        const startX = e.clientX;
        const startY = e.clientY;
        const origW = el.offsetWidth;
        const origH = el.offsetHeight;
        grip.setPointerCapture(e.pointerId);
        const onMove = (ev) => {{
          el.style.width = Math.max(360, origW + (ev.clientX - startX)) + "px";
          el.style.height = Math.max(240, origH + (ev.clientY - startY)) + "px";
        }};
        const onUp = () => {{
          grip.removeEventListener("pointermove", onMove);
          grip.removeEventListener("pointerup", onUp);
        }};
        grip.addEventListener("pointermove", onMove);
        grip.addEventListener("pointerup", onUp);
      }});

      // Controls
      el.querySelector(".snap-l").addEventListener("click", () => {{
        el.classList.remove("maximized");
        el.style.left = "6px";
        el.style.top = "6px";
        el.style.width = (Math.floor(desk.clientWidth / 2) - 9) + "px";
        el.style.height = (desk.clientHeight - 12) + "px";
      }});
      el.querySelector(".snap-r").addEventListener("click", () => {{
        el.classList.remove("maximized");
        const half = Math.floor(desk.clientWidth / 2);
        el.style.left = (half + 3) + "px";
        el.style.top = "6px";
        el.style.width = (desk.clientWidth - half - 9) + "px";
        el.style.height = (desk.clientHeight - 12) + "px";
      }});
      el.querySelector(".min").addEventListener("click", (e) => {{
        e.stopPropagation();
        const rec = windows.get(winId);
        if (rec) rec.minimized = true;
        el.classList.add("hidden");
        el.classList.remove("focused");
        renderTaskbar();
      }});
      el.querySelector(".max").addEventListener("click", () => el.classList.toggle("maximized"));
      el.querySelector(".close").addEventListener("click", () => closeWin(winId));

      document.getElementById("windowsLayer").appendChild(el);
      const winRec = {{ id: winId, app, title: app.title, el, minimized: false, onParams: null, cleanup: null }};
      windows.set(winId, winRec);
      mountAppBody(winRec, el.querySelector(".win-body"), params || {{}});
      focusWin(winId);
    }}

    // =========================================================================
    // APP IMPLEMENTATIONS
    // =========================================================================

    function mountAppBody(winRec, body, params) {{
      const id = winRec.app.id;
      if (id === "code") return mountCodeStudio(winRec, body, params);
      if (id === "terminal") return mountTerminal(winRec, body, params);
      if (id === "files") return mountFileExplorer(winRec, body, params);
      if (id === "git") return mountGitStudio(winRec, body, params);
      if (id === "kanban") return mountKanban(winRec, body);
      if (id === "notes") return mountNotesApp(winRec, body, params);
      if (id === "browser") return mountBrowserRunner(winRec, body, params);
      if (id === "monitor") return mountSystemMonitor(winRec, body);
      if (id === "settings") return mountSettingsApp(winRec, body);
    }}

    // 1. CODE STUDIO (IDE)
    function mountCodeStudio(winRec, body, params) {{
      body.innerHTML = `
        <div class="toolbar">
          <button class="btn btn-ghost ide-up" type="button">↑</button>
          <button class="btn btn-ghost ide-newf" type="button">+ Файл</button>
          <button class="btn btn-ghost ide-newd" type="button">+ Папка</button>
          <button class="btn btn-ghost ide-ref" type="button">↻</button>
          <span class="muted mono ide-cwd" style="font-size:12px;">/</span>
          <div style="margin-left:auto; display:flex; gap:6px;">
            <button class="btn btn-green ide-run-py hidden" type="button">▶ Запустити Python</button>
            <button class="btn btn-green ide-run-html hidden" type="button">🌐 Відкрити в Браузері</button>
            <button class="btn ide-save" type="button" disabled>💾 Зберегти (Ctrl+S)</button>
          </div>
        </div>
        <div class="ide-layout">
          <div class="ide-side">
            <div class="ide-tree"></div>
          </div>
          <div class="ide-main">
            <div class="ide-tabs"></div>
            <div class="ide-editor-wrap">
              <div class="ide-gutter mono">1</div>
              <textarea class="ide-textarea mono" spellcheck="false" placeholder="Вибери файл у дереві зліва або створи новий..." disabled></textarea>
            </div>
            <div class="ide-console mono">Готово. Відкрий .py файл для запуску на сервері або .html для живого прев'ю.</div>
          </div>
        </div>
      `;

      let treeDir = params.dir || "";
      let treeParent = "";
      const openTabs = new Map(); // path -> tab record
      let activePath = "";

      const treeEl = body.querySelector(".ide-tree");
      const tabsEl = body.querySelector(".ide-tabs");
      const gutterEl = body.querySelector(".ide-gutter");
      const areaEl = body.querySelector(".ide-textarea");
      const outEl = body.querySelector(".ide-console");
      const saveBtn = body.querySelector(".ide-save");
      const runPyBtn = body.querySelector(".ide-run-py");
      const runHtmlBtn = body.querySelector(".ide-run-html");

      function syncGutter() {{
        const lines = (areaEl.value || "").split("\\n").length;
        const nums = [];
        for (let i = 1; i <= lines; i++) nums.push(i);
        gutterEl.textContent = nums.join("\\n");
        gutterEl.scrollTop = areaEl.scrollTop;
      }}
      areaEl.addEventListener("scroll", () => {{ gutterEl.scrollTop = areaEl.scrollTop; }});
      areaEl.addEventListener("input", () => {{
        syncGutter();
        const t = openTabs.get(activePath);
        if (t) {{
          t.content = areaEl.value;
          t.dirty = true;
          renderTabs();
        }}
      }});
      areaEl.addEventListener("keydown", (e) => {{
        if (e.key === "Tab") {{
          e.preventDefault();
          const s = areaEl.selectionStart;
          const end = areaEl.selectionEnd;
          areaEl.value = areaEl.value.slice(0, s) + "    " + areaEl.value.slice(end);
          areaEl.selectionStart = areaEl.selectionEnd = s + 4;
          areaEl.dispatchEvent(new Event("input"));
        }} else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {{
          e.preventDefault();
          saveActive();
        }}
      }});

      function renderTabs() {{
        tabsEl.innerHTML = "";
        openTabs.forEach((tab, p) => {{
          const el = document.createElement("div");
          el.className = "ide-tab" + (p === activePath ? " active" : "");
          el.innerHTML = `<span>${{esc(tab.name)}}${{tab.dirty ? " ●" : ""}}</span><span class="close-t" style="opacity:0.7;">×</span>`;
          el.addEventListener("click", (e) => {{
            if (e.target.classList.contains("close-t")) {{
              openTabs.delete(p);
              if (activePath === p) {{
                const keys = Array.from(openTabs.keys());
                activateTab(keys.length ? keys[keys.length - 1] : "");
              }} else {{
                renderTabs();
              }}
              return;
            }}
            activateTab(p);
          }});
          tabsEl.appendChild(el);
        }});
      }}

      function activateTab(p) {{
        activePath = p;
        const tab = openTabs.get(p);
        if (!tab) {{
          areaEl.value = "";
          areaEl.disabled = true;
          saveBtn.disabled = true;
          runPyBtn.classList.add("hidden");
          runHtmlBtn.classList.add("hidden");
          syncGutter();
          renderTabs();
          return;
        }}
        areaEl.disabled = false;
        areaEl.value = tab.content;
        saveBtn.disabled = false;
        runPyBtn.classList.toggle("hidden", !p.endsWith(".py"));
        runHtmlBtn.classList.toggle("hidden", !(p.endsWith(".html") || p.endsWith(".htm")));
        syncGutter();
        renderTabs();
      }}

      async function openFile(relPath) {{
        if (openTabs.has(relPath)) {{
          activateTab(relPath);
          return;
        }}
        const {{ data }} = await api("api/files/read?path=" + encodeURIComponent(relPath));
        if (!data.ok) return toast(data.error, true);
        openTabs.set(data.path, {{ path: data.path, name: data.name, content: data.content, dirty: false }});
        activateTab(data.path);
      }}

      async function saveActive() {{
        const tab = openTabs.get(activePath);
        if (!tab) return;
        const {{ data }} = await api("api/files/write", {{
          method: "POST",
          body: JSON.stringify({{ path: tab.path, content: tab.content }})
        }});
        if (!data.ok) return toast(data.error, true);
        tab.dirty = false;
        renderTabs();
        toast(`Збережено ${{tab.name}}`);
        loadTree(treeDir);
      }}

      async function loadTree(dir) {{
        const {{ data }} = await api("api/files?path=" + encodeURIComponent(dir || ""));
        if (!data.ok) return;
        treeDir = data.cwd || "";
        treeParent = data.parent || "";
        body.querySelector(".ide-cwd").textContent = "/" + treeDir;
        treeEl.innerHTML = "";
        data.items.forEach(it => {{
          const row = document.createElement("div");
          row.className = "ide-entry mono";
          const ic = it.type === "dir" ? (it.is_git ? "📦 " : "📁 ") : (it.name.endsWith(".py") ? "🐍 " : (it.name.endsWith(".html") ? "🌐 " : "📄 "));
          row.textContent = ic + it.name;
          row.addEventListener("click", () => {{
            if (it.type === "dir") loadTree(it.path);
            else openFile(it.path);
          }});
          treeEl.appendChild(row);
        }});
      }}

      saveBtn.addEventListener("click", saveActive);
      runPyBtn.addEventListener("click", async () => {{
        if (!activePath) return;
        await saveActive();
        outEl.textContent = `>>> Запуск ${{activePath}}...\\n`;
        const {{ data }} = await api("api/python/run", {{
          method: "POST",
          body: JSON.stringify({{ file: activePath }})
        }});
        if (!data.ok) {{ outEl.textContent += "Помилка: " + data.error; return; }}
        outEl.textContent = (data.stdout || "") + (data.stderr ? "\\n" + data.stderr : "") + `\\n[exit=${{data.exit_code}} • ${{data.duration_ms}} мс]`;
      }});
      runHtmlBtn.addEventListener("click", async () => {{
        if (!activePath) return;
        await saveActive();
        openApp("browser", {{ file: activePath }});
      }});

      body.querySelector(".ide-up").addEventListener("click", () => loadTree(treeParent));
      body.querySelector(".ide-ref").addEventListener("click", () => loadTree(treeDir));
      body.querySelector(".ide-newf").addEventListener("click", async () => {{
        const n = prompt("Назва нового файлу (напр. app.py або page.html):");
        if (!n) return;
        const p = treeDir ? `${{treeDir}}/${{n}}` : n;
        const starter = n.endsWith(".py") ? "#!/usr/bin/env python3\\n\\nprint('Hello from WiGi OS!')\\n" : "";
        const {{ data }} = await api("api/files/write", {{ method: "POST", body: JSON.stringify({{ path: p, content: starter }}) }});
        if (!data.ok) return toast(data.error, true);
        await loadTree(treeDir);
        openFile(data.path);
      }});
      body.querySelector(".ide-newd").addEventListener("click", async () => {{
        const n = prompt("Назва нової папки:");
        if (!n) return;
        const p = treeDir ? `${{treeDir}}/${{n}}` : n;
        const {{ data }} = await api("api/files/mkdir", {{ method: "POST", body: JSON.stringify({{ path: p }}) }});
        if (!data.ok) return toast(data.error, true);
        loadTree(treeDir);
      }});

      winRec.onParams = (p) => {{
        if (p.dir !== undefined) loadTree(p.dir);
        if (p.file) openFile(p.file);
      }};

      loadTree(treeDir).then(() => {{
        if (params.file) openFile(params.file);
        else openFile("hello.py").catch(() => {{}});
      }});
    }}

    // 2. TERMINAL
    function mountTerminal(winRec, body, params) {{
      let cwd = params.cwd || "";
      const history = [];
      let hIdx = -1;

      body.style.background = "#050811";
      body.innerHTML = `
        <div class="toolbar">
          <button class="btn btn-ghost t-chip" data-c="ls -la" type="button">ls -la</button>
          <button class="btn btn-ghost t-chip" data-c="python3 hello.py" type="button">python3 hello.py</button>
          <button class="btn btn-ghost t-chip" data-c="git status" type="button">git status</button>
          <button class="btn btn-ghost t-chip" data-c="python3 --version" type="button">python3 -V</button>
          <button class="btn btn-ghost t-clr" style="margin-left:auto;" type="button">Очистити</button>
        </div>
        <div class="t-out mono selectable" style="flex:1; padding:12px; font-size:12.8px; line-height:1.5; color:#d1fae5; overflow-y:auto; white-space:pre-wrap;">WiGi OS Terminal — підключено до робочої папки сервера.
Підтримується перехід між папками через 'cd', запуск Python та Git.\n</div>
        <form class="t-form" style="display:flex; align-items:center; gap:8px; padding:8px 10px; border-top:1px solid var(--border); background:#090f1d;">
          <span class="t-prompt mono" style="color:var(--accent); font-size:12.5px; font-weight:700;">~/ $</span>
          <input class="t-in mono" type="text" style="flex:1; border:none; background:transparent; padding:4px;" placeholder="Введи команду..." autocomplete="off" />
          <button class="btn" type="submit">Виконати</button>
        </form>
      `;

      const out = body.querySelector(".t-out");
      const inp = body.querySelector(".t-in");
      const promptEl = body.querySelector(".t-prompt");

      function updatePrompt() {{
        promptEl.textContent = `~/${{cwd}} $`;
      }}
      updatePrompt();

      async function runCmd(cmd) {{
        if (cmd === "clear" || cmd === "cls") {{
          out.textContent = "";
          return;
        }}
        out.textContent += `\\n~/${{cwd}} $ ${{cmd}}\\n`;
        out.scrollTop = out.scrollHeight;
        const {{ data }} = await api("api/exec", {{
          method: "POST",
          body: JSON.stringify({{ command: cmd, cwd }})
        }});
        if (!data.ok) {{
          out.textContent += `Помилка: ${{data.error}}\\n`;
          return;
        }}
        cwd = data.cwd || "";
        updatePrompt();
        if (data.stdout) out.textContent += data.stdout + (data.stdout.endsWith("\\n") ? "" : "\\n");
        if (data.stderr) out.textContent += data.stderr + (data.stderr.endsWith("\\n") ? "" : "\\n");
        out.scrollTop = out.scrollHeight;
      }}

      body.querySelector(".t-form").addEventListener("submit", (e) => {{
        e.preventDefault();
        const c = inp.value.trim();
        if (!c) return;
        history.unshift(c);
        hIdx = -1;
        inp.value = "";
        runCmd(c);
      }});
      inp.addEventListener("keydown", (e) => {{
        if (e.key === "ArrowUp" && history.length) {{
          e.preventDefault();
          hIdx = Math.min(history.length - 1, hIdx + 1);
          inp.value = history[hIdx];
        }} else if (e.key === "ArrowDown") {{
          e.preventDefault();
          hIdx = Math.max(-1, hIdx - 1);
          inp.value = hIdx >= 0 ? history[hIdx] : "";
        }}
      }});
      body.querySelectorAll(".t-chip").forEach(b => b.addEventListener("click", () => runCmd(b.dataset.c)));
      body.querySelector(".t-clr").addEventListener("click", () => {{ out.textContent = ""; }});
      setTimeout(() => inp.focus(), 60);
    }}

    // 3. FILE EXPLORER
    function mountFileExplorer(winRec, body, params) {{
      let cur = params.dir || "";
      let parent = "";
      body.innerHTML = `
        <div class="toolbar">
          <button class="btn btn-ghost fe-up" type="button">↑ Вгору</button>
          <button class="btn btn-ghost fe-nf" type="button">+ Файл</button>
          <button class="btn btn-ghost fe-nd" type="button">+ Папка</button>
          <label class="btn btn-ghost" style="cursor:pointer;">⬆ Завантажити<input class="fe-up-in" type="file" style="display:none;" /></label>
          <button class="btn btn-ghost fe-tpl-py" type="button">🐍 +Python проєкт</button>
          <button class="btn btn-ghost fe-tpl-html" type="button">🌐 +HTML додаток</button>
          <span class="muted mono fe-path" style="font-size:12px; margin-left:auto;">/</span>
        </div>
        <div class="fe-grid" style="padding:14px; display:grid; grid-template-columns:repeat(auto-fill,minmax(175px,1fr)); gap:10px; overflow-y:auto; flex:1; align-content:start;"></div>
      `;
      const grid = body.querySelector(".fe-grid");

      async function load(dir) {{
        const {{ data }} = await api("api/files?path=" + encodeURIComponent(dir || ""));
        if (!data.ok) return toast(data.error, true);
        cur = data.cwd || "";
        parent = data.parent || "";
        body.querySelector(".fe-path").textContent = "/" + cur;
        grid.innerHTML = "";
        if (!data.items.length) {{
          grid.innerHTML = '<div class="muted">Папка порожня</div>';
          return;
        }}
        data.items.forEach(it => {{
          const card = document.createElement("div");
          card.style.cssText = "background:var(--panel-2); border:1px solid var(--border); border-radius:10px; padding:10px; display:flex; flex-direction:column; gap:8px; cursor:pointer;";
          const ic = it.type === "dir" ? (it.is_git ? "📦" : "📁") : (it.name.endsWith(".py") ? "🐍" : (it.name.endsWith(".html") ? "🌐" : (it.name.endsWith(".md") ? "📝" : "📄")));
          card.innerHTML = `
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:22px;">${{ic}}</span>
              <div style="min-width:0; flex:1;">
                <div class="mono" style="font-size:12.5px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${{esc(it.name)}}</div>
                <div class="muted" style="font-size:11px;">${{it.type === "dir" ? "Папка" : (it.size + " B")}}</div>
              </div>
            </div>
            <div style="display:flex; gap:4px; margin-top:auto;">
              <button class="btn btn-ghost fe-open" style="padding:3px 7px; font-size:11px; flex:1;" type="button">Відкрити</button>
              ${{it.type === "file" ? '<button class="btn btn-ghost fe-dl" style="padding:3px 7px; font-size:11px;" type="button" title="Скачати">↓</button>' : ''}}
              ${{it.path !== "server.json" ? '<button class="btn btn-danger fe-del" style="padding:3px 7px; font-size:11px;" type="button" title="Видалити">×</button>' : ''}}
            </div>
          `;
          const triggerOpen = () => {{
            if (it.type === "dir") return load(it.path);
            if (it.name.endsWith(".html") || it.name.endsWith(".htm")) return openApp("browser", {{ file: it.path }});
            if (it.name.endsWith(".md")) return openApp("notes", {{ file: it.path }});
            return openApp("code", {{ file: it.path }});
          }};
          card.addEventListener("dblclick", triggerOpen);
          card.querySelector(".fe-open").addEventListener("click", (e) => {{ e.stopPropagation(); triggerOpen(); }});
          const dl = card.querySelector(".fe-dl");
          if (dl) dl.addEventListener("click", (e) => {{
            e.stopPropagation();
            const url = `${{ROOT}}/api/files/download?path=${{encodeURIComponent(it.path)}}&token=${{encodeURIComponent(getToken())}}`;
            window.open(url, "_blank");
          }});
          const del = card.querySelector(".fe-del");
          if (del) del.addEventListener("click", async (e) => {{
            e.stopPropagation();
            if (!confirm(`Видалити '${{it.name}}'?`)) return;
            await api("api/files/delete", {{ method: "POST", body: JSON.stringify({{ path: it.path }}) }});
            load(cur);
          }});
          grid.appendChild(card);
        }});
      }}

      body.querySelector(".fe-up").addEventListener("click", () => load(parent));
      body.querySelector(".fe-nf").addEventListener("click", async () => {{
        const n = prompt("Назва файлу:");
        if (!n) return;
        const p = cur ? `${{cur}}/${{n}}` : n;
        const r = await api("api/files/write", {{ method: "POST", body: JSON.stringify({{ path: p, content: "" }}) }});
        if (!r.data.ok) return toast(r.data.error, true);
        load(cur);
      }});
      body.querySelector(".fe-nd").addEventListener("click", async () => {{
        const n = prompt("Назва папки:");
        if (!n) return;
        const p = cur ? `${{cur}}/${{n}}` : n;
        const r = await api("api/files/mkdir", {{ method: "POST", body: JSON.stringify({{ path: p }}) }});
        if (!r.data.ok) return toast(r.data.error, true);
        load(cur);
      }});
      body.querySelector(".fe-up-in").addEventListener("change", (e) => {{
        const f = e.target.files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = async () => {{
          const b64 = String(rd.result).split(",")[1] || "";
          const p = cur ? `${{cur}}/${{f.name}}` : f.name;
          const r = await api("api/files/upload", {{ method: "POST", body: JSON.stringify({{ path: p, data_b64: b64 }}) }});
          e.target.value = "";
          if (!r.data.ok) return toast(r.data.error, true);
          toast(`Завантажено ${{f.name}}`);
          load(cur);
        }};
        rd.readAsDataURL(f);
      }});
      body.querySelector(".fe-tpl-py").addEventListener("click", () => createTemplateFlow("python-app", () => load(cur)));
      body.querySelector(".fe-tpl-html").addEventListener("click", () => createTemplateFlow("html-app", () => load(cur)));

      winRec.onParams = (p) => {{ if (p.dir !== undefined) load(p.dir); }};
      load(cur);
    }}

    async function createTemplateFlow(kind, onDone) {{
      const defName = kind === "html-app" ? "my-web-app" : "my-python-tool";
      const name = prompt(`Назва нового проєкту (${{kind}}):`, defName);
      if (!name) return;
      const {{ data }} = await api("api/os/template", {{
        method: "POST",
        body: JSON.stringify({{ kind, name }})
      }});
      if (!data.ok) return toast(data.error, true);
      toast(`Створено проєкт '${{data.name}}'`);
      if (onDone) onDone();
      if (kind === "html-app") openApp("browser", {{ file: data.entry }});
      else openApp("code", {{ dir: data.path, file: data.entry }});
    }}

    // 4. GITHUB STUDIO
    function mountGitStudio(winRec, body) {{
      body.innerHTML = `
        <div class="toolbar">
          <input class="g-url" type="text" style="flex:1; min-width:210px;" placeholder="GitHub: owner/repo або https://github.com/..." />
          <input class="g-dir" type="text" style="width:140px;" placeholder="Папка (авто)" />
          <button class="btn g-clone" type="button">⬇ Клонувати</button>
          <button class="btn btn-ghost g-init" type="button">+ git init</button>
          <button class="btn btn-ghost g-ref" type="button">↻</button>
        </div>
        <div style="padding:12px; overflow-y:auto; flex:1;" class="g-list"></div>
        <div class="g-log mono selectable" style="height:110px; background:#050811; border-top:1px solid var(--border); padding:8px 11px; font-size:12px; color:#93c5fd; overflow-y:auto; white-space:pre-wrap;">Готово до роботи з Git та GitHub репозиторіями.</div>
      `;
      const listEl = body.querySelector(".g-list");
      const logEl = body.querySelector(".g-log");

      async function refresh() {{
        const {{ data }} = await api("api/git/repos");
        if (!data.ok) return;
        listEl.innerHTML = "";
        if (!data.repos.length) {{
          listEl.innerHTML = '<div class="muted" style="padding:14px;">Репозиторіїв поки немає. Введи owner/repo зверху для клонування з GitHub або натисни «+ git init».</div>';
          return;
        }}
        data.repos.forEach(r => {{
          const card = document.createElement("div");
          card.style.cssText = "background:var(--panel-2); border:1px solid var(--border); border-radius:11px; padding:13px; margin-bottom:10px;";
          card.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
              <div>
                <strong style="font-size:15px;">📦 ${{esc(r.name)}}</strong>
                <span style="margin-left:8px; font-size:11.5px; padding:2px 8px; border-radius:99px; background:rgba(56,189,248,0.16); color:var(--accent);">🌿 ${{esc(r.branch)}}</span>
                <div class="muted mono" style="font-size:11.5px; margin-top:2px;">${{esc(r.remote_url || "локальний репозиторій")}}</div>
              </div>
              <div style="display:flex; gap:5px; flex-wrap:wrap;">
                <button class="btn btn-ghost g-act" data-a="status" type="button">Status</button>
                <button class="btn btn-ghost g-act" data-a="pull" type="button">Pull</button>
                <button class="btn btn-ghost g-act" data-a="commit" type="button">Commit</button>
                <button class="btn btn-ghost g-act" data-a="push" type="button">Push</button>
                <button class="btn btn-ghost g-act" data-a="checkout" type="button">Гілка</button>
                <button class="btn g-code" type="button">💻 Код</button>
                <button class="btn btn-ghost g-term" type="button">🖥 Термінал</button>
              </div>
            </div>
            <div class="mono muted" style="font-size:12px;">Змінених файлів: ${{r.changed_count}}${{r.commits.length ? " • Останній коміт: " + esc(r.commits[0].hash + " " + r.commits[0].subject) : ""}}</div>
          `;
          card.querySelectorAll(".g-act").forEach(b => b.addEventListener("click", async () => {{
            const act = b.dataset.a;
            const payload = {{ path: r.path, action: act }};
            if (act === "commit") {{
              const m = prompt("Повідомлення коміту:");
              if (!m) return;
              payload.message = m;
            }} else if (act === "checkout") {{
              const br = prompt("Назва гілки:", r.branch);
              if (!br) return;
              payload.branch = br;
            }}
            logEl.textContent = `Виконую git ${{act}}...`;
            const res = await api("api/git/action", {{ method: "POST", body: JSON.stringify(payload) }});
            logEl.textContent = res.data.ok ? res.data.output : ("Помилка: " + res.data.error);
            refresh();
          }}));
          card.querySelector(".g-code").addEventListener("click", () => openApp("code", {{ dir: r.path }}));
          card.querySelector(".g-term").addEventListener("click", () => openApp("terminal", {{ cwd: r.path }}));
          listEl.appendChild(card);
        }});
      }}

      body.querySelector(".g-clone").addEventListener("click", async () => {{
        const repo = body.querySelector(".g-url").value.trim();
        const folder = body.querySelector(".g-dir").value.trim();
        if (!repo) return toast("Вкажи owner/repo або URL", true);
        logEl.textContent = `Клонування ${{repo}}...`;
        const {{ data }} = await api("api/git/clone", {{ method: "POST", body: JSON.stringify({{ repo, folder }}) }});
        if (!data.ok) {{ logEl.textContent = "Помилка: " + data.error; return toast(data.error, true); }}
        body.querySelector(".g-url").value = "";
        body.querySelector(".g-dir").value = "";
        logEl.textContent = data.output || `Клоновано ${{data.name}}`;
        toast(`Клоновано ${{data.name}}`);
        refresh();
      }});

      body.querySelector(".g-init").addEventListener("click", async () => {{
        const folder = prompt("Назва папки для нового Git-репозиторію:");
        if (!folder) return;
        const {{ data }} = await api("api/git/init", {{ method: "POST", body: JSON.stringify({{ folder }}) }});
        if (!data.ok) return toast(data.error, true);
        logEl.textContent = data.output || `Ініціалізовано ${{data.path}}`;
        refresh();
      }});
      body.querySelector(".g-ref").addEventListener("click", refresh);
      refresh();
    }}

    // 5. KANBAN BOARD
    function mountKanban(winRec, body) {{
      body.innerHTML = `
        <form class="toolbar kb-form">
          <input class="kb-title" type="text" style="flex:1;" placeholder="Нова робоча задача..." required />
          <select class="kb-prio">
            <option value="normal">Звичайний пріоритет</option>
            <option value="high">🔥 Високий пріоритет</option>
          </select>
          <button class="btn" type="submit">+ Додати задачу</button>
        </form>
        <div class="kb-board">
          <div class="kb-col"><div style="font-weight:800; font-size:13px; color:var(--muted);">📌 Заплановано</div><div class="kb-items" data-col="todo"></div></div>
          <div class="kb-col"><div style="font-weight:800; font-size:13px; color:var(--accent);">⚡ В роботі</div><div class="kb-items" data-col="doing"></div></div>
          <div class="kb-col"><div style="font-weight:800; font-size:13px; color:var(--green);">✅ Готово</div><div class="kb-items" data-col="done"></div></div>
        </div>
      `;

      const cols = ["todo", "doing", "done"];
      function render() {{
        body.querySelectorAll(".kb-items").forEach(el => {{ el.innerHTML = ""; }});
        (osState.tasks || []).forEach(t => {{
          const cEl = body.querySelector(`.kb-items[data-col="${{t.col}}"]`);
          if (!cEl) return;
          const card = document.createElement("div");
          card.className = "kb-card" + (t.priority === "high" ? " high" : "");
          card.style.marginBottom = "8px";
          const idx = cols.indexOf(t.col);
          card.innerHTML = `
            <div style="margin-bottom:8px; line-height:1.38;">${{t.priority === "high" ? "🔥 " : ""}}${{esc(t.title)}}</div>
            <div style="display:flex; justify-content:space-between; gap:4px;">
              <div>
                ${{idx > 0 ? '<button class="btn btn-ghost kb-prev" style="padding:2px 7px; font-size:11px;" type="button">←</button>' : ''}}
                ${{idx < 2 ? '<button class="btn btn-ghost kb-next" style="padding:2px 7px; font-size:11px;" type="button">→</button>' : ''}}
              </div>
              <button class="btn btn-danger kb-del" style="padding:2px 7px; font-size:11px;" type="button">×</button>
            </div>
          `;
          const prev = card.querySelector(".kb-prev");
          if (prev) prev.addEventListener("click", async () => {{
            t.col = cols[idx - 1];
            await saveOsStatePatch({{ tasks: osState.tasks }});
            render();
          }});
          const next = card.querySelector(".kb-next");
          if (next) next.addEventListener("click", async () => {{
            t.col = cols[idx + 1];
            await saveOsStatePatch({{ tasks: osState.tasks }});
            render();
          }});
          card.querySelector(".kb-del").addEventListener("click", async () => {{
            osState.tasks = osState.tasks.filter(x => x.id !== t.id);
            await saveOsStatePatch({{ tasks: osState.tasks }});
            render();
          }});
          cEl.appendChild(card);
        }});
      }}

      body.querySelector(".kb-form").addEventListener("submit", async (e) => {{
        e.preventDefault();
        const title = body.querySelector(".kb-title").value.trim();
        const priority = body.querySelector(".kb-prio").value;
        if (!title) return;
        const tasks = Array.from(osState.tasks || []);
        tasks.unshift({{ id: "t_" + Date.now(), title, col: "todo", priority }});
        body.querySelector(".kb-title").value = "";
        await saveOsStatePatch({{ tasks }});
        render();
      }});

      render();
    }}

    // 6. MARKDOWN NOTES
    function mountNotesApp(winRec, body, params) {{
      let filePath = params.file || "notes.md";
      body.innerHTML = `
        <div class="toolbar">
          <span class="mono n-path" style="font-size:12.5px; font-weight:700;"></span>
          <button class="btn btn-ghost n-open" type="button">Змінити .md файл</button>
          <button class="btn n-save" style="margin-left:auto;" type="button">💾 Зберегти на сервер</button>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; flex:1; min-height:0;">
          <textarea class="n-ed mono" style="border:none; border-right:1px solid var(--border); border-radius:0; padding:14px; resize:none; line-height:1.55;" placeholder="# Мої нотатки..."></textarea>
          <div class="n-prev selectable" style="padding:16px; overflow-y:auto; line-height:1.6; font-size:13.5px;"></div>
        </div>
      `;
      const ed = body.querySelector(".n-ed");
      const prev = body.querySelector(".n-prev");

      function renderMd(md) {{
        const lines = esc(md).split("\\n").map(ln => {{
          if (ln.startsWith("### ")) return `<h3 style="margin:10px 0 4px; color:var(--accent);">${{ln.slice(4)}}</h3>`;
          if (ln.startsWith("## ")) return `<h2 style="margin:12px 0 6px; color:var(--accent);">${{ln.slice(3)}}</h2>`;
          if (ln.startsWith("# ")) return `<h1 style="margin:8px 0 8px;">${{ln.slice(2)}}</h1>`;
          if (ln.startsWith("- ") || ln.startsWith("* ")) return `<div style="padding-left:12px;">• ${{ln.slice(2)}}</div>`;
          return ln ? `<p style="margin-bottom:6px;">${{ln}}</p>` : "<br/>";
        }});
        prev.innerHTML = lines.join("");
      }}

      async function loadMd(p) {{
        filePath = p;
        body.querySelector(".n-path").textContent = "📝 " + filePath;
        const {{ data }} = await api("api/files/read?path=" + encodeURIComponent(filePath));
        ed.value = data.ok ? data.content : `# ${{filePath}}\\n\\n`;
        renderMd(ed.value);
      }}

      ed.addEventListener("input", () => renderMd(ed.value));
      body.querySelector(".n-save").addEventListener("click", async () => {{
        const {{ data }} = await api("api/files/write", {{
          method: "POST",
          body: JSON.stringify({{ path: filePath, content: ed.value }})
        }});
        if (!data.ok) return toast(data.error, true);
        toast(`Нотатку ${{filePath}} збережено`);
      }});
      body.querySelector(".n-open").addEventListener("click", () => {{
        const p = prompt("Шлях до .md файлу в середовищі (напр. plan.md):", filePath);
        if (p) loadMd(p.endsWith(".md") ? p : p + ".md");
      }});
      winRec.onParams = (p) => {{ if (p.file) loadMd(p.file); }};
      loadMd(filePath);
    }}

    // 7. WEB RUNNER (LIVE HTML APP PREVIEW)
    function mountBrowserRunner(winRec, body, params) {{
      let curFile = params.file || "";
      body.innerHTML = `
        <form class="toolbar br-form">
          <button class="btn btn-ghost br-rel" type="button" title="Перезавантажити">↻</button>
          <input class="br-in mono" type="text" style="flex:1;" placeholder="Шлях до HTML у середовищі (напр. my-web-app/index.html)" />
          <button class="btn" type="submit">Відкрити</button>
          <button class="btn btn-green br-new" type="button">+ Створити HTML-проєкт</button>
          <button class="btn btn-ghost br-ext" type="button" title="У новій вкладці">↗</button>
        </form>
        <iframe class="br-frame" style="flex:1; border:none; background:#fff;"></iframe>
      `;
      const inp = body.querySelector(".br-in");
      const frame = body.querySelector(".br-frame");

      function buildUrl(rel) {{
        const clean = rel.replace(/^\\/+/, "");
        return `${{ROOT}}/workspace/${{clean}}?token=${{encodeURIComponent(getToken())}}&_t=${{Date.now()}}`;
      }}

      function navigate(rel) {{
        curFile = (rel || "").trim();
        inp.value = curFile;
        if (!curFile) {{
          frame.srcdoc = `<body style="font-family:system-ui;background:#0d1424;color:#cbd5e1;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;"><div style="text-align:center;max-width:420px;"><h2>🌐 Веб-Ранер WiGi OS</h2><p style="color:#94a3b8;line-height:1.5;">Запускає будь-які HTML/CSS/JS проєкти прямо із папки твого сервера. Натисни «+ Створити HTML-проєкт» зверху або вкажи шлях до .html файлу.</p></div></body>`;
          return;
        }}
        frame.removeAttribute("srcdoc");
        frame.src = buildUrl(curFile);
      }}

      body.querySelector(".br-form").addEventListener("submit", (e) => {{
        e.preventDefault();
        navigate(inp.value);
      }});
      body.querySelector(".br-rel").addEventListener("click", () => navigate(inp.value));
      body.querySelector(".br-ext").addEventListener("click", () => {{
        if (inp.value.trim()) window.open(buildUrl(inp.value.trim()), "_blank");
      }});
      body.querySelector(".br-new").addEventListener("click", () => {{
        createTemplateFlow("html-app");
      }});

      winRec.onParams = (p) => {{ if (p.file) navigate(p.file); }};

      if (curFile) navigate(curFile);
      else {{
        api("api/os/search").then(({{ data }}) => {{
          const htmlFile = (data.files || []).find(f => f.path.endsWith(".html"));
          navigate(htmlFile ? htmlFile.path : "");
        }}).catch(() => navigate(""));
      }}
    }}

    // 8. SYSTEM MONITOR & PROCESSES
    function mountSystemMonitor(winRec, body) {{
      body.innerHTML = `
        <div style="padding:14px; overflow-y:auto; flex:1;">
          <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; margin-bottom:14px;" class="m-cards"></div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <strong style="font-size:13px; color:var(--muted);">АКТИВНІ ПРОЦЕСИ ХОСТА (CPU TOP)</strong>
            <button class="btn btn-ghost m-ref" type="button">↻ Оновити</button>
          </div>
          <div class="m-procs mono" style="background:#060a14; border:1px solid var(--border); border-radius:10px; padding:10px; font-size:12px;"></div>
        </div>
      `;
      const cardsEl = body.querySelector(".m-cards");
      const procsEl = body.querySelector(".m-procs");

      async function load() {{
        const [stRes, prRes] = await Promise.all([api("api/status"), api("api/os/processes")]);
        if (stRes.data.ok) {{
          const h = stRes.data.host;
          const s = stRes.data.server;
          const ramTxt = h.memory ? `${{h.memory.used_mb}} / ${{h.memory.total_mb}} МБ (${{h.memory.percent}}%)` : "Н/Д";
          const diskTxt = h.disk ? `${{h.disk.used_gb}} / ${{h.disk.total_gb}} ГБ (${{h.disk.percent}}%)` : "Н/Д";
          cardsEl.innerHTML = `
            <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:10px; padding:11px;"><div class="muted" style="font-size:11.5px;">Система / CPU</div><div class="mono" style="font-size:13px; margin-top:4px;">${{esc(h.os)}} (${{h.cpu_cores}} ядер)</div></div>
            <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:10px; padding:11px;"><div class="muted" style="font-size:11.5px;">RAM Пам'ять</div><div class="mono" style="font-size:13px; margin-top:4px;">${{ramTxt}}</div></div>
            <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:10px; padding:11px;"><div class="muted" style="font-size:11.5px;">Диск</div><div class="mono" style="font-size:13px; margin-top:4px;">${{diskTxt}}</div></div>
            <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:10px; padding:11px;"><div class="muted" style="font-size:11.5px;">Активних сесій</div><div class="mono" style="font-size:13px; margin-top:4px;">${{(stRes.data.sessions || []).length}} • порт ${{s.port}}</div></div>
          `;
        }}
        if (prRes.data.ok) {{
          const rows = (prRes.data.processes || []).map(p =>
            `<div style="display:grid; grid-template-columns:70px 70px 80px 1fr; padding:4px 0; border-bottom:1px solid rgba(96,132,190,0.14);"><span>${{esc(p.pid)}}</span><span style="color:var(--accent);">${{esc(p.cpu)}}</span><span>${{esc(p.mem)}}</span><span>${{esc(p.command)}}</span></div>`
          );
          procsEl.innerHTML = `<div style="display:grid; grid-template-columns:70px 70px 80px 1fr; color:var(--muted); font-weight:700; padding-bottom:6px;"><span>PID</span><span>CPU</span><span>MEM</span><span>COMMAND</span></div>` + rows.join("");
        }}
      }}
      body.querySelector(".m-ref").addEventListener("click", load);
      load();
      const iv = setInterval(load, 4000);
      winRec.cleanup = () => clearInterval(iv);
    }}

    // 9. OS SETTINGS & ENV
    function mountSettingsApp(winRec, body) {{
      body.innerHTML = `
        <div style="padding:14px; overflow-y:auto; flex:1; display:flex; flex-direction:column; gap:14px;">
          <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:11px; padding:13px;">
            <div style="font-weight:700; margin-bottom:9px;">🎨 Тема робочого столу WiGi OS</div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;" class="th-btns">
              <button class="btn btn-ghost" data-th="cyber" type="button">Cyber Grid</button>
              <button class="btn btn-ghost" data-th="nebula" type="button">Deep Nebula</button>
              <button class="btn btn-ghost" data-th="matrix" type="button">Matrix Core</button>
              <button class="btn btn-ghost" data-th="sunset" type="button">Sunset Synth</button>
              <button class="btn btn-ghost" data-th="slate" type="button">Minimal Slate</button>
            </div>
          </div>

          <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:11px; padding:13px;">
            <div style="font-weight:700; margin-bottom:6px;">🔑 Змінні середовища сервера (ENV)</div>
            <div class="muted" style="font-size:12px; margin-bottom:8px;">Доступні у Python, Терміналі та Git (формат KEY=VALUE):</div>
            <textarea class="s-env mono" rows="6" style="width:100%;" placeholder="GITHUB_TOKEN=...&#10;MODE=production"></textarea>
            <div style="margin-top:8px; display:flex; justify-content:space-between;">
              <button class="btn s-save-env" type="button">Зберегти ENV</button>
              <a class="btn btn-ghost" style="text-decoration:none;" href="${{ROOT || ''}}/">Розширені налаштування панелі ↗</a>
            </div>
          </div>
        </div>
      `;

      body.querySelectorAll("[data-th]").forEach(b => b.addEventListener("click", async () => {{
        const th = b.dataset.th;
        document.body.dataset.theme = th;
        await saveOsStatePatch({{ theme: th }});
        toast(`Тему змінено: ${{th}}`);
      }}));

      api("api/env").then(({{ data }}) => {{
        if (data.ok) {{
          body.querySelector(".s-env").value = Object.entries(data.env || {{}}).map(([k, v]) => `${{k}}=${{v}}`).join("\\n");
        }}
      }});

      body.querySelector(".s-save-env").addEventListener("click", async () => {{
        const env = {{}};
        for (const ln of body.querySelector(".s-env").value.split("\\n")) {{
          const t = ln.trim();
          if (!t || t.startsWith("#")) continue;
          const eq = t.indexOf("=");
          if (eq === -1) return toast(`Некоректний рядок: ${{t}}`, true);
          env[t.slice(0, eq).trim()] = t.slice(eq + 1);
        }}
        const {{ data }} = await api("api/env", {{ method: "POST", body: JSON.stringify({{ env }}) }});
        if (!data.ok) return toast(data.error, true);
        toast("Змінні ENV збережено");
      }});
    }}

    // =========================================================================
    // START MENU, CONTEXT MENU, COMMAND PALETTE (Ctrl+K) & SYSTEM TRAY
    // =========================================================================

    const startMenu = document.getElementById("startMenu");
    const ctxMenu = document.getElementById("ctxMenu");
    const cmdPalette = document.getElementById("cmdPalette");

    function hidePopups() {{
      startMenu.classList.add("hidden");
      ctxMenu.classList.add("hidden");
      cmdPalette.classList.add("hidden");
    }}

    document.getElementById("startBtn").addEventListener("click", (e) => {{
      e.stopPropagation();
      ctxMenu.classList.add("hidden");
      cmdPalette.classList.add("hidden");
      startMenu.classList.toggle("hidden");
    }});
    document.getElementById("desktop").addEventListener("click", () => hidePopups());

    // Right-click desktop menu
    document.getElementById("desktop").addEventListener("contextmenu", (e) => {{
      if (e.target.closest(".os-win") || e.target.closest(".sticky-widget")) return;
      e.preventDefault();
      startMenu.classList.add("hidden");
      ctxMenu.style.left = Math.min(window.innerWidth - 235, e.clientX) + "px";
      ctxMenu.style.top = Math.min(window.innerHeight - 250, e.clientY) + "px";
      ctxMenu.classList.remove("hidden");
    }});

    ctxMenu.querySelectorAll(".ctx-item").forEach(item => item.addEventListener("click", async () => {{
      const act = item.dataset.act;
      hidePopups();
      if (act === "open-code") openApp("code");
      if (act === "open-term") openApp("terminal");
      if (act === "open-git") openApp("git");
      if (act === "tpl-py") createTemplateFlow("python-app");
      if (act === "tpl-html") createTemplateFlow("html-app");
      if (act === "cycle-theme") {{
        const order = ["cyber", "nebula", "matrix", "sunset", "slate"];
        const next = order[(order.indexOf(document.body.dataset.theme) + 1) % order.length];
        document.body.dataset.theme = next;
        await saveOsStatePatch({{ theme: next }});
        toast(`Тема: ${{next}}`);
      }}
    }}));

    // Command Palette (Ctrl+K)
    let flatFilesCache = [];
    async function openCommandPalette() {{
      hidePopups();
      cmdPalette.classList.remove("hidden");
      const inp = document.getElementById("cmdSearchInput");
      inp.value = "";
      inp.focus();
      try {{
        const {{ data }} = await api("api/os/search");
        if (data.ok) flatFilesCache = data.files || [];
      }} catch (_) {{}}
      renderPalette("");
    }}

    function renderPalette(q) {{
      const term = q.trim().toLowerCase();
      const box = document.getElementById("cmdResults");
      box.innerHTML = "";
      const items = [];
      APPS.forEach(a => {{
        if (!term || a.title.toLowerCase().includes(term) || a.id.includes(term)) {{
          items.push({{ label: `${{a.icon}} Додаток: ${{a.title}}`, hint: "Відкрити вікно", run: () => openApp(a.id) }});
        }}
      }});
      flatFilesCache.forEach(f => {{
        if (!term || f.path.toLowerCase().includes(term)) {{
          items.push({{
            label: `📄 ${{f.path}}`,
            hint: f.path.endsWith(".html") ? "Веб-Ранер" : "Code Studio",
            run: () => f.path.endsWith(".html") ? openApp("browser", {{ file: f.path }}) : openApp("code", {{ file: f.path }})
          }});
        }}
      }});
      items.slice(0, 20).forEach(it => {{
        const r = document.createElement("div");
        r.className = "cmd-row";
        r.innerHTML = `<span>${{esc(it.label)}}</span><span class="muted" style="font-size:11.5px;">${{esc(it.hint)}}</span>`;
        r.addEventListener("click", () => {{ hidePopups(); it.run(); }});
        box.appendChild(r);
      }});
    }}

    document.getElementById("searchBarBtn").addEventListener("click", openCommandPalette);
    document.getElementById("smPaletteBtn").addEventListener("click", openCommandPalette);
    document.getElementById("cmdSearchInput").addEventListener("input", (e) => renderPalette(e.target.value));
    cmdPalette.addEventListener("click", (e) => {{ if (e.target === cmdPalette) hidePopups(); }});
    window.addEventListener("keydown", (e) => {{
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {{
        e.preventDefault();
        openCommandPalette();
      }} else if (e.key === "Escape") {{
        hidePopups();
      }}
    }});

    document.getElementById("sysTrayMonitor").addEventListener("click", () => openApp("monitor"));
    document.getElementById("lockOsBtn").addEventListener("click", () => {{ hidePopups(); showLockScreen(); }});
    document.getElementById("logoutOsBtn").addEventListener("click", async () => {{
      hidePopups();
      try {{ await api("api/logout", {{ method: "POST", body: "{{}}" }}); }} catch (_) {{}}
      setToken("");
      showLockScreen();
    }});

    // System Tray background stats poll
    let statsTimer = null;
    async function pollTrayStats() {{
      try {{
        const {{ data }} = await api("api/status");
        if (data.ok) {{
          document.getElementById("smServerName").textContent = data.server.name;
          if (data.host.memory) {{
            document.getElementById("trayStats").textContent = `RAM ${{data.host.memory.percent}}%`;
          }} else {{
            document.getElementById("trayStats").textContent = `${{data.host.cpu_cores}} CPU`;
          }}
        }}
      }} catch (_) {{}}
    }}

    // Lock / Unlock Lifecycle
    const lockScreen = document.getElementById("lockScreen");
    function showLockScreen() {{
      if (statsTimer) {{ clearInterval(statsTimer); statsTimer = null; }}
      lockScreen.classList.remove("hidden");
      setTimeout(() => document.getElementById("unlockPw").focus(), 50);
    }}

    async function bootDesktop() {{
      lockScreen.classList.add("hidden");
      await loadOsState();
      await pollTrayStats();
      if (statsTimer) clearInterval(statsTimer);
      statsTimer = setInterval(pollTrayStats, 5000);
      if (windows.size === 0) {{
        openApp("code");
      }}
    }}

    document.getElementById("unlockForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const errEl = document.getElementById("unlockErr");
      errEl.textContent = "";
      const password = document.getElementById("unlockPw").value;
      const res = await fetch(ROOT + "/api/login", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ password }})
      }});
      const data = await res.json();
      if (!res.ok || !data.ok) {{
        errEl.textContent = data.error || "Невірний пароль";
        return;
      }}
      setToken(data.token || "");
      document.getElementById("unlockPw").value = "";
      await bootDesktop();
    }});

    (async () => {{
      const res = await fetch(ROOT + "/api/info", {{ headers: authHeaders() }});
      const info = await res.json();
      if (info.authenticated) {{
        await bootDesktop();
      }} else {{
        showLockScreen();
      }}
    }})();
  </script>
</body>
</html>
"""
