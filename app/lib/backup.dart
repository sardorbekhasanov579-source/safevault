import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_contacts/flutter_contacts.dart';
import 'package:photo_manager/photo_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'session.dart';

const maxFileBytes = 200 * 1024 * 1024; // v0.1: butun fayl xotiraga o'qiladi, katta videolar keyin (oqimli yuklash)
const _maxConsecutiveFails = 3;

/// Hujjat sifatida avtomatik zaxiralanadigan fayl turlari va papkalar (Android).
const docExts = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'odt', 'rtf', 'csv'};
const docRoots = [
  '/storage/emulated/0/Download',
  '/storage/emulated/0/Documents',
  '/storage/emulated/0/Android/media/org.telegram.messenger/Telegram/Telegram Documents',
];

class BackupResult {
  int uploaded = 0, skipped = 0, failed = 0, tooBig = 0;
  bool partial = false; // vaqt tugadi, qolganini keyingi safar davom ettiramiz
  bool authFailed = false; // server sessiyani rad etdi (qayta kirish kerak)
  bool networkDown = false; // ketma-ket xatolar: tarmoq yo'q deb to'xtatildi
  final List<String> notes = [];

  String get summary {
    final b = StringBuffer('Yangi: $uploaded, allaqachon bor: $skipped, xato: $failed');
    if (tooBig > 0) b.write(', juda katta: $tooBig');
    if (partial) b.write(' (davomi keyingi safar)');
    return b.toString();
  }
}

class BackupService {
  final VaultSession session;
  final void Function(String) onProgress;
  final bool background;
  final Duration? budget;
  final Stopwatch _sw = Stopwatch();
  SharedPreferences? _prefs;
  Set<String> _done = {};
  int _consecutiveFails = 0;

  BackupService(this.session, this.onProgress, {this.background = false, this.budget});

  bool get _timeUp => budget != null && _sw.elapsed > budget!;

  Future<BackupResult> run(Set<String> cats) async {
    final res = BackupResult();
    _sw.start();
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload(); // fon izolyati yozgan o'zgarishlarni ko'rish uchun
    _prefs = prefs;
    _done = (prefs.getStringList('done_keys') ?? <String>[]).toSet();
    try {
      if (cats.contains('photo') || cats.contains('video')) {
        await _media(cats, res);
      }
      if (cats.contains('contact') && !res.authFailed && !res.partial && !res.networkDown) {
        await _contacts(res);
      }
      if (cats.contains('document') && !res.authFailed && !res.partial && !res.networkDown) {
        await _documentFolders(res);
      }
    } finally {
      await _saveCache();
    }
    return res;
  }

  Future<void> _saveCache() async => _prefs?.setStringList('done_keys', _done.toList());

  /// true — serverda endi bor (yangi yuklandi yoki oldin bor edi).
  Future<bool> _put(BackupResult res, Uint8List data, Map<String, dynamic> meta) async {
    try {
      if (await session.backupBytes(data, meta)) {
        res.uploaded++;
      } else {
        res.skipped++;
      }
      _consecutiveFails = 0;
      return true;
    } on ApiException catch (e) {
      if (e.status == 401) {
        res.authFailed = true;
      } else {
        res.failed++;
        res.notes.add('${meta['name']}: ${e.code}');
      }
      return false;
    } catch (e) {
      res.failed++;
      res.notes.add('${meta['name']}: $e');
      if (++_consecutiveFails >= _maxConsecutiveFails) res.networkDown = true;
      return false;
    }
  }

  Future<void> _media(Set<String> cats, BackupResult res) async {
    if (!background) {
      final perm = await PhotoManager.requestPermissionExtend();
      if (!perm.hasAccess) {
        res.notes.add('Rasm/video ruxsati berilmagan');
        return;
      }
    }
    final List<AssetPathEntity> paths;
    try {
      paths = await PhotoManager.getAssetPathList(onlyAll: true, type: RequestType.common);
    } catch (e) {
      res.notes.add("Galereyaga kirib bo'lmadi (ruxsatni tekshiring)");
      return;
    }
    if (paths.isEmpty) return;
    final all = paths.first;
    final total = await all.assetCountAsync;
    var page = 0, seen = 0, sinceSave = 0;
    while (true) {
      final assets = await all.getAssetListPaged(page: page++, size: 50);
      if (assets.isEmpty) break;
      for (final a in assets) {
        seen++;
        if (res.authFailed || res.networkDown) return;
        if (_timeUp) {
          res.partial = true;
          return;
        }
        final isVideo = a.type == AssetType.video;
        if (isVideo ? !cats.contains('video') : !cats.contains('photo')) continue;
        final key = '${a.id}:${a.modifiedDateTime.millisecondsSinceEpoch}';
        if (_done.contains(key)) continue; // bu fayl avval muvaffaqiyatli saqlangan
        onProgress('${isVideo ? "Video" : "Rasm"}: $seen / $total');
        final file = await a.originFile;
        if (file == null) continue;
        if (await file.length() > maxFileBytes) {
          res.tooBig++;
          _done.add(key);
          continue;
        }
        final ok = await _put(res, await file.readAsBytes(), {
          'name': await a.titleAsync,
          'category': isVideo ? 'video' : 'photo',
          'mtime': a.modifiedDateTime.millisecondsSinceEpoch ~/ 1000,
        });
        if (ok) {
          _done.add(key);
          if (++sinceSave >= 20) {
            sinceSave = 0;
            await _saveCache();
          }
        }
      }
    }
  }

  Future<void> _contacts(BackupResult res) async {
    final prefs = _prefs!;
    final now = DateTime.now().millisecondsSinceEpoch;
    if (background && now - (prefs.getInt('contacts_last') ?? 0) < 12 * 3600 * 1000) return;
    bool ok;
    try {
      ok = await FlutterContacts.requestPermission(readonly: true).timeout(const Duration(seconds: 15));
    } catch (_) {
      ok = false;
    }
    if (!ok) {
      res.notes.add('Kontaktlar ruxsati berilmagan');
      return;
    }
    onProgress("Kontaktlar o'qilmoqda…");
    final list = await FlutterContacts.getContacts(withProperties: true, withPhoto: false);
    final vcf = list.map((c) => c.toVCard()).join('\n');
    final saved = await _put(res, Uint8List.fromList(utf8.encode(vcf)),
        {'name': 'kontaktlar.vcf', 'category': 'contact', 'count': list.length});
    if (saved) await prefs.setInt('contacts_last', now);
  }

  /// Yuklamalar (Download), Hujjatlar (Documents) va Telegram hujjatlari papkalaridagi PDF/Word/slayd kabi fayllar.
  /// Android 11+ da buning uchun "Barcha fayllarga ruxsat" kerak.
  Future<void> _documentFolders(BackupResult res) async {
    if (!Platform.isAndroid) return;
    var found = 0, sinceSave = 0;
    for (final root in docRoots) {
      final dir = Directory(root);
      try {
        if (!await dir.exists()) continue;
      } catch (_) {
        continue;
      }
      try {
        await for (final e in dir.list(recursive: true, followLinks: false)) {
          if (e is! File) continue;
          if (res.authFailed || res.networkDown) return;
          if (_timeUp) {
            res.partial = true;
            return;
          }
          if (e.path.contains('/.')) continue; // yashirin papka va fayllar
          final name = e.path.split('/').last;
          final dot = name.lastIndexOf('.');
          if (dot < 0 || !docExts.contains(name.substring(dot + 1).toLowerCase())) continue;
          final st = await e.stat();
          final key = 'doc:${e.path}:${st.modified.millisecondsSinceEpoch}:${st.size}';
          if (_done.contains(key)) continue;
          if (st.size > maxFileBytes) {
            res.tooBig++;
            _done.add(key);
            continue;
          }
          onProgress('Hujjat: ${++found}');
          final ok = await _put(res, await e.readAsBytes(), {
            'name': name,
            'category': 'document',
            'mtime': st.modified.millisecondsSinceEpoch ~/ 1000,
          });
          if (ok) {
            _done.add(key);
            if (++sinceSave >= 20) {
              sinceSave = 0;
              await _saveCache();
            }
          }
        }
      } on FileSystemException {
        res.notes.add("Hujjat papkasiga kirib bo'lmadi: «Barcha fayllarga ruxsat» bering");
      }
    }
  }

  /// Foydalanuvchi qo'lda tanlagan hujjatlar (boshqa papkalardagi fayllar uchun).
  Future<BackupResult> documents(List<String> paths) async {
    final res = BackupResult();
    var i = 0;
    for (final p in paths) {
      onProgress('Hujjat: ${++i} / ${paths.length}');
      final f = File(p);
      if (await f.length() > maxFileBytes) {
        res.tooBig++;
        continue;
      }
      await _put(res, await f.readAsBytes(), {
        'name': p.split(Platform.pathSeparator).last,
        'category': 'document',
        'mtime': (await f.lastModified()).millisecondsSinceEpoch ~/ 1000,
      });
    }
    return res;
  }
}
