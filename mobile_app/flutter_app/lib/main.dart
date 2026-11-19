import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'providers/petlink_provider.dart';
import 'screens/home_screen.dart';
import 'theme/app_theme.dart';

void main() {
  // 骨架：入口仅装配 Provider 与根 MaterialApp。
  runApp(const PetLinkApp());
}

class PetLinkApp extends StatelessWidget {
  const PetLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => PetlinkProvider()..init(),
      child: MaterialApp(
        title: 'PetLink 姿态识别',
        theme: AppTheme.light,
        home: const HomeScreen(),
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}
