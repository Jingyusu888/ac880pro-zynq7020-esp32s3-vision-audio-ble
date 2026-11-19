import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 通用胶囊标签。
class Pill extends StatelessWidget {
  final String text;
  final Color fg;
  final Color bg;
  const Pill(this.text, {super.key, required this.fg, required this.bg});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
        child: Text(text,
            style: TextStyle(
                fontSize: 11, color: fg, fontWeight: FontWeight.w600)),
      );
}

/// 三色状态 pill：已连接 / 未连接 / 蓝色能力标 / 中性。
class StatusTag extends StatelessWidget {
  final String text;
  final TagKind kind;
  const StatusTag(this.text, this.kind, {super.key});

  @override
  Widget build(BuildContext context) {
    Color bg;
    Color fg;
    switch (kind) {
      case TagKind.ok:
        bg = AppColors.positiveSoft;
        fg = AppColors.positive;
        break;
      case TagKind.off:
        bg = AppColors.warningSoft;
        fg = AppColors.warning;
        break;
      case TagKind.ble:
        bg = AppColors.infoSoft;
        fg = AppColors.info;
        break;
      case TagKind.neutral:
        bg = AppColors.surfaceAlt;
        fg = AppColors.ink;
        break;
    }
    return Pill(text, fg: fg, bg: bg);
  }
}

enum TagKind { ok, off, ble, neutral }

/// 合规注脚（红线 D1 / D6）：只出现一次，放在页面底部。
class LegalNote extends StatelessWidget {
  const LegalNote({super.key});
  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.only(top: 14, left: 4, right: 4),
        child: Text(
          '本结果仅基于设备回传的视觉姿态帧，为行为层面提示，不构成医疗诊断。',
          style: TextStyle(fontSize: 11, color: AppColors.muted, height: 1.5),
        ),
      );
}

/// 圆角卡片容器。
class SectionCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  const SectionCard(this.child, {super.key, this.padding});

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: padding ?? const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: child,
      );
}

/// 一行键值。
class KV extends StatelessWidget {
  final String k;
  final Widget v;
  const KV(this.k, this.v, {super.key});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          children: [
            Text(k, style: const TextStyle(fontSize: 13, color: AppColors.muted)),
            const Spacer(),
            v,
          ],
        ),
      );
}

/// 主按钮：实心暖橙。
class PrimaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  const PrimaryButton(this.label, {super.key, this.onPressed});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        height: 52,
        child: ElevatedButton(
          onPressed: onPressed,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.accent,
            foregroundColor: Colors.white,
            disabledBackgroundColor: AppColors.accentSoft,
            disabledForegroundColor: AppColors.muted,
            elevation: 0,
            surfaceTintColor: Colors.transparent,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.md)),
          ),
          child: Text(label,
              style:
                  const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        ),
      );
}

/// 次按钮：柔和底色。
class SoftButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final Color? fg;
  const SoftButton(this.label, {super.key, this.onPressed, this.fg});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        height: 48,
        child: ElevatedButton(
          onPressed: onPressed,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.surfaceAlt,
            foregroundColor: fg ?? AppColors.ink,
            disabledBackgroundColor: AppColors.surfaceAlt,
            disabledForegroundColor: AppColors.muted2,
            elevation: 0,
            surfaceTintColor: Colors.transparent,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.md)),
          ),
          child: Text(label,
              style:
                  const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
        ),
      );
}

/// 统计格（需放在 Row 内）。
class StatTile extends StatelessWidget {
  final String value;
  final String label;
  const StatTile(this.value, this.label, {super.key});

  @override
  Widget build(BuildContext context) => Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value,
                  style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink)),
              const SizedBox(height: 6),
              Text(label,
                  style:
                      const TextStyle(fontSize: 11, color: AppColors.muted)),
            ],
          ),
        ),
      );
}

/// 状态圆点。
class StatusDot extends StatelessWidget {
  final Color color;
  final double size;
  const StatusDot({super.key, this.color = AppColors.positive, this.size = 8});

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      );
}

/// 顶部连接状态条：点击进入连接弹层。
class ConnectionStrip extends StatelessWidget {
  final bool connected;
  final String name;
  final VoidCallback onTap;
  const ConnectionStrip({
    super.key,
    required this.connected,
    required this.name,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
          child: Row(
            children: [
              StatusDot(
                  color: connected ? AppColors.positive : AppColors.muted2),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  connected ? '$name · 已连接' : '未连接 · 点此连接板子',
                  style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink),
                ),
              ),
              Text(
                connected ? '›' : '连接',
                style: TextStyle(
                    fontSize: connected ? 16 : 13,
                    fontWeight: FontWeight.w600,
                    color: AppColors.accent),
              ),
            ],
          ),
        ),
      );
}
