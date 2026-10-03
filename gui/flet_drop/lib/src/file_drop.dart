import 'package:desktop_drop/desktop_drop.dart';
import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

/// gui/drop.py FileDrop: "enter" and "leave" while files hover, "drop" with their paths.
class FileDropControl extends StatelessWidget {
  final Control control;

  const FileDropControl({super.key, required this.control});

  @override
  Widget build(BuildContext context) {
    final content = control.buildWidget("content") ?? const SizedBox.shrink();
    return LayoutControl(
      control: control,
      child: DropTarget(
        enable: !control.getBool("disabled", false)!,
        onDragEntered: (_) => control.triggerEvent("enter"),
        onDragExited: (_) => control.triggerEvent("leave"),
        onDragDone: (detail) => control.triggerEvent("drop",
            detail.files.map((f) => f.path).where((p) => p.isNotEmpty).toList()),
        child: content,
      ),
    );
  }
}
