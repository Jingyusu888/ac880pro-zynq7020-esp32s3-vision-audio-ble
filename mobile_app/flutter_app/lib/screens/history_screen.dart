import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/vision_frame.dart';
import '../providers/petlink_provider.dart';
import '../services/protocol.dart';
import '../theme/app_theme.dart';
import '../utils/pose_labels.dart';
import '../widgets/common.dart';

/// 历史页：标题+条数+导出 · 物种筛选（直接按 JSON 的 cls）· 按天分组。
/// 路线 A 后历史全部来自手机本地，不再有「同步历史 / 全量重同步」。
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});
  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  int _filter = 0; // 0 全部 / 1 猫 / 2 狗

  bool _match(VisionRecord r) {
    if (_filter == 0) return true;
    return _filter == 1 ? r.cls == 'CAT' : r.cls == 'DOG';
  }

  @override
  Widget build(BuildContext context) {
    final p = Provider.of<PetlinkProvider>(context);
    final all = p.history;
    final records = all.where(_match).toList();

    final groups = <String, List<VisionRecord>>{};
    for (final r in records) {
      groups.putIfAbsent(Protocol.formatDay(r.at), () => []).add(r);
    }
    final days = groups.keys.toList();

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 16),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('历史记录',
                      style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink)),
                  const SizedBox(height: 4),
                  Text('共 ${all.length} 条 · 已按天归类',
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.muted)),
                ],
              ),
            ),
            TextButton(
              // 历史在手机本地，未连接也可导出。
              onPressed: () async {
                final path = await p.exportCsv();
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('已导出：$path')),
                  );
                }
              },
              child: const Text('导出 CSV',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.accent)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            _chip('全部', 0),
            const SizedBox(width: 8),
            _chip('猫', 1),
            const SizedBox(width: 8),
            _chip('狗', 2),
          ],
        ),
        const SizedBox(height: 14),
        if (records.isEmpty)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 30),
            alignment: Alignment.center,
            child: const Text('暂无记录。连接后按姿态变化自动累积。',
                style: TextStyle(fontSize: 13, color: AppColors.muted)),
          )
        else
          ...days.expand((day) => [
                Padding(
                  padding: const EdgeInsets.only(top: 8, bottom: 8),
                  child: Text(day,
                      style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.muted)),
                ),
                ...groups[day]!.map((r) => _Row(r: r)),
              ]),
        const LegalNote(),
      ],
    );
  }

  Widget _chip(String text, int v) {
    final active = _filter == v;
    return GestureDetector(
      onTap: () => setState(() => _filter = v),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: BoxDecoration(
          color: active ? AppColors.accent : AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
        child: Text(text,
            style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: active ? Colors.white : AppColors.ink)),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  final VisionRecord r;
  const _Row({required this.r});

  @override
  Widget build(BuildContext context) {
    final style = poseStyles[r.pose] ?? poseStyles['UNK']!;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            alignment: Alignment.center,
            decoration: BoxDecoration(
                color: style.soft, shape: BoxShape.circle),
            child: Text(style.emoji,
                style: TextStyle(fontSize: 18, color: style.color)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${speciesText(r.cls)} · ${style.title}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: AppColors.ink)),
                const SizedBox(height: 3),
                Text(
                  '${Protocol.formatHms(r.at)} · 关键点 ${r.kptCnt}/17'
                  ' · 置信度 ${(r.score * 100).toStringAsFixed(0)}%',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style:
                      const TextStyle(fontSize: 11, color: AppColors.muted),
                ),
              ],
            ),
          ),
          Pill(style.title.length > 6 ? '待确认' : style.title,
              fg: style.color, bg: style.soft),
        ],
      ),
    );
  }
}
