import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "lib/workspace-router"

FAKE_COMMAND = r'''
import json
import os
from pathlib import Path
import re
import sys

path = Path(os.environ["WORKSPACE_TEST_STATE"])
state = json.loads(path.read_text())
command, *args = sys.argv[1:]

def save():
  temporary = path.with_suffix(".tmp")
  temporary.write_text(json.dumps(state))
  temporary.replace(path)

if command == "notify-send":
  sys.exit(0)
elif command == "systemd-run":
  args = args[args.index("uwsm-app") + 1:]
  state["events"].append({"launch": args, "active": state.get("active")})
  if "--new-window" in args and not state.get("no_new_window"):
    count = state.get("spawn_count", 1)
    for offset in range(count):
      address = "0x" + str(100 + len(state["clients"]))
      state["clients"].append({
        "address": address, "class": "chromium", "mapped": True,
        "workspace": state.get("spawn_workspace", {"id": 2, "name": "2"}),
        "grouped": ["0xa", address] if state.get("spawn_grouped") else []
      })
      state["active"] = address
  save()
elif args[0] == "-j":
  if state.get("ipc_failure"):
    sys.exit(1)
  if args[1] == "clients":
    print(json.dumps(state["clients"]))
  elif args[1] == "monitors":
    print(json.dumps(state["monitors"]))
  elif args[1] == "activewindow":
    print(json.dumps(next((c for c in state["clients"] if c["address"] == state.get("active")), {})))
elif args[0] == "dispatch":
  expression = args[1]
  if state.get("legacy") and expression.startswith("hl."):
    sys.exit(1)
  if "focus" in expression:
    address = re.search(r"address:(0x[0-9a-f]+)", " ".join(args)).group(1)
    state["events"].append({"focus": address})
    if not state.get("focus_failure"):
      state["active"] = address
  elif "move" in expression:
    address = re.search(r"address:(0x[0-9a-f]+)", " ".join(args)).group(1)
    if "out_of_group" in expression or "moveoutofgroup" in expression:
      state["events"].append({"detach": address})
      for client in state["clients"]:
        if client["address"] == address:
          client["grouped"] = []
      save()
      sys.exit(0)
    if expression.startswith("hl."):
      workspace = re.search(r'workspace = ("(?:[^"\\]|\\.)*")', expression).group(1)
      workspace = json.loads(workspace)
    else:
      workspace = args[2].split(",address:")[0]
    state["events"].append({"move": address, "workspace": workspace})
    for client in state["clients"]:
      if client["address"] == address:
        client["workspace"] = {"id": -98 if workspace.startswith("special:") else int(workspace), "name": workspace}
  save()
  print("ok")
'''


def client(address, workspace=2, class_name="chromium", name=None):
  return {
    "address": address, "class": class_name, "mapped": True,
    "workspace": {"id": workspace, "name": name or str(workspace)}
  }


class WorkspaceBrowserTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory(prefix="omarchy-browser-test-")
    self.addCleanup(self.temp.cleanup)
    self.directory = Path(self.temp.name)
    self.state_file = self.directory / "state.json"
    fake = self.directory / "fake.py"
    fake.write_text(FAKE_COMMAND)
    for command in ("hyprctl", "systemd-run", "notify-send"):
      path = self.directory / command
      path.write_text("#!/bin/bash\nexec /usr/bin/python3 " + shlex.quote(str(fake)) + " " + command + ' "$@"\n')
      path.chmod(0o755)
    config = self.directory / "browser.conf"
    config.write_text("browser_command=(/usr/bin/chromium)\nbrowser_class='^[cC]hromium$'\n")
    self.env = {
      **os.environ,
      "PATH": str(self.directory) + ":/usr/bin",
      "WORKSPACE_TEST_STATE": str(self.state_file),
      "OMARCHY_ROUTER_EXECUTABLE": "/usr/bin/chromium",
      "OMARCHY_ROUTER_CLASS": "^[cC]hromium$",
      "XDG_RUNTIME_DIR": str(self.directory),
      "HYPRLAND_INSTANCE_SIGNATURE": "workspace-test",
    }
    self.state = {
      "clients": [client("0xa", class_name="chatgpt")], "active": "0xa",
      "monitors": [{"focused": True, "activeWorkspace": {"id": 2, "name": "2"}, "specialWorkspace": {"id": 0}}],
      "events": [],
    }

  def run_handler(self, *args, success=True):
    self.state_file.write_text(json.dumps(self.state))
    result = subprocess.run([str(HANDLER), *args], env=self.env, text=True, capture_output=True, timeout=20)
    self.state = json.loads(self.state_file.read_text())
    if success:
      self.assertEqual(result.returncode, 0, result.stderr)
    else:
      self.assertNotEqual(result.returncode, 0)
    return result

  def launches(self):
    return [event for event in self.state["events"] if "launch" in event]

  def test_focuses_first_browser_on_same_workspace_and_preserves_urls(self):
    self.state["clients"] += [client("0xb", 3), client("0xc"), client("0xd")]
    urls = ["https://example.com/?a=1&b=$(echo bad)", "https://example.com/a b#fragment"]
    self.run_handler(*urls)
    self.assertEqual(self.launches()[0]["active"], "0xc")
    self.assertEqual(self.launches()[0]["launch"][-2:], urls)
    self.assertNotIn("--new-window", self.launches()[0]["launch"])
    self.assertFalse(any("move" in event for event in self.state["events"]))

  def test_creates_new_window_without_moving_existing_browser(self):
    self.state["clients"].append(client("0xb", 3))
    self.state["spawn_workspace"] = {"id": 3, "name": "3"}
    self.run_handler("https://example.com")
    self.assertIn("--new-window", self.launches()[0]["launch"])
    self.assertEqual(self.state["clients"][1]["workspace"]["id"], 3)
    self.assertEqual(self.state["clients"][-1]["workspace"]["id"], 2)

  def test_special_workspace_is_independent_of_regular_workspace(self):
    self.state["clients"][0] = client("0xa", -98, "chatgpt", "special:chatgpt")
    self.state["clients"] += [client("0xb"), client("0xc", -98, name="special:chatgpt")]
    self.run_handler("https://example.com")
    self.assertEqual(self.launches()[0]["active"], "0xc")

  def test_detaches_only_new_window_before_moving_it(self):
    self.state["spawn_grouped"] = True
    self.state["spawn_workspace"] = {"id": 3, "name": "3"}
    self.run_handler("https://example.com")
    new_address = self.state["clients"][-1]["address"]
    detach = next(i for i, event in enumerate(self.state["events"]) if event.get("detach") == new_address)
    move = next(i for i, event in enumerate(self.state["events"]) if event.get("move") == new_address)
    self.assertLess(detach, move)

  def test_new_window_is_placed_in_special_workspace(self):
    self.state["clients"][0] = client("0xa", -98, "chatgpt", "special:chatgpt")
    self.run_handler("https://example.com")
    self.assertEqual(self.state["clients"][-1]["workspace"]["name"], "special:chatgpt")

  def test_empty_special_workspace_uses_focused_monitor(self):
    self.state["active"] = None
    self.state["monitors"][0]["specialWorkspace"] = {"id": -98, "name": "special:chatgpt"}
    self.run_handler("https://example.com")
    self.assertEqual(self.state["clients"][-1]["workspace"]["id"], -98)

  def test_no_arguments_only_focus_existing_window(self):
    self.state["clients"].append(client("0xb"))
    self.run_handler()
    self.assertEqual(self.state["active"], "0xb")
    self.assertEqual(self.launches(), [])

  def test_private_request_creates_new_window(self):
    self.state["clients"].append(client("0xb"))
    self.run_handler("--private", "https://example.com")
    self.assertIn("--incognito", self.launches()[0]["launch"])
    self.assertIn("--new-window", self.launches()[0]["launch"])

  def test_explicit_new_window_does_not_reuse_local_browser(self):
    self.state["clients"].append(client("0xb"))
    self.run_handler("--new-window", "https://example.com")
    self.assertIn("--new-window", self.launches()[0]["launch"])

  def test_web_apps_and_devtools_are_not_selected(self):
    self.state["clients"] += [client("0xb", class_name="chrome-chatgpt.com__-Default"), client("0xc")]
    self.state["clients"][-1]["title"] = "DevTools - example.com"
    self.run_handler("https://example.com")
    self.assertIn("--new-window", self.launches()[0]["launch"])

  def test_failed_focus_does_not_send_url_to_another_workspace(self):
    self.state["clients"].append(client("0xb"))
    self.state["focus_failure"] = True
    self.run_handler("https://example.com", success=False)
    self.assertEqual(self.launches(), [])

  def test_ambiguous_new_windows_are_not_moved(self):
    self.state["spawn_count"] = 2
    self.run_handler("https://example.com", success=False)
    self.assertFalse(any("move" in event for event in self.state["events"]))

  def test_hyprland_connection_failure_does_not_route_blindly(self):
    self.state["ipc_failure"] = True
    self.run_handler("https://example.com", success=False)
    self.assertEqual(self.launches(), [])

  def test_outside_hyprland_uses_real_browser(self):
    self.env.pop("HYPRLAND_INSTANCE_SIGNATURE")
    self.state["ipc_failure"] = True
    self.run_handler("https://example.com")
    self.assertEqual(len(self.launches()), 1)

  def test_legacy_hyprland_dispatchers(self):
    self.state["legacy"] = True
    self.state["spawn_workspace"] = {"id": 3, "name": "3"}
    self.run_handler("https://example.com")
    self.assertEqual(self.state["clients"][-1]["workspace"]["id"], 2)

  def test_concurrent_links_reuse_the_first_new_window(self):
    self.state_file.write_text(json.dumps(self.state))
    jobs = [subprocess.Popen([str(HANDLER), "https://example.com/" + str(i)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(3)]
    for job in jobs:
      _, error = job.communicate(timeout=20)
      self.assertEqual(job.returncode, 0, error)
    self.state = json.loads(self.state_file.read_text())
    self.assertEqual(len(self.launches()), 3)
    self.assertEqual(sum("--new-window" in event["launch"] for event in self.launches()), 1)

  def test_help_does_not_launch_browser(self):
    self.run_handler("--help")
    self.assertEqual(self.launches(), [])


if __name__ == "__main__":
  unittest.main(verbosity=2)
