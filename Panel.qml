import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons

Item {
  id: root
  property var shell: null
  property var manifest: null
  property bool opened: false
  property var browserState: ({ browsers: [], can_restore: false })
  property string selectedId: ""
  property bool workspaceMode: false
  property string operation: ""
  property string feedback: ""
  property bool failed: false
  property string stdoutText: ""
  property string stderrText: ""
  property bool stdoutDone: false
  property bool stderrDone: false
  property bool exitSeen: false
  property int commandExitCode: 0

  readonly property bool busy: operation !== ""
  readonly property var selected: {
    for (let browser of browserState.browsers || [])
      if (browser.id === selectedId) return browser
    return null
  }
  readonly property bool workspaceSupported: selected !== null && selected.workspace_supported
  readonly property string backend: manifest && manifest.__sourceDir
    ? String(manifest.__sourceDir) + "/lib/browser_settings.py"
    : decodeURIComponent(Qt.resolvedUrl("lib/browser_settings.py").toString().replace(/^file:\/\//, ""))

  function open(payloadJson) {
    opened = true
    if (!busy) execute("status", [])
    Qt.callLater(function() { card.forceActiveFocus() })
  }

  function close() { opened = false }

  function dismiss() {
    if (busy) return
    if (shell && typeof shell.hide === "function")
      shell.hide("io.github.agata.browser-settings")
    else close()
  }

  function execute(action, extraArgs) {
    if (busy) return
    operation = action
    failed = false
    feedback = action === "status" ? "" : "Applying your preference…"
    stdoutText = ""
    stderrText = ""
    stdoutDone = false
    stderrDone = false
    exitSeen = false
    worker.command = ["/usr/bin/python3", backend, action].concat(extraArgs)
    worker.running = true
  }

  function finishCommand() {
    if (!exitSeen || !stdoutDone || !stderrDone) return
    let action = operation
    operation = ""
    if (commandExitCode !== 0) {
      failed = true
      try { feedback = JSON.parse(stderrText).error || stderrText }
      catch (error) { feedback = stderrText || "Unable to update the browser preference." }
      return
    }
    try {
      browserState = JSON.parse(stdoutText)
      selectedId = browserState.selected || ""
      workspaceMode = browserState.same_workspace === true
      feedback = action === "apply" ? "Saved. New links will use this preference."
        : action === "restore" ? "Previous defaults restored. Later changes were kept." : ""
    } catch (error) {
      failed = true
      feedback = "Unable to read the browser settings."
    }
  }

  function applySelection() {
    if (!selected) return
    let extraArgs = ["--browser", selectedId]
    if (workspaceMode && workspaceSupported) extraArgs.push("--workspace")
    execute("apply", extraArgs)
  }

  Process {
    id: worker
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.stdoutText = text
        root.stdoutDone = true
        root.finishCommand()
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.stderrText = text
        root.stderrDone = true
        root.finishCommand()
      }
    }
    onExited: function(exitCode, exitStatus) {
      root.commandExitCode = exitCode
      root.exitSeen = true
      root.finishCommand()
    }
  }

  PanelWindow {
    id: window
    visible: root.opened
    color: "transparent"
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-browser-settings"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    Rectangle { anchors.fill: parent; color: "#88000000" }
    MouseArea { anchors.fill: parent; onClicked: root.dismiss() }

    Rectangle {
      id: card
      width: Math.min(640, window.width - 40)
      height: Math.min(content.implicitHeight + 56, window.height - 40)
      anchors.centerIn: parent
      color: Color.popups.background
      border.color: Color.popups.border
      border.width: 1
      radius: 14
      focus: true
      Keys.onEscapePressed: root.dismiss()

      MouseArea { anchors.fill: parent }
      ColumnLayout {
        id: content
        anchors { fill: parent; margins: 28 }
        spacing: 18

        RowLayout {
          Layout.fillWidth: true
          ColumnLayout {
            spacing: 5
            Text {
              text: "Browser Settings"
              color: Color.foreground
              font { family: Style.font.family; pixelSize: 26; bold: true }
            }
            Text {
              text: "Choose where your links open."
              color: Color.muted
              font { family: Style.font.family; pixelSize: 14 }
            }
          }
          Item { Layout.fillWidth: true }
          Controls.Button {
            text: "×"
            enabled: !root.busy
            flat: true
            font.pixelSize: 24
            onClicked: root.dismiss()
            palette.buttonText: Color.foreground
          }
        }

        Text {
          text: "DEFAULT BROWSER"
          color: Color.muted
          font { family: Style.font.family; pixelSize: 11; letterSpacing: 1.5; bold: true }
        }

        Controls.ScrollView {
          Layout.fillWidth: true
          Layout.preferredHeight: Math.min(browserRows.implicitHeight, 280)
          clip: true
          contentWidth: availableWidth
          Column {
            id: browserRows
            width: parent.width
            spacing: 8
            Repeater {
              model: root.browserState.browsers || []
              delegate: Controls.AbstractButton {
                id: choice
                required property var modelData
                width: browserRows.width
                height: 58
                enabled: !root.busy
                checked: root.selectedId === modelData.id
                onClicked: {
                  root.selectedId = modelData.id
                  if (!root.workspaceSupported) root.workspaceMode = false
                  root.feedback = ""
                }
                background: Rectangle {
                  radius: 8
                  color: choice.checked ? Qt.alpha(Color.accent, 0.12)
                    : choice.hovered ? Qt.alpha(Color.foreground, 0.05) : "transparent"
                  border.width: 1
                  border.color: choice.checked || choice.activeFocus ? Color.accent : Qt.alpha(Color.foreground, 0.15)
                }
                contentItem: RowLayout {
                  spacing: 12
                  Item { Layout.preferredWidth: 4 }
                  Image {
                    source: Quickshell.iconPath(choice.modelData.icon)
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                    sourceSize: Qt.size(56, 56)
                  }
                  Text {
                    text: choice.modelData.name
                    textFormat: Text.PlainText
                    color: Color.foreground
                    font { family: Style.font.family; pixelSize: 16 }
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                  }
                  Rectangle {
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    radius: 9
                    color: "transparent"
                    border.width: 2
                    border.color: choice.checked ? Color.accent : Color.muted
                    Rectangle {
                      anchors.centerIn: parent
                      width: 8; height: 8; radius: 4
                      visible: choice.checked
                      color: Color.accent
                    }
                  }
                  Item { Layout.preferredWidth: 4 }
                }
              }
            }
            Text {
              visible: !root.busy && (root.browserState.browsers || []).length === 0
              text: "No installed web browsers were found."
              color: Color.muted
              font.family: Style.font.family
            }
          }
        }

        Rectangle {
          Layout.fillWidth: true
          implicitHeight: optionContent.implicitHeight + 28
          radius: 8
          color: Qt.alpha(Color.foreground, 0.035)
          ColumnLayout {
            id: optionContent
            anchors { fill: parent; margins: 14 }
            spacing: 6
            Controls.Switch {
              id: workspaceSwitch
              Layout.fillWidth: true
              text: "Open links on the current workspace"
              enabled: !root.busy && root.workspaceSupported
              checked: root.workspaceMode && root.workspaceSupported
              onClicked: root.workspaceMode = checked
              font { family: Style.font.family; pixelSize: 14; bold: true }
              palette.windowText: Color.foreground
              palette.highlight: Color.accent
            }
            Text {
              Layout.fillWidth: true
              text: root.workspaceSupported
                ? "Reuse a browser window here, or open a new one if needed."
                : "Available for native Chromium and Google Chrome."
              wrapMode: Text.WordWrap
              color: Color.muted
              font { family: Style.font.family; pixelSize: 13 }
            }
          }
        }

        Text {
          Layout.fillWidth: true
          visible: root.browserState.mixed_defaults === true && root.feedback === ""
          text: "HTTP, HTTPS and HTML currently use different apps. Apply sets all three."
          wrapMode: Text.WordWrap
          color: Color.muted
          font { family: Style.font.family; pixelSize: 12 }
        }

        Text {
          Layout.fillWidth: true
          visible: root.feedback !== ""
          text: root.feedback
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          color: root.failed ? Color.urgent : Color.accent
          font { family: Style.font.family; pixelSize: 13 }
        }

        RowLayout {
          Layout.fillWidth: true
          Controls.Button {
            text: "Restore previous defaults"
            flat: true
            enabled: !root.busy && root.browserState.can_restore === true
            onClicked: root.execute("restore", [])
            palette.buttonText: Color.foreground
          }
          Item { Layout.fillWidth: true }
          Controls.Button {
            text: root.busy ? "Please wait…" : "Apply"
            enabled: !root.busy && root.selected !== null
            highlighted: true
            onClicked: root.applySelection()
            palette.highlight: Color.accent
            palette.highlightedText: Color.background
            Layout.preferredWidth: 112
          }
        }
      }
    }
  }
}
