import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 红线 D1：行为提示，非医疗判断。CSV 首行与页面注脚共用。
/// 路线 A 后语义从「声音情绪」变为「视觉姿态」，仍属行为层面提示，措辞在 UI 层适配。
const String legalLine = '行为提示，非医疗判断';

/// 姿态展示样式。色值全部复用 UI 2.0 Design Tokens（迁移指南 §三 3 给出的 5 个色
/// 在 app_theme.dart 中已存在：info / accent / positive / muted / muted2）。
class PoseStyle {
  final String title;
  final String emoji;
  final Color color;
  final Color soft;
  const PoseStyle(this.title, this.emoji,
      {required this.color, required this.soft});
}

const Map<String, PoseStyle> poseStyles = {
  'STD': PoseStyle('站立', '🐾', color: AppColors.info, soft: AppColors.infoSoft),
  'SIT': PoseStyle('坐姿', '🪑', color: AppColors.accent, soft: AppColors.accentSoft),
  'LIE': PoseStyle('趴卧', '🛌', color: AppColors.positive, soft: AppColors.positiveSoft),
  'UNK': PoseStyle('待确认 · 局部遮挡', '❔', color: AppColors.muted, soft: AppColors.surfaceAlt),
  'NONE': PoseStyle('画面无宠物（等待目标）', '◌', color: AppColors.muted2, soft: AppColors.surfaceAlt),
};

/// valid=0 一律走 NONE；未知 pose 走 UNK（沿用 D2：不强猜）。
PoseStyle styleFor({required bool valid, required String pose}) {
  if (!valid) return poseStyles['NONE']!;
  return poseStyles[pose] ?? poseStyles['UNK']!;
}

/// 物种直接取 JSON 的 cls，不再像旧版那样从 gate_label 反推。
String speciesText(String cls) {
  switch (cls) {
    case 'CAT':
      return '猫';
    case 'DOG':
      return '狗';
    default:
      return '—';
  }
}
