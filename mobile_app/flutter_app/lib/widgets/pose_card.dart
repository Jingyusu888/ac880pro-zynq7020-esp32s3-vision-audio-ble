import 'package:flutter/material.dart';

import '../models/vision_frame.dart';
import '../services/protocol.dart';
import '../theme/app_theme.dart';
import '../utils/pose_labels.dart';
import 'common.dart';

/// 姿态主卡（Hero）：单一视觉焦点。
/// 映射见迁移指南 §三 3；valid=0 显示待机提示且不写历史。
/// 沿用 D2 不强猜原则：UNK 明确写「局部遮挡」，不推断具体姿态。
class PoseCard extends StatelessWidget {
  final VisionFrame? frame;
  final bool connected;
  final bool stale;

  const PoseCard({
    super.key,
    this.frame,
    required this.connected,
    required this.stale,
  });

  @override
  Widget build(BuildContext context) {
    final f = frame;
    final style = f == null
        ? poseStyles['NONE']!
        : styleFor(valid: f.valid, pose: f.pose);

    final title = f == null
        ? (connected ? '等待板端推流' : '等待连接板子')
        : style.title;

    String sub;
    if (f == null) {
      sub = connected ? '连接后自动接收 AC880 视觉姿态帧' : '连接后自动接收板端推流';
    } else if (!f.valid) {
      sub = stale ? '等待板端推流' : '画面未检测到猫狗，继续等待目标';
    } else if (stale) {
      sub = '等待板端推流（连接保持中）';
    } else {
      sub = '${speciesText(f.cls)} · 关键点 ${f.kptCnt}/17';
    }

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Container(
                width: 64,
                height: 64,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                    color: style.soft, shape: BoxShape.circle),
                child: Text(style.emoji,
                    style: TextStyle(fontSize: 32, color: style.color)),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                            fontSize: 26,
                            fontWeight: FontWeight.w700,
                            color: style.color,
                            height: 1.1)),
                    const SizedBox(height: 6),
                    Text(sub,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 13, color: AppColors.muted)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              const Pill('行为提示 · 非诊断',
                  fg: AppColors.accent, bg: AppColors.accentSoft),
              const Spacer(),
              if (f != null && f.valid)
                Text(
                  '检测置信度 ${(f.score * 100).toStringAsFixed(0)}%',
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink),
                ),
            ],
          ),
          const SizedBox(height: 14),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
            decoration: BoxDecoration(
              color: AppColors.surfaceAlt,
              borderRadius: BorderRadius.circular(AppRadius.sm),
            ),
            child: Row(
              children: [
                Pill(stale ? '等待推流' : '推流中',
                    fg: stale ? AppColors.muted : AppColors.positive,
                    bg: stale
                        ? AppColors.surfaceAlt
                        : AppColors.positiveSoft),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    f == null
                        ? '接通后自动接收 · 单包 JSON'
                        : '最近一帧 · ${Protocol.formatHms(f.receivedAt)}'
                            ' · 耗时 ${Protocol.formatMs(f.ms)} · 第 ${f.seq} 帧',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 11, color: AppColors.muted),
                  ),
                ),
              ],
            ),
          ),
          if (f != null && f.valid && f.pose == 'UNK') ...[
            const SizedBox(height: 10),
            const Text('仅见局部或缺少躯干关键点，姿态待确认，不作推断',
                style: TextStyle(fontSize: 11, color: AppColors.warning)),
          ],
        ],
      ),
    );
  }
}
