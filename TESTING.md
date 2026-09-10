# Validation for 0.1.0

Validated on September 11, 2026, on Omarchy 4.0.0.alpha / Quattro,
Hyprland 0.56.2, native Wayland Chromium 152.0.7977.82 and
Google Chrome 152.0.7977.82.

## Automated checks

- 32 isolated Python unittest cases: 17 routing cases and 15 settings cases.
- Bash syntax checks for the management command and router.
- `omarchy plugin validate .` for the manifest and entry points.
- `qmllint -I /usr/share/omarchy/shell Panel.qml BarWidget.qml`.

The settings tests use real GIO and XDG tools with temporary user directories,
including a home directory containing spaces. They cover normal selection,
workspace-mode registration, restoration, external preference changes, partial
write rollback, removal, and continued operation after the UI checkout is gone.
The routing tests use fake compositor and process-launch commands to exercise
failure handling, special workspaces, grouping and concurrent requests.

GitHub Actions runs the isolated test suite on Ubuntu with PyGObject and XDG
tools. It does not run a Wayland compositor or a real browser.

## Live desktop checks

For both Chromium and Google Chrome, temporary browser profiles and otherwise
empty workspaces were used to verify:

1. With a browser open elsewhere and no browser on the caller's workspace,
   opening a link creates a window on the caller's workspace.
2. When a matching window exists on the caller's workspace, it is reused even
   after a browser on another workspace was the last active browser.
3. With multiple matching local windows, the first one returned by Hyprland is
   selected.
4. Pre-existing windows retain their workspace assignments.

An additional check used the installed default desktop handler, `xdg-open`, and
Omarchy's `BROWSER=omarchy-launch-browser` environment. Chromium both created a
new local window and reused it on a subsequent request.

The installed QML panel was checked in the desktop shell: browser discovery,
workspace switch, Apply, Restore previous defaults, keyboard activation and
Escape dismissal. The final panel was inspected in a captured screenshot.

## Boundaries

These checks do not establish compatibility with multiple browser profiles,
mixed normal/incognito windows, arbitrary launcher flags or every compositor
version. Routing remains a focus-based workaround with the limitations in the
README. Tests were performed on one physical monitor; multi-monitor workspace
selection is covered by the routing logic, not a live dual-monitor run.
