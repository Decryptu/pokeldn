import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

import 'file_drop.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    switch (control.type) {
      case "FileDrop":
        return FileDropControl(key: key, control: control);
      default:
        return null;
    }
  }
}
