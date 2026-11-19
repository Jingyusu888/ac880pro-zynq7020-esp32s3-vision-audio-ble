import 'dart:convert';

/// AC880 视觉姿态帧：UDP 9000 单包 JSON，经 ESP32-S3 的 NUS TX Notify 原样透传。
/// 字段契约见 MIGRATION_GUIDE_FOR_APP_AND_ESP32.md §二。
/// 注意：JSON 不携带 RTC epoch，receivedAt 取 App 收到 Notify 当下的手机本地时间。
class VisionFrame {
  final int seq;
  final bool valid;
  final String cls; // CAT / DOG / NONE
  final double score; // 目标检测置信度 0..1（不是旧版的情绪置信度/门槛）
  final String pose; // STD / SIT / LIE / UNK（已过 3 帧多数投票）
  final String raw; // 单帧未平滑姿态，留作调试
  final int kptCnt;
  final List<int> box; // 1280x720 画面坐标 [x1,y1,x2,y2]
  final double ms; // 板端本帧耗时（毫秒）
  final DateTime receivedAt;

  const VisionFrame({
    required this.seq,
    required this.valid,
    required this.cls,
    required this.score,
    required this.pose,
    required this.raw,
    required this.kptCnt,
    required this.box,
    required this.ms,
    required this.receivedAt,
  });

  /// 容错解析：单包 JSON 损坏、半包或字段类型异常时丢弃该帧，不影响后续推流。
  static VisionFrame? parse(List<int> bytes, {DateTime? now}) {
    try {
      final text = utf8.decode(bytes, allowMalformed: false);
      final decoded = jsonDecode(text);
      if (decoded is! Map) return null;
      final m = decoded;
      return VisionFrame(
        seq: _asInt(m['seq']),
        valid: _asInt(m['valid']) == 1,
        cls: (m['cls'] as String?) ?? 'NONE',
        score: _asDouble(m['score']),
        pose: (m['pose'] as String?) ?? 'UNK',
        raw: (m['raw'] as String?) ?? 'UNK',
        kptCnt: _asInt(m['kpt_cnt']),
        box: m['box'] is List
            ? (m['box'] as List).map(_asInt).toList(growable: false)
            : const [0, 0, 0, 0],
        ms: _asDouble(m['ms']),
        receivedAt: now ?? DateTime.now(),
      );
    } catch (_) {
      return null;
    }
  }

  static int _asInt(dynamic v) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    return int.tryParse(v?.toString() ?? '') ?? 0;
  }

  static double _asDouble(dynamic v) {
    if (v is num) return v.toDouble();
    return double.tryParse(v?.toString() ?? '') ?? 0.0;
  }
}

/// 本地历史记录。主键 = 收到时刻(ms) + seq 复合，避免 ESP32 / AC880 重启后
/// seq 归零覆盖既有历史（迁移指南 §二 把 seq 描述为「递增帧号」但并未承诺全局唯一）。
/// 写入策略：仅 valid==1 且「pose 变化 或 距上次写入 >5s」时落一条（§三 2）。
class VisionRecord {
  final String id;
  final int seq;
  final DateTime at;
  final String cls;
  final String pose;
  final double score;
  final int kptCnt;
  final double ms;

  const VisionRecord({
    required this.id,
    required this.seq,
    required this.at,
    required this.cls,
    required this.pose,
    required this.score,
    required this.kptCnt,
    required this.ms,
  });

  factory VisionRecord.fromFrame(VisionFrame f) => VisionRecord(
        id: '${f.receivedAt.millisecondsSinceEpoch}_${f.seq}',
        seq: f.seq,
        at: f.receivedAt,
        cls: f.cls,
        pose: f.pose,
        score: f.score,
        kptCnt: f.kptCnt,
        ms: f.ms,
      );

  Map<String, Object?> toMap() => {
        'id': id,
        'seq': seq,
        'at_ms': at.millisecondsSinceEpoch,
        'cls': cls,
        'pose': pose,
        'score': score,
        'kpt_cnt': kptCnt,
        'ms': ms,
      };

  factory VisionRecord.fromMap(Map<String, Object?> m) => VisionRecord(
        id: m['id'] as String,
        seq: m['seq'] as int,
        at: DateTime.fromMillisecondsSinceEpoch(m['at_ms'] as int),
        cls: m['cls'] as String,
        pose: m['pose'] as String,
        score: (m['score'] as num).toDouble(),
        kptCnt: m['kpt_cnt'] as int,
        ms: (m['ms'] as num).toDouble(),
      );
}
