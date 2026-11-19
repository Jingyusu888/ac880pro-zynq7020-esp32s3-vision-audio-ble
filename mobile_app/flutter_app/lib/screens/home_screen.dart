import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/petlink_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/connect_sheet.dart';
import 'device_screen.dart';
import 'history_screen.dart';
import 'live_screen.dart';

/// 根页面：品牌顶栏 + 底部胶囊三 Tab（实时 / 历史 / 设备）。
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  final _pages = const [LiveScreen(), HistoryScreen(), DeviceScreen()];

  @override
  Widget build(BuildContext context) {
    final p = Provider.of<PetlinkProvider>(context);
    final connected = p.isConnected;
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        titleSpacing: 18,
        title: const Row(
          children: [
            Icon(Icons.pets, size: 22, color: AppColors.accent),
            SizedBox(width: 8),
            Text('PetLink 姿态识别',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 14),
            child: GestureDetector(
              onTap: connected ? p.disconnect : () => showConnectSheet(context),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: connected
                      ? AppColors.positiveSoft
                      : AppColors.warningSoft,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: Row(
                  children: [
                    StatusDot(
                        color: connected
                            ? AppColors.positive
                            : AppColors.warning),
                    const SizedBox(width: 6),
                    Text(
                      connected ? '已连接' : '未连接',
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: connected
                              ? AppColors.positive
                              : AppColors.warning),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(top: false, child: _pages[_tab]),
      bottomNavigationBar:
          _PillNav(index: _tab, onTap: (i) => setState(() => _tab = i)),
    );
  }
}

class _PillNav extends StatelessWidget {
  final int index;
  final ValueChanged<int> onTap;
  const _PillNav({required this.index, required this.onTap});

  static const _items = [
    (Icons.visibility, '实时'),
    (Icons.history, '历史'),
    (Icons.tune, '设备'),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.bg,
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 14),
      child: Container(
        height: 62,
        padding: const EdgeInsets.symmetric(horizontal: 30),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(30),
          boxShadow: const [
            BoxShadow(
                color: Color(0x1A2E2922),
                blurRadius: 18,
                offset: Offset(0, 8)),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: List.generate(_items.length, (i) {
            final active = i == index;
            final color = active ? AppColors.accent : AppColors.muted;
            return GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () => onTap(i),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(_items[i].$1, size: 22, color: color),
                  const SizedBox(height: 4),
                  Text(_items[i].$2,
                      style: TextStyle(
                          fontSize: 11,
                          color: color,
                          fontWeight: active
                              ? FontWeight.w700
                              : FontWeight.w500)),
                ],
              ),
            );
          }),
        ),
      ),
    );
  }
}
