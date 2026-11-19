import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/petlink_provider.dart';
import '../services/protocol.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';

/// 设备页：设备信息（名称 / 连接态 / 推流态 / 帧耗时 / 断开）＋ 关于与免责。
/// 迁移指南 §三 3：移除旧「固件 1.3.0-tjc / 喇叭取消 / RTC 校时」相关卡片；
/// 合规红线 D1–D6 整体沿用，措辞适配视觉姿态。
class DeviceScreen extends StatelessWidget {
  const DeviceScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = Provider.of<PetlinkProvider>(context);
    final f = p.latest;

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 16),
      children: [
        SectionCard(
          Column(
            children: [
              Row(
                children: [
                  const Text('设备信息',
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink)),
                  const Spacer(),
                  StatusTag(p.isConnected ? '已连接' : '未连接',
                      p.isConnected ? TagKind.ok : TagKind.off),
                ],
              ),
              const SizedBox(height: 4),
              const KV(
                  '设备名称',
                  Text(Protocol.deviceName,
                      style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink))),
              const KV(
                  '服务 UUID',
                  Text('6E400001 · NUS',
                      style: TextStyle(fontSize: 12, color: AppColors.muted))),
              KV(
                  '推流状态',
                  StatusTag(
                      !p.isConnected
                          ? '未连接'
                          : (p.streamStale ? '等待板端推流' : '接收中'),
                      !p.isConnected
                          ? TagKind.neutral
                          : (p.streamStale ? TagKind.off : TagKind.ok))),
              KV(
                  '当前帧耗时',
                  Text(f == null ? '—' : Protocol.formatMs(f.ms),
                      style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink))),
              if (p.isConnected) ...[
                const SizedBox(height: 12),
                SoftButton('断开连接',
                    onPressed: p.disconnect, fg: AppColors.warning),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: AppColors.surfaceAlt,
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('关于与免责',
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink)),
              SizedBox(height: 8),
              Text(
                '· 姿态识别结果为行为层面提示，非医疗判断。\n'
                '· 板子单连接、无加密：同空间任何人可连，演示级勿当安全边界。\n'
                '· 历史由手机本地保存，按姿态变化或 5 秒间隔抽稀写入。\n'
                '· 推流约 0.38~1.1 Hz，非连续监护设备。\n'
                '· 物种由视觉检测的 cls 字段直接给出，App 按服务 UUID 识别设备，不依赖广播名。',
                style: TextStyle(
                    fontSize: 12, color: AppColors.muted, height: 1.7),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Text(p.message,
            style: const TextStyle(fontSize: 11, color: AppColors.muted2)),
      ],
    );
  }
}
