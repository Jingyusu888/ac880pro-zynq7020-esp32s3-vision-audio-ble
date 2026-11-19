import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:provider/provider.dart';

import '../providers/petlink_provider.dart';
import '../services/ble_service.dart';
import '../theme/app_theme.dart';

/// 连接引导层：按 NUS 服务 UUID 扫描并列出 Petlink-ESP32S3，点选即连接。
/// 路线 A：界面以真实设备名展示，识别仍以 128-bit 服务 UUID 为准。
void showConnectSheet(BuildContext context) {
  final p = Provider.of<PetlinkProvider>(context, listen: false);
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => _ConnectSheetBody(p: p),
  );
}

class _ConnectSheetBody extends StatefulWidget {
  final PetlinkProvider p;
  const _ConnectSheetBody({required this.p});

  @override
  State<_ConnectSheetBody> createState() => _ConnectSheetBodyState();
}

class _ConnectSheetBodyState extends State<_ConnectSheetBody> {
  List<ScanResult> results = [];
  bool scanning = true;
  String err = '';
  ScanFailureReason? failure;

  @override
  void initState() {
    super.initState();
    _scan();
  }

  Future<void> _scan() async {
    try {
      final r = await widget.p.ble.scan();
      if (mounted) setState(() => results = r);
    } on ScanFailure catch (e) {
      if (mounted) {
        setState(() {
          failure = e.reason;
          err = e.message;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          failure = ScanFailureReason.unknown;
          err = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => scanning = false);
    }
  }

  void _retry() {
    setState(() {
      scanning = true;
      err = '';
      failure = null;
      results = [];
    });
    _scan();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.sheet)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 20),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 5,
                decoration: BoxDecoration(
                  color: AppColors.line,
                  borderRadius: BorderRadius.circular(3),
                ),
              ),
            ),
            const SizedBox(height: 14),
            const Text('连接 PetLink 设备',
                style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink)),
            const SizedBox(height: 4),
            const Text('请确保 ESP32-S3 已上电并靠近手机；设备显示为 Petlink-ESP32S3',
                style: TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 14),
            _body(),
            const SizedBox(height: 6),
            Center(
              child: TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消',
                    style: TextStyle(color: AppColors.muted)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    if (scanning) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        child: Row(
          children: [
            const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                  strokeWidth: 2.4, color: AppColors.accent),
            ),
            const SizedBox(width: 10),
            const Text('正在搜索附近设备…',
                style: TextStyle(fontSize: 13, color: AppColors.muted)),
          ],
        ),
      );
    }

    if (err.isNotEmpty) {
      IconData icon = Icons.bluetooth_searching;
      String title = '扫描失败';
      if (failure == ScanFailureReason.bluetoothOff) {
        icon = Icons.bluetooth_disabled;
        title = '手机蓝牙未开启';
      } else if (failure == ScanFailureReason.permissionDenied) {
        icon = Icons.lock_outline;
        title = '需要蓝牙权限';
      }
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _hintCard(icon, title, err.replaceFirst(RegExp(r'^Exception:\s*'), '')),
          const SizedBox(height: 12),
          _retryButton(),
        ],
      );
    }

    if (results.isEmpty) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _hintCard(
            Icons.bluetooth,
            '未搜索到设备',
            '确认 ESP32-S3 已上电、已连上 Wi-Fi 且未连着其他手机；'
            '设备显示为 Petlink-ESP32S3。Android 11 及以下还需打开定位服务并授权位置权限。',
          ),
          const SizedBox(height: 12),
          _retryButton(),
        ],
      );
    }

    return Column(
      children: results.map((r) => _deviceRow(r)).toList(),
    );
  }

  Widget _hintCard(IconData icon, String title, String subtitle) => Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 24),
        decoration: BoxDecoration(
          color: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        child: Column(
          children: [
            Icon(icon, size: 40, color: AppColors.muted),
            const SizedBox(height: 10),
            Text(title,
                style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.ink)),
            const SizedBox(height: 4),
            Text(subtitle,
                textAlign: TextAlign.center,
                style:
                    const TextStyle(fontSize: 11, color: AppColors.muted)),
          ],
        ),
      );

  Widget _retryButton() => SizedBox(
        width: double.infinity,
        height: 48,
        child: ElevatedButton(
          onPressed: _retry,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.accent,
            foregroundColor: Colors.white,
            elevation: 0,
            surfaceTintColor: Colors.transparent,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.sm)),
          ),
          child: const Text('重新搜索',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
        ),
      );

  Widget _deviceRow(ScanResult r) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        child: Row(
          children: [
            const Icon(Icons.bluetooth, size: 24, color: AppColors.ink),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      _nameOf(r).isEmpty ? 'PetLink 设备' : _nameOf(r),
                      style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink)),
                  const SizedBox(height: 3),
                  Text('服务 UUID 已匹配 · 信号 ${r.rssi} dBm',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 11, color: AppColors.muted)),
                ],
              ),
            ),
            GestureDetector(
              onTap: () {
                Navigator.pop(context);
                widget.p.connectDevice(r.device);
              },
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.accent,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: const Text('连接',
                    style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: Colors.white)),
              ),
            ),
          ],
        ),
      );

  String _nameOf(ScanResult r) => r.device.platformName.isNotEmpty
      ? r.device.platformName
      : r.advertisementData.advName;
}
