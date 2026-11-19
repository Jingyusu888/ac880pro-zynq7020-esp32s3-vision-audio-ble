import 'dart:async';
import 'dart:io';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';

import '../models/vision_frame.dart';
import 'protocol.dart';

enum BleConnectionState { disconnected, connecting, connected }

/// 扫描失败原因：连接弹层据此给出可操作的提示，而不是笼统的「未搜索到设备」。
enum ScanFailureReason { bluetoothOff, permissionDenied, unknown }

class ScanFailure implements Exception {
  final ScanFailureReason reason;
  final String message;
  const ScanFailure(this.reason, this.message);

  @override
  String toString() => message;
}

/// 路线 A BLE 连接管理：扫描 NUS 服务 → 连接 → 请求 MTU 256 → 订阅 TX Notify。
/// 旧版 TIME / CURSOR / CTRL / STATUS 依赖已全部移除（迁移指南 §三 1）。
/// 连接状态只来自真实 GATT 断连事件（红线 D5），绝不硬编码「已连接」。
class BleService {
  /// 名称仅用于展示/兜底；识别以 128-bit 服务 UUID 为准。
  static const List<String> acceptedNames = ['Petlink-ESP32S3'];

  static String _uuidKey(String s) => s.toLowerCase().replaceAll('-', '');
  static final String _serviceKey = _uuidKey(Protocol.serviceUuid);

  BleConnectionState _state = BleConnectionState.disconnected;
  BleConnectionState get state => _state;

  BluetoothDevice? _device;
  BluetoothCharacteristic? _tx;
  StreamSubscription<List<int>>? _txSub;
  StreamSubscription<BluetoothConnectionState>? _connSub;
  DateTime? _lastFrameAt;

  /// 最近一帧到达时刻，用于「连接正常但板端未推流」的 6s 判定。
  DateTime? get lastFrameAt => _lastFrameAt;

  final _stateCtl = StreamController<BleConnectionState>.broadcast();
  final _frameCtl = StreamController<VisionFrame>.broadcast();

  Stream<BleConnectionState> get stateStream => _stateCtl.stream;
  Stream<VisionFrame> get frameStream => _frameCtl.stream;

  /// 服务 UUID 优先、名称兜底。广播名与文档不一致时仍能识别设备。
  bool _isPetLink(ScanResult r) {
    final byUuid = r.advertisementData.serviceUuids
        .any((g) => _uuidKey(g.toString()) == _serviceKey);
    if (byUuid) return true;
    final n = _nameOf(r).toLowerCase();
    if (n.isEmpty) return false;
    return acceptedNames.any((a) => n == a.toLowerCase()) ||
        n.startsWith('petlink');
  }

  /// 扫描并按服务 UUID 识别设备；按 remoteId 去重、保留最强信号。
  Future<List<ScanResult>> scan(
      {Duration timeout = const Duration(seconds: 15)}) async {
    // ① 适配器状态：蓝牙关着/未授权时 startScan 只会静默返回空列表。
    final adapter = await FlutterBluePlus.adapterState.first.timeout(
      const Duration(seconds: 5),
      onTimeout: () => BluetoothAdapterState.unknown,
    );
    if (adapter == BluetoothAdapterState.unauthorized) {
      throw const ScanFailure(ScanFailureReason.permissionDenied,
          '系统未授予蓝牙权限，请到「设置 → 应用权限」开启「附近的设备」。');
    }
    if (adapter != BluetoothAdapterState.on) {
      throw ScanFailure(ScanFailureReason.bluetoothOff,
          '手机蓝牙未开启（当前状态：${adapter.name}），请先打开蓝牙再搜索。');
    }

    // ② Android 12+ 运行时权限，申请结果必须回传。
    if (Platform.isAndroid) {
      try {
        final req = await [
          Permission.bluetoothScan,
          Permission.bluetoothConnect,
        ].request();
        final denied = req.values
            .where((s) => s.isDenied || s.isPermanentlyDenied)
            .length;
        if (denied == req.length) {
          throw const ScanFailure(ScanFailureReason.permissionDenied,
              '蓝牙权限被拒绝：请到「设置 → 应用权限」允许「附近的设备」。');
        }
      } on ScanFailure {
        rethrow;
      } catch (_) {
        // 插件异常时继续，清单声明兜底
      }
    }

    // ③ 累积式收集，不依赖 scanResults 是否为累积列表。
    final byId = <String, ScanResult>{};
    final done = Completer<void>();
    StreamSubscription<List<ScanResult>>? sub;
    try {
      sub = FlutterBluePlus.scanResults.listen((list) {
        for (final r in list) {
          if (!_isPetLink(r)) continue;
          final id = r.device.remoteId.toString();
          final prev = byId[id];
          if (prev == null || r.rssi > prev.rssi) byId[id] = r;
        }
      });
      await FlutterBluePlus.startScan(timeout: timeout);
      FlutterBluePlus.isScanning.where((s) => s == false).first.then((_) {
        if (!done.isCompleted) done.complete();
      });
      await done.future.timeout(
        timeout + const Duration(seconds: 5),
        onTimeout: () {},
      );
    } finally {
      await sub?.cancel();
      if (FlutterBluePlus.isScanningNow) {
        await FlutterBluePlus.stopScan();
      }
    }
    return byId.values.toList()..sort((a, b) => b.rssi.compareTo(a.rssi));
  }

  String _nameOf(ScanResult r) => r.device.platformName.isNotEmpty
      ? r.device.platformName
      : r.advertisementData.advName;

  Future<void> connect(BluetoothDevice device) async {
    _state = BleConnectionState.connecting;
    _stateCtl.add(_state);
    _device = device;
    _lastFrameAt = null;

    // 真实 GATT 断连事件 → 驱动 UI 进入「已断开」（红线 D5）。
    _connSub?.cancel();
    _connSub = device.connectionState.listen((s) {
      if (s == BluetoothConnectionState.disconnected) {
        _state = BleConnectionState.disconnected;
        _stateCtl.add(_state);
      }
    });

    // mtu: 256 由插件在连接后自动向板端请求（单包 JSON <=130 B，一帧收完）。
    await device.connect(mtu: Protocol.mtu, timeout: const Duration(seconds: 15));

    final services = await device.discoverServices();
    final svc = services.firstWhere(
      (s) => s.uuid == Guid(Protocol.serviceUuid),
      orElse: () => throw Exception('未找到 Nordic UART 服务（6E400001）'),
    );
    _tx = svc.characteristics.firstWhere(
      (c) => c.uuid == Guid(Protocol.uuidTx),
      orElse: () => throw Exception('未找到 NUS TX Notify 特征（6E400003）'),
    );

    // 迁移指南 §三 1：连接流程精简为「扫描 → 连接 → MTU → 订阅 TX」。
    // 不探测 0002/0003/0005/0006，缺失时不报错、不卡死。
    await _tx!.setNotifyValue(true);
    await _txSub?.cancel();
    _txSub = _tx!.onValueReceived.listen((v) {
      final frame = Protocol.parseFrame(v);
      if (frame == null) return; // 坏帧丢弃，不影响后续推流
      _lastFrameAt = DateTime.now();
      _frameCtl.add(frame);
    });

    _state = BleConnectionState.connected;
    _stateCtl.add(_state);
  }

  Future<void> disconnect() async {
    try {
      await _device?.disconnect();
    } catch (_) {
      // 忽略断开异常
    }
    await _txSub?.cancel();
    await _connSub?.cancel();
    _txSub = null;
    _connSub = null;
    _device = null;
    _tx = null;
    _lastFrameAt = null;
  }

  void dispose() {
    _txSub?.cancel();
    _connSub?.cancel();
    _stateCtl.close();
    _frameCtl.close();
  }
}
