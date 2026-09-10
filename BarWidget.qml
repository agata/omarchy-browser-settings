import QtQuick
import Quickshell
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.agata.browser-settings"
  implicitWidth: browserButton.implicitWidth
  implicitHeight: browserButton.implicitHeight

  WidgetButton {
    id: browserButton
    anchors.fill: parent
    bar: root.bar
    text: "󰖟"
    tooltipText: "Browser Settings"
    onPressed: function(button) {
      if (button === Qt.LeftButton)
        Quickshell.execDetached(["omarchy-shell", "shell", "toggle", root.moduleName, "{}"])
    }
  }
}
