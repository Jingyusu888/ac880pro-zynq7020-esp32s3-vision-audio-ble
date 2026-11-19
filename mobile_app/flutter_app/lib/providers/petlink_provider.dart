import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import '../models/vision_frame.dart';
import '../services/ble_service.dart';
import '../services/protocol.dart';
import '../services/storage_service.dart';

/// 中央状态协调器：持有 BleService / StorageService，向 UI 暴露连接态、
/// 最新视觉帧、本地历史与推流心跳。
///
/// 路线 A 后不再有 STATUS/TIME/CURSOR/CTRL：旧版的校时、控制、板端游标同步
/// 全部移除，历史由手机本地按「pose 变化或 >5s」抽稀写入（迁移指南 §三 2）。
class PetlinkProvider extends ChangeNotifier {
  final BleService ble = BleService();
  final StorageService storage = StorageService();

  BleConnectionState get connState => ble.state;
  bool get isConnected => connState == BleConnectionState.connected;

  VisionFrame? latest;
  List<VisionRecord> history = [];
  bool streamStale = false;
  String message = '未连接。点「连接板子」选择 ${Protocol.deviceName}。';

  Timer? _staleTimer;
  DateTime? _lastWriteAt;
  String? _lastWrittenPose;

  Future<void> init() async {
    await storage.init();
    history = await storage.all();

    ble.stateStream.listen((_) => notifyListeners());
    ble.frameStream.listen((f) async {
      await _onFrame(f);
    });

    // 已连接但 >6s 无新帧：只提示「等待板端推流」，不改变真实连接态（红线 D5）。
    _staleTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      final stale = isConnected &&
          (ble.lastFrameAt == null ||
              DateTime.now().difference(ble.lastFrameAt!) >=
                  Protocol.staleAfter);
      if (stale != streamStale) {
        streamStale = stale;
        notifyListeners();
      }
    });

    notifyListeners();
  }

  Future<void> _onFrame(VisionFrame f) async {
    latest = f;
    if (streamStale) streamStale = false;
    notifyListeners();

    if (!f.valid) return; // NONE 空帧：主卡显示待机，但不写历史
    await _maybeWrite(f);
  }

  /// 仅在「姿态变化」或「距上次写入 >5s」时落一条，避免重复帧刷屏。
  Future<void> _maybeWrite(VisionFrame f) async {
    final poseChanged = _lastWrittenPose != f.pose;
    final gap = _lastWriteAt == null ||
        f.receivedAt.difference(_lastWriteAt!) >= Protocol.historyMinGap;
    if (!poseChanged && !gap) return;

    await storage.insert(VisionRecord.fromFrame(f));
    _lastWriteAt = f.receivedAt;
    _lastWrittenPose = f.pose;
    history = await storage.all();
    notifyListeners();
  }

  Future<void> connectDevice(BluetoothDevice device) async {
    try {
      message = '连接中…';
      notifyListeners();
      await ble.connect(device);
      message = '已连接，等待板端推流…';
    } catch (e) {
      message = '连接失败：$e';
    }
    notifyListeners();
  }

  Future<void> disconnect() async {
    await ble.disconnect();
    streamStale = false;
    message = '已断开。历史记录保存在手机本地。';
    notifyListeners();
  }

  Future<String> exportCsv() => storage.exportCsv();

  @override
  void dispose() {
    _staleTimer?.cancel();
    ble.dispose();
    super.dispose();
  }
}
