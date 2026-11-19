import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/vision_frame.dart';
import '../providers/petlink_provider.dart';
import '../services/protocol.dart';
import '../theme/app_theme.dart';
import '../utils/pose_labels.dart';
import '../widgets/common.dart';
import '../widgets/connect_sheet.dart';
import '../widgets/pose_card.dart';

/// 实时页（首页）：连接状态条 + 姿态 Hero + 今日概览 + 合规注脚。
/// 路线 A 后无 CTRL 通道，原控制区已移除。
class LiveScreen extends StatelessWidget {
  const LiveScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = Provider.of<PetlinkProvider>(context);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
      children: [
        ConnectionStrip(
          connected: p.isConnected,
          name: Protocol.deviceName,
          onTap: () => showConnectSheet(context),
        ),
        const SizedBox(height: 16),
        PoseCard(
          frame: p.latest,
          connected: p.isConnected,
          stale: p.streamStale,
        ),
        const SizedBox(height: 18),
        _TodayOverview(records: p.history, frame: p.latest),
        const LegalNote(),
        const SizedBox(height: 4),
        Text(p.message,
            style: const TextStyle(fontSize: 11, color: AppColors.muted2)),
      ],
    );
  }
}

/// 今日概览：今日识别次数 / 主要姿态占比（站·坐·卧）/ 最近同步耗时。
class _TodayOverview extends StatelessWidget {
  final List<VisionRecord> records;
  final VisionFrame? frame;
  const _TodayOverview({required this.records, required this.frame});

  @override
  Widget build(BuildContext context) {
    final todayKey = Protocol.formatDay(DateTime.now());
    final today = records
        .where((r) => Protocol.formatDay(r.at) == todayKey)
        .toList();

    // 只统计站/坐/卧三种已确认姿态；UNK 不计入占比（沿用不强猜原则）。
    const counted = ['STD', 'SIT', 'LIE'];
    final valid = today.where((r) => counted.contains(r.pose)).toList();
    String ratio = '—';
    String mainPose = '主要姿态';
    if (valid.isNotEmpty) {
      final counts = <String, int>{};
      for (final r in valid) {
        counts[r.pose] = (counts[r.pose] ?? 0) + 1;
      }
      final top = counts.entries.reduce(
          (a, b) => a.value >= b.value ? a : b);
      ratio = '${((top.value / valid.length) * 100).round()}%';
      mainPose = '主要姿态 · ${poseStyles[top.key]?.title ?? '—'}';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('今日概览',
            style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.muted)),
        const SizedBox(height: 10),
        Row(
          children: [
            StatTile('${today.length}', '今日识别 · 次'),
            const SizedBox(width: 10),
            StatTile(ratio, mainPose),
            const SizedBox(width: 10),
            StatTile(
                frame == null ? '—' : Protocol.formatMs(frame!.ms),
                '最近同步耗时'),
          ],
        ),
      ],
    );
  }
}
