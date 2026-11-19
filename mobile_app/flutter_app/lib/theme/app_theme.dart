import 'package:flutter/material.dart';

/// 视觉规范 2.0：温暖自然 + 克制专业。
/// 米杏底、单一暖橙主色、无纯黑、柔和投影替代硬描边。
class AppColors {
  static const bg = Color(0xFFFAF7F2);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceAlt = Color(0xFFF4EFE6);

  static const ink = Color(0xFF2E2922);
  static const muted = Color(0xFF8A7F6D);
  static const muted2 = Color(0xFFB7AC98);

  static const accent = Color(0xFFE8923C);
  static const accentSoft = Color(0xFFFBEEDD);

  static const positive = Color(0xFF3F8A5C);
  static const positiveSoft = Color(0xFFE4EFDD);

  static const warning = Color(0xFFC4564F);
  static const warningSoft = Color(0xFFF6E4E2);

  static const info = Color(0xFF3B6FB0);
  static const infoSoft = Color(0xFFE6EEF7);

  static const line = Color(0xFFECE4D6);

  // 兼容旧命名
  static const card = surface;
  static const ok = positive;
  static const warn = warning;
  static const soft = surfaceAlt;
  static const blue = info;
}

class AppRadius {
  static const sm = 12.0;
  static const md = 14.0;
  static const lg = 20.0;
  static const sheet = 24.0;
  static const pill = 999.0;
}

class AppTheme {
  static final light = ThemeData(
    useMaterial3: true,
    scaffoldBackgroundColor: AppColors.bg,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.accent,
      brightness: Brightness.light,
    ).copyWith(
      surface: AppColors.bg,
      primary: AppColors.accent,
    ),
    textTheme: const TextTheme(
      bodyMedium: TextStyle(color: AppColors.ink, fontSize: 14, height: 1.45),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      foregroundColor: AppColors.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
    ),
    splashFactory: InkSparkle.splashFactory,
  );
}
