import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "lib/browser_settings.py"
spec = importlib.util.spec_from_file_location("browser_settings", BACKEND)
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class SettingsIntegrationTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory(prefix="browser-settings-test-")
    self.addCleanup(self.temp.cleanup)
    # A space exercises both the generated shell wrappers and Desktop Exec.
    self.home = Path(self.temp.name) / "test home"
    self.config = self.home / ".config"
    self.data = self.home / ".local/share"
    self.applications = self.data / "applications"
    self.config.mkdir(parents=True)
    self.applications.mkdir(parents=True)
    self.commands = self.home / "commands"
    self.commands.mkdir()
    for name in ("chromium", "google-chrome-stable", "uwsm-app", "hyprctl"):
      command = self.commands / name
      command.write_text('#!/bin/bash\nexit 0\n')
      command.chmod(0o755)
    self.env = {
      **os.environ, "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.config),
      "XDG_DATA_HOME": str(self.data), "XDG_DATA_DIRS": str(self.home / "system-data"),
      "XDG_CONFIG_DIRS": str(self.home / "system-config"),
      "XDG_STATE_HOME": str(self.home / ".local/state"),
      "XDG_CURRENT_DESKTOP": "Hyprland", "DE": "generic",
      "PATH": str(self.home / '.local/bin') + ":" + str(self.commands) + ":/usr/bin:/bin",
    }
    self.env.pop("BROWSER", None)
    for desktop_id, name, executable in [
      ("original.desktop", "Original browser", "/usr/bin/true"),
      ("alternative.desktop", "Another browser", "/usr/bin/true"),
      ("chromium.desktop", "Chromium", "chromium"),
      ("google-chrome.desktop", "Google Chrome", "google-chrome-stable"),
    ]:
      (self.applications / desktop_id).write_text(
        f'[Desktop Entry]\nType=Application\nName={name}\nExec={executable} %U\n'
        'Categories=Network;WebBrowser;\nMimeType=x-scheme-handler/http;x-scheme-handler/https;text/html;\n'
      )
    self.mime = self.config / "mimeapps.list"
    self.original = '[Default Applications]\n' + ''.join(mime + '=original.desktop\n' for mime in settings.MIME_TYPES)
    self.original += 'text/plain=editor.desktop\n'
    self.mime.write_text(self.original)

  def command(self, *args, success=True):
    result = subprocess.run(args, env=self.env, text=True, capture_output=True, timeout=20)
    if success:
      self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
    else:
      self.assertNotEqual(result.returncode, 0)
    return result

  def backend(self, *args, success=True):
    result = self.command('/usr/bin/python3', str(BACKEND), *args, success=success)
    return json.loads(result.stdout if success else result.stderr)

  def default(self, mime='x-scheme-handler/https'):
    return self.command('xdg-mime', 'query', 'default', mime).stdout.strip()

  def test_status_has_no_setting_side_effects(self):
    state = self.backend('status')
    self.assertEqual(self.mime.read_text(), self.original)
    self.assertFalse((self.home / '.local/state/omarchy/browser-settings').exists())
    self.assertEqual(state['selected'], 'original.desktop')
    self.assertFalse(state['can_restore'])

  def test_browser_capabilities_and_hidden_internal_handler(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    items = {item['id']: item for item in self.backend('status')['browsers']}
    self.assertNotIn(settings.DESKTOP_ID, items)
    self.assertTrue(items['chromium.desktop']['workspace_supported'])
    self.assertTrue(items['google-chrome.desktop']['workspace_supported'])
    self.assertFalse(items['alternative.desktop']['workspace_supported'])

  def test_normal_mode_sets_the_real_browser_directly(self):
    state = self.backend('apply', '--browser', 'alternative.desktop')
    self.assertEqual(set(state['defaults'].values()), {'alternative.desktop'})
    self.assertFalse(state['same_workspace'])
    self.assertIn('text/plain=editor.desktop', self.mime.read_text())

  def test_equivalent_local_bin_path_from_shell_environment(self):
    self.env['PATH'] = str(self.data / '../bin') + ':' + str(self.commands) + ':/usr/bin:/bin'
    state = self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    self.assertTrue(state['same_workspace'])

  def test_workspace_mode_installs_valid_independent_handler(self):
    state = self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    self.assertEqual(set(state['defaults'].values()), {settings.DESKTOP_ID})
    self.assertTrue(state['same_workspace'])
    self.command('desktop-file-validate', str(self.applications / settings.DESKTOP_ID))
    output = self.command(str(self.home / '.local/bin/omarchy-launch-browser-settings'), '--help').stdout
    self.assertIn('Usage:', output)
    self.assertEqual(self.command('xdg-settings', 'check', 'default-web-browser', settings.DESKTOP_ID).stdout.strip(), 'yes')

  def test_unsupported_workspace_mode_does_not_change_defaults(self):
    result = self.backend('apply', '--browser', 'alternative.desktop', '--workspace', success=False)
    self.assertIn('supports native Chromium', result['error'])
    self.assertEqual(self.mime.read_text(), self.original)

  def test_custom_profile_launcher_cannot_enable_workspace_mode(self):
    path = self.applications / 'chromium.desktop'
    path.write_text(path.read_text().replace('chromium %U', 'chromium --profile-directory=Work %U'))
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace', success=False)
    self.backend('apply', '--browser', 'chromium.desktop')
    self.assertEqual(self.default(), 'chromium.desktop')

  def test_restore_keeps_first_defaults_across_multiple_applies(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    self.backend('apply', '--browser', 'google-chrome.desktop', '--workspace')
    self.backend('apply', '--browser', 'alternative.desktop')
    self.backend('restore')
    self.assertEqual(self.mime.read_text(), self.original)

  def test_restore_preserves_a_later_external_default_change(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    self.command('xdg-mime', 'default', 'alternative.desktop', 'text/html')
    state = self.backend('restore')
    self.assertEqual(state['defaults']['text/html'], 'alternative.desktop')
    self.assertEqual(state['defaults']['x-scheme-handler/https'], 'original.desktop')

  def test_new_apply_cycle_saves_new_previous_defaults(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    self.backend('restore')
    for mime in settings.MIME_TYPES:
      self.command('xdg-mime', 'default', 'alternative.desktop', mime)
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    self.backend('restore')
    self.assertEqual(self.default(), 'alternative.desktop')

  def test_runtime_and_restore_survive_removing_plugin_checkout(self):
    plugin = self.home / 'plugin'
    shutil.copytree(ROOT / 'lib', plugin / 'lib', ignore=shutil.ignore_patterns('__pycache__'))
    self.command('/usr/bin/python3', str(plugin / 'lib/browser_settings.py'), 'apply', '--browser', 'chromium.desktop', '--workspace')
    shutil.rmtree(plugin)
    self.command(str(self.home / '.local/bin/omarchy-launch-browser-settings'), '--help')
    self.command(str(self.home / '.local/bin/omarchy-setup-browser-settings'), 'restore')
    self.assertEqual(self.default(), 'original.desktop')

  def test_uninstall_removes_runtime_after_restoring_defaults(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    result = self.command(str(self.home / '.local/bin/omarchy-setup-browser-settings'), 'uninstall')
    self.assertTrue(json.loads(result.stdout)['uninstalled'])
    self.assertEqual(self.default(), 'original.desktop')
    self.assertFalse((self.applications / settings.DESKTOP_ID).exists())
    self.assertFalse((self.home / '.local/bin/omarchy-launch-browser-settings').exists())

  def test_missing_previous_browser_blocks_removal_of_active_handler(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    (self.applications / 'original.desktop').unlink()
    self.backend('uninstall', success=False)
    self.assertEqual(self.default(), settings.DESKTOP_ID)
    self.assertTrue((self.home / '.local/bin/omarchy-launch-browser-settings').exists())

  def test_gui_disabled_does_not_overwrite_an_external_browser_choice(self):
    self.backend('apply', '--browser', 'chromium.desktop', '--workspace')
    for mime in settings.MIME_TYPES:
      self.command('xdg-mime', 'default', 'alternative.desktop', mime)
    state = self.backend('status')
    self.assertFalse(state['same_workspace'])
    self.assertEqual(state['selected'], 'alternative.desktop')
    self.backend('uninstall')
    self.assertEqual(self.default(), 'alternative.desktop')


class TransactionTest(unittest.TestCase):
  def test_failed_second_association_rolls_back_and_keeps_original_journal(self):
    with tempfile.TemporaryDirectory() as directory:
      home = Path(directory)
      p = {'config': home / 'config.json', 'mime': home / 'mimeapps.list', 'state': home / 'state'}
      p['state'].mkdir()
      current = {mime: 'old.desktop' for mime in settings.MIME_TYPES}
      values = dict(current)
      calls = []

      def set_default(mime, target):
        calls.append((mime, target))
        values[mime] = target
        if len(calls) == 2:
          raise RuntimeError('Simulated xdg-mime failure after a write')

      with patch.object(settings, 'paths', return_value=p), \
           patch.object(settings, 'get_app', return_value=object()), \
           patch.object(settings, 'browsers', return_value=[{'id': 'new.desktop'}]), \
           patch.object(settings, 'defaults', side_effect=lambda: dict(values)), \
           patch.object(settings, 'install_runtime'), \
           patch.object(settings, 'set_default', side_effect=set_default), \
           patch.object(settings, 'run', side_effect=lambda *args: values[args[-1]]):
        with self.assertRaisesRegex(RuntimeError, 'Simulated'):
          settings.apply('new.desktop')
      self.assertEqual(values, current)
      self.assertFalse(p['config'].exists())
      self.assertFalse((p['state'] / 'session.json').exists())


if __name__ == '__main__':
  unittest.main(verbosity=2)
