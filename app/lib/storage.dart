import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'session.dart';
import 'vault_crypto.dart';

/// Fon zaxirasi uchun saqlangan kirish ma'lumotlari (Android Keystore himoyasidagi xotirada).
class BgCreds {
  final String server, deviceId, token, mk;
  BgCreds(this.server, this.deviceId, this.token, this.mk);
}

class AutoRun {
  final DateTime time;
  final String message;
  AutoRun(this.time, this.message);
}

/// Maxfiy qiymatlar (token, asosiy kalit) Android Keystore bilan himoyalangan xotirada.
class AppStore {
  static const _s = FlutterSecureStorage();

  static Future<String?> get(String k) => _s.read(key: k);
  static Future<void> set(String k, String v) => _s.write(key: k, value: v);
  static Future<void> del(String k) => _s.delete(key: k);

  static Future<String> deviceId() async {
    var id = await get('device_id');
    if (id == null) {
      id = hexOf(randomBytes(16));
      await set('device_id', id);
    }
    return id;
  }

  /// Chiqishda faqat sessiya o'chadi; qurilma identifikatori va server manzili qoladi.
  static Future<void> clearSession() async {
    await del('token');
    await del('mk');
  }

  static const allCategories = ['photo', 'video', 'contact', 'document'];

  static Future<Set<String>> categories() async {
    final p = await SharedPreferences.getInstance();
    await p.reload();
    return (p.getStringList('cats') ?? <String>[]).toSet();
  }

  static Future<void> setCategories(Set<String> c) async =>
      (await SharedPreferences.getInstance()).setStringList('cats', c.toList());

  /// Ruxsat tushuntirishi har bir turga faqat BIR MARTA ko'rsatiladi.
  static Future<bool> wasExplained(String cat) async =>
      (await SharedPreferences.getInstance()).getBool('explained_$cat') ?? false;

  static Future<void> markExplained(String cat) async =>
      (await SharedPreferences.getInstance()).setBool('explained_$cat', true);

  // ---------- avtomatik (fon) zaxira ----------
  static Future<bool> autoEnabled() async {
    final p = await SharedPreferences.getInstance();
    await p.reload();
    return p.getBool('auto_on') ?? false;
  }

  static Future<void> setAuto(bool v) async => (await SharedPreferences.getInstance()).setBool('auto_on', v);

  static Future<bool> wifiOnly() async => (await SharedPreferences.getInstance()).getBool('wifi_only') ?? true;

  static Future<void> setWifiOnly(bool v) async => (await SharedPreferences.getInstance()).setBool('wifi_only', v);

  static Future<void> writeBg(VaultSession s) async {
    await set('bg_server', s.api.baseUrl);
    await set('bg_device', s.api.deviceId);
    await set('bg_token', s.api.token!);
    await set('bg_mk', b64e(s.mk!));
  }

  static Future<BgCreds?> readBg() async {
    final server = await get('bg_server');
    final device = await get('bg_device');
    final token = await get('bg_token');
    final mk = await get('bg_mk');
    if (server == null || device == null || token == null || mk == null) return null;
    return BgCreds(server, device, token, mk);
  }

  static Future<void> deleteBg() async {
    for (final k in ['bg_server', 'bg_device', 'bg_token', 'bg_mk']) {
      await del(k);
    }
  }

  // ---------- joylashuvni yuborish ----------
  static Future<bool> locationEnabled() async {
    final p = await SharedPreferences.getInstance();
    await p.reload();
    return p.getBool('loc_on') ?? false;
  }

  static Future<void> setLocationEnabled(bool v) async => (await SharedPreferences.getInstance()).setBool('loc_on', v);

  static Future<void> recordLocRun(String msg) async {
    final p = await SharedPreferences.getInstance();
    await p.setInt('loc_last', DateTime.now().millisecondsSinceEpoch);
    await p.setString('loc_msg', msg);
  }

  static Future<AutoRun?> lastLocRun() async {
    final p = await SharedPreferences.getInstance();
    await p.reload();
    final ms = p.getInt('loc_last');
    if (ms == null) return null;
    return AutoRun(DateTime.fromMillisecondsSinceEpoch(ms), p.getString('loc_msg') ?? '');
  }

  static Future<void> recordAutoRun(String msg) async {
    final p = await SharedPreferences.getInstance();
    await p.setInt('auto_last', DateTime.now().millisecondsSinceEpoch);
    await p.setString('auto_msg', msg);
  }

  static Future<AutoRun?> lastAutoRun() async {
    final p = await SharedPreferences.getInstance();
    await p.reload();
    final ms = p.getInt('auto_last');
    if (ms == null) return null;
    return AutoRun(DateTime.fromMillisecondsSinceEpoch(ms), p.getString('auto_msg') ?? '');
  }

  /// Boshqa hisobga kirilganda "bu fayl saqlangan" keshi tozalanadi.
  static Future<void> clearBackupCache() async {
    final p = await SharedPreferences.getInstance();
    await p.remove('done_keys');
    await p.remove('contacts_last');
  }
}

Future<bool> authenticateWithBiometrics() async {
  final auth = LocalAuthentication();
  try {
    if (!await auth.canCheckBiometrics) return false;
    return await auth.authenticate(
        localizedReason: 'SafeVault ga kirish uchun barmoq izingizni tasdiqlang',
        options: const AuthenticationOptions(biometricOnly: true));
  } catch (_) {
    return false;
  }
}
