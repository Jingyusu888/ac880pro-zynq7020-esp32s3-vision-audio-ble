import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../models/vision_frame.dart';
import '../services/protocol.dart';
import '../utils/pose_labels.dart';

/// 本地历史持久化：SQLite，按「本地时间戳 + seq」复合主键去重。
/// 迁移指南 §三 2：历史改由手机本地保存，不再从板端读取 300 条游标。
///
/// 兼容性说明：数据库文件仍为 petlink.db，版本升至 2；旧版 records 表
/// **保留不删除也不读写**（已安装设备上的旧历史不丢），新数据写入独立
/// 的 vision_records 表，两者互不干扰。
class StorageService {
  Database? _db;

  Future<void> init() async {
    final dir = await getApplicationDocumentsDirectory();
    _db = await openDatabase(
      p.join(dir.path, 'petlink.db'),
      version: 2,
      onCreate: (db, _) => _createTable(db),
      onUpgrade: (db, oldVersion, _) async {
        if (oldVersion < 2) await _createTable(db);
      },
    );
  }

  Future<void> _createTable(Database db) => db.execute(
        'CREATE TABLE IF NOT EXISTS vision_records('
        'id TEXT PRIMARY KEY, seq INTEGER, at_ms INTEGER, cls TEXT, pose TEXT, '
        'score REAL, kpt_cnt INTEGER, ms REAL)',
      );

  Future<void> insert(VisionRecord r) async {
    await _db!.insert(
      'vision_records',
      r.toMap(),
      conflictAlgorithm: ConflictAlgorithm.ignore,
    );
  }

  Future<List<VisionRecord>> all() async {
    final maps = await _db!.query('vision_records', orderBy: 'at_ms DESC');
    return maps.map(VisionRecord.fromMap).toList(growable: false);
  }

  /// 导出 CSV：带 BOM 防中文乱码，首行注明「行为提示，非医疗判断」（红线 D1）。
  Future<String> exportCsv() async {
    final rows = await all();
    final buf = StringBuffer();
    buf.writeln('﻿# PetLink $legalLine');
    buf.writeln('帧序号,时间,物种,姿态,检测置信度,关键点,帧耗时(ms)');
    for (final r in rows) {
      buf.writeln([
        r.seq,
        '${Protocol.formatDay(r.at)} ${Protocol.formatHms(r.at)}',
        speciesText(r.cls),
        poseStyles[r.pose]?.title ?? '待确认 · 局部遮挡',
        '${(r.score * 100).toStringAsFixed(1)}%',
        '${r.kptCnt}/17',
        r.ms.toStringAsFixed(1),
      ].join(','));
    }
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(
      dir.path,
      'petlink_pose_${DateTime.now().toIso8601String().substring(0, 10)}.csv',
    ));
    await file.writeAsString(buf.toString(), encoding: utf8);
    return file.path;
  }
}
