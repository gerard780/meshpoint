import 'package:flutter/foundation.dart';

/// Which of [HomeShell]'s 5 bottom-nav tabs is showing. A plain
/// provider (not local `State`) so other widgets -- most importantly
/// [MeshpointDetailSheet]'s "Switch to this meshpoint" button -- can
/// jump the user to the Nodes tab from outside the shell itself.
class TabIndexController extends ChangeNotifier {
  int _index = 0;
  int get index => _index;

  void setIndex(int index) {
    if (_index == index) return;
    _index = index;
    notifyListeners();
  }
}
