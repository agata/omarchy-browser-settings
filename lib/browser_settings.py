"""Browser selection and an independent XDG URL handler for Omarchy.

No shell configuration is changed by this module. Preferences are applied only
through the explicit apply/restore/uninstall commands, never on plugin load.
"""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

VERSION = "0.1.0"
DESKTOP_ID = "omarchy-browser-settings-handler.desktop"
MIME_TYPES = ("x-scheme-handler/http", "x-scheme-handler/https", "text/html")
EXCLUDED_IDS = {DESKTOP_ID, "omarchy-workspace-browser.desktop"}
ADAPTERS = {
  "chromium": "^[cC]hromium$",
  "google-chrome-stable": "^[Gg]oogle-chrome$",
  "google-chrome": "^[Gg]oogle-chrome$",
}
NATIVE_IDS = {"chromium.desktop", "google-chrome.desktop", "com.google.Chrome.desktop"}


def paths():
  home = Path.home()
  config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
  data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
  state = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
  return {
    "config": config / "omarchy/browser-settings.json",
    "mime": config / "mimeapps.list",
    "runtime": data / "omarchy-browser-settings",
    "desktop": data / "applications" / DESKTOP_ID,
    "bin": home / ".local/bin",
    "state": state / "omarchy/browser-settings",
  }


def atomic_write(path, content, mode=0o600):
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
  try:
    with os.fdopen(fd, "w") as stream:
      stream.write(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def write_json(path, data):
  atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path, default=None):
  if not path.exists():
    return default if default is not None else {}
  return json.loads(path.read_text())


def gio():
  import gi
  gi.require_version("Gio", "2.0")
  from gi.repository import Gio
  try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix
    desktop_class = GioUnix.DesktopAppInfo
  except (ValueError, ImportError):
    desktop_class = Gio.DesktopAppInfo
  return Gio, desktop_class


def get_app(desktop_id):
  if not re.fullmatch(r"[A-Za-z0-9_.-]+\.desktop", desktop_id):
    raise ValueError("Invalid desktop application ID")
  _, desktop_class = gio()
  app = desktop_class.new(desktop_id)
  # Some older GIR releases expose GioUnix instance methods as functions.
  # Calling through the class with an explicit instance works with both forms.
  if app is None or desktop_class.get_is_hidden(app):
    raise ValueError("Browser is no longer installed: " + desktop_id)
  if desktop_id in EXCLUDED_IDS:
    raise ValueError("Select the real browser, not a routing handler")
  return app


def adapter(app):
  # Only native launchers with the standard command line are verified. Flatpak,
  # custom profiles and wrappers remain available for normal default selection.
  if app.get_id() not in NATIVE_IDS:
    return None
  args = shlex.split(app.get_commandline() or "")
  if not args or args[1:] not in (["%U"], ["%u"], []):
    return None
  executable = shutil.which(args[0])
  window_class = ADAPTERS.get(Path(args[0]).name)
  if executable and window_class:
    return {"executable": executable, "class": window_class}
  return None


def browsers():
  Gio, desktop_class = gio()
  result = []
  for item in Gio.AppInfo.get_all():
    app = desktop_class.new(item.get_id()) if item.get_id() else None
    if app is None or not app.should_show() or app.get_id() in EXCLUDED_IDS:
      continue
    if "WebBrowser" not in (desktop_class.get_categories(app) or "").split(";"):
      continue
    if not app.supports_uris():
      continue
    icon = app.get_icon()
    result.append({
      "id": app.get_id(), "name": app.get_display_name(),
      "icon": icon.to_string() if icon else "web-browser",
      "workspace_supported": adapter(app) is not None,
    })
  return sorted(result, key=lambda item: (item["name"].casefold(), item["id"]))


def run(*args, check=True):
  env = dict(os.environ)
  env.pop("BROWSER", None)
  result = subprocess.run(args, text=True, capture_output=True, env=env, timeout=15)
  if check and result.returncode:
    raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Command failed: " + args[0])
  return result.stdout.strip()


def defaults():
  return {mime: run("xdg-mime", "query", "default", mime) for mime in MIME_TYPES}


def set_default(mime, desktop_id):
  if desktop_id:
    run("xdg-mime", "default", desktop_id, mime)
    if run("xdg-mime", "query", "default", mime) != desktop_id:
      raise RuntimeError("Could not update the default application for " + mime)
    return
  # xdg-mime has no unset command. On Omarchy it writes this standard file.
  path = paths()["mime"]
  if path.exists():
    section = ""
    lines = []
    for line in path.read_text().splitlines(keepends=True):
      if line.strip().startswith("["):
        section = line.strip()
      if section == "[Default Applications]" and line.startswith(mime + "="):
        continue
      lines.append(line)
    atomic_write(path, "".join(lines), path.stat().st_mode & 0o777)


@contextmanager
def settings_lock():
  directory = paths()["state"]
  directory.mkdir(parents=True, exist_ok=True, mode=0o700)
  with (directory / "settings.lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    yield


def status():
  p = paths()
  config = read_json(p["config"])
  current = defaults()
  configured = config.get("browser", "")
  routed = all(value == DESKTOP_ID for value in current.values())
  actual = current["x-scheme-handler/https"]
  selected = configured if actual == DESKTOP_ID else actual
  return {
    "version": VERSION, "browsers": browsers(), "defaults": current,
    "selected": selected, "same_workspace": routed and config.get("same_workspace", False),
    "mixed_defaults": len(set(current.values())) > 1,
    "can_restore": (p["state"] / "session.json").exists(),
    "runtime_installed": (p["runtime"] / "browser_settings.py").exists(),
  }


def install_runtime(app):
  p = paths()
  source = Path(__file__).resolve().parent
  p["runtime"].mkdir(parents=True, exist_ok=True)
  for name in ("browser_settings.py", "workspace-router"):
    target = p["runtime"] / name
    if source / name != target:
      atomic_write(target, (source / name).read_text(), 0o755 if name == "workspace-router" else 0o644)
  python = shlex.quote(str(p["runtime"] / "browser_settings.py"))
  for name, arguments in [
    ("omarchy-setup-browser-settings", ' "$@"'),
    ("omarchy-launch-browser-settings", ' open -- "$@"'),
  ]:
    atomic_write(p["bin"] / name, '#!/bin/bash\nexec /usr/bin/python3 ' + python + arguments + '\n', 0o755)
  launcher = shutil.which("omarchy-launch-browser-settings")
  if not launcher or Path(launcher).resolve() != (p["bin"] / "omarchy-launch-browser-settings").resolve():
    raise ValueError("Add ~/.local/bin to the front of PATH before applying Browser Settings")
  # NoDisplay keeps this internal handler out of the real-browser picker.
  name = app.get_display_name().replace("\n", " ").replace("\r", " ")
  atomic_write(p["desktop"], "\n".join([
    "[Desktop Entry]", "Type=Application", "Name=" + name + " (Current Workspace)",
    "Comment=Open links in the selected browser on the current workspace",
    # Both xdg-utils and Omarchy's browser launcher inspect the first Exec word.
    # A command on PATH also works when HOME itself contains spaces.
    "Exec=omarchy-launch-browser-settings %U",
    "Icon=web-browser", "Terminal=false", "NoDisplay=true", "StartupNotify=true",
    "Categories=Network;WebBrowser;", "MimeType=" + ";".join(MIME_TYPES) + ";", "",
  ]), 0o644)
  run("update-desktop-database", str(p["desktop"].parent))


def apply(browser_id, same_workspace=False):
  app = get_app(browser_id)
  if browser_id not in {item["id"] for item in browsers()}:
    raise ValueError("Select an installed web browser")
  if same_workspace and adapter(app) is None:
    raise ValueError("Current-workspace routing supports native Chromium and Google Chrome with standard launchers")
  if same_workspace:
    for command in ("hyprctl", "jq", "flock", "systemd-run", "uwsm-app"):
      if not shutil.which(command):
        raise ValueError("Missing routing dependency: " + command)
  with settings_lock():
    p = paths()
    current = defaults()
    session_file = p["state"] / "session.json"
    session = read_json(session_file)
    previous_session = dict(session)
    old_config = read_json(p["config"])
    if not session:
      if any(value == DESKTOP_ID for value in current.values()):
        raise ValueError("Missing restore state; choose the real default browser in system settings first")
      session = {"version": 1, "before": current, "last": {}}
      if p["mime"].exists():
        atomic_write(p["state"] / "mimeapps.list.before", p["mime"].read_text())
    # Preserve the saved restore command outside the plugin checkout. Removing
    # or hot-reloading the panel never makes the OS URL handler disappear.
    install_runtime(app)
    desired = DESKTOP_ID if same_workspace else browser_id
    session["last"] = {mime: desired for mime in MIME_TYPES}
    write_json(session_file, session)
    write_json(p["config"], {"version": 1, "browser": browser_id, "same_workspace": same_workspace})
    changed = []
    try:
      for mime in MIME_TYPES:
        changed.append(mime)
        set_default(mime, desired)
    except Exception:
      for mime in reversed(changed):
        if run("xdg-mime", "query", "default", mime) == desired:
          set_default(mime, current[mime])
      if old_config:
        write_json(p["config"], old_config)
      else:
        p["config"].unlink(missing_ok=True)
      if previous_session:
        write_json(session_file, previous_session)
      else:
        session_file.unlink(missing_ok=True)
      raise
  return status()


def restore():
  with settings_lock():
    p = paths()
    session_file = p["state"] / "session.json"
    session = read_json(session_file)
    if not session:
      return status()
    current = defaults()
    for mime in MIME_TYPES:
      # A subsequent selection in another settings app belongs to the user.
      if current[mime] == session.get("last", {}).get(mime):
        previous = session["before"][mime]
        if previous:
          get_app(previous)
        set_default(mime, previous)
    p["config"].unlink(missing_ok=True)
    session_file.unlink()
  return status()


def uninstall():
  restore()
  p = paths()
  if DESKTOP_ID in defaults().values():
    raise RuntimeError("The routing handler is still a default; select a real browser before uninstalling")
  p["desktop"].unlink(missing_ok=True)
  for name in ("omarchy-launch-browser-settings", "omarchy-setup-browser-settings"):
    (p["bin"] / name).unlink(missing_ok=True)
  for name in ("browser_settings.py", "workspace-router"):
    (p["runtime"] / name).unlink(missing_ok=True)
  if p["runtime"].exists() and not any(p["runtime"].iterdir()):
    p["runtime"].rmdir()
  run("update-desktop-database", str(p["desktop"].parent))
  return {"uninstalled": True, "defaults": defaults()}


def open_urls(arguments):
  if arguments and arguments[0] == "--":
    arguments = arguments[1:]
  if arguments in (["--help"], ["-h"]):
    print("Usage: omarchy-launch-browser-settings [--new-window|--private] [URL...]")
    return
  config = read_json(paths()["config"])
  browser_id = config.get("browser")
  if not browser_id:
    raise ValueError("No browser selected. Open Browser Settings and click Apply.")
  app = get_app(browser_id)
  selected_adapter = adapter(app)
  if config.get("same_workspace"):
    if not selected_adapter:
      raise ValueError("The selected browser launcher changed. Apply Browser Settings again.")
    env = dict(os.environ)
    env["OMARCHY_ROUTER_EXECUTABLE"] = selected_adapter["executable"]
    env["OMARCHY_ROUTER_CLASS"] = selected_adapter["class"]
    router = str(Path(__file__).resolve().parent / "workspace-router")
    os.execve(router, [router, *arguments], env)
  else:
    # Normal mode normally bypasses this handler entirely through XDG. Keep a
    # queued request or manually invoked handler useful after switching modes.
    if any(value.startswith("-") for value in arguments):
      raise ValueError("Browser options are available only in current-workspace mode")
    app.launch_uris(arguments, None)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  sub = parser.add_subparsers(dest="action", required=True)
  sub.add_parser("status")
  change = sub.add_parser("apply")
  change.add_argument("--browser", required=True)
  change.add_argument("--workspace", action="store_true")
  sub.add_parser("restore")
  sub.add_parser("uninstall")
  opener = sub.add_parser("open", add_help=False)
  opener.add_argument("urls", nargs=argparse.REMAINDER)
  args = parser.parse_args()
  try:
    if args.action == "open":
      open_urls(args.urls)
      return 0
    if args.action == "apply":
      result = apply(args.browser, args.workspace)
    elif args.action == "restore":
      result = restore()
    elif args.action == "uninstall":
      result = uninstall()
    else:
      result = status()
    print(json.dumps(result, ensure_ascii=False))
    return 0
  except Exception as error:
    message = str(error)
    print(json.dumps({"error": message}), file=sys.stderr)
    if args.action == "open" and shutil.which("notify-send"):
      subprocess.run(["notify-send", "Browser Settings", message], check=False)
    return 1


if __name__ == "__main__":
  sys.exit(main())
