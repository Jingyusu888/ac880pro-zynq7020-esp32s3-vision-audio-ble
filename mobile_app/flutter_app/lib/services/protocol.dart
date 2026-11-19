import '../models/vision_frame.dart';

/// 路线 A 视觉姿态链路（MIGRATION_GUIDE_FOR_APP_AND_ESP32.md §二 / §三）：
///   AC880 --UDP:9000 单包 JSON--> ESP32-S3 --BLE NUS TX Notify--> PetLink App
///
/// 与旧版 PLKMONITOR（504c4b4d-... / REC 20B / TIME·CURSOR·CTRL·STATUS）已完全替换：
/// 不再校时、不再读板端游标、不再下发控制指令。
class Protocol {
  /// Nordic UART Service。ESP32-S3 广播包携带此 128-bit UUID，扫描以它为准。
  static const String serviceUuid = '6E400001-B5A3-F393-E0A9-E50E24DCCA9E';

  /// TX Notify：UTF-8 JSON 字符串，单包 <= 130 B。
  static const String uuidTx = '6E400003-B5A3-F393-E0A9-E50E24DCCA9E';

  static const String deviceName = 'Petlink-ESP32S3';

  /// 连接后向板端请求 256，保证单帧 JSON 一包收完、不粘包。
  static const int mtu = 256;

  /// 已连接但超过 6s 未收到新帧 → 显示「等待板端推流」，但不伪造断开（红线 D5）。
  static const Duration staleAfter = Duration(seconds: 6);

  /// 历史抽稀：pose 未变化时至少间隔 5s 才写一条。
  static const Duration historyMinGap = Duration(seconds: 5);

  static VisionFrame? parseFrame(List<int> bytes) => VisionFrame.parse(bytes);

  static String _p2(int n) => n.toString().padLeft(2, '0');

  /// 时间统一取手机本地时间字段（JSON 无 epoch，不再做 UTC 墙钟换算）。
  static String formatDay(DateTime t) =>
      '${t.year}-${_p2(t.month)}-${_p2(t.day)}';

  static String formatHms(DateTime t) =>
      '${_p2(t.hour)}:${_p2(t.minute)}:${_p2(t.second)}';

  /// 板端帧耗时 ms → 「2.6s」。
  static String formatMs(double ms) => '${(ms / 1000).toStringAsFixed(1)}s';
}
