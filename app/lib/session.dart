// Mijoz mantig'i — client/safevault_client/client.py ning Dart varianti.
import 'dart:typed_data';

import 'api.dart';
import 'vault_crypto.dart';

class RemoteFile {
  final String id;
  final int size;
  final double uploadedAt;
  final Map<String, dynamic> meta;
  RemoteFile(this.id, this.size, this.uploadedAt, this.meta);
  String get name => (meta['name'] ?? '?') as String;
  String get category => (meta['category'] ?? 'document') as String;
}

class VaultStatus {
  final int fileCount;
  final int totalBytes;
  final DateTime? lastBackup;
  VaultStatus(this.fileCount, this.totalBytes, this.lastBackup);
}

class PhoneLocation {
  final double lat, lon;
  final double? acc;
  final String? addr;
  final DateTime updatedAt;
  PhoneLocation(this.lat, this.lon, this.acc, this.addr, this.updatedAt);
}

class VaultSession {
  final Api api;
  Uint8List? mk;
  VaultSession(this.api);

  Uint8List get _mk => mk ?? (throw StateError('avval kiring'));

  Future<void> requestOtp(String purpose, String phone, [String? email]) =>
      api.json('POST', '/v1/auth/otp', body: {'purpose': purpose, 'phone': phone, if (email != null) 'email': email});

  /// Hisob yaratadi va tiklash kodini qaytaradi (foydalanuvchiga FAQAT BIR MARTA ko'rsatiladi).
  Future<String> register(
      {required String phone,
      required String email,
      required String phoneCode,
      required String emailCode,
      required String password}) async {
    final newMk = randomBytes(32);
    final pwSalt = randomBytes(16), recSalt = randomBytes(16);
    final code = newRecoveryCode();
    final p = await passwordKeys(password, pwSalt, defaultKdf);
    final r = await recoveryKeys(code, recSalt);
    final res = await api.json('POST', '/v1/auth/register', body: {
      'phone': phone,
      'email': email,
      'phone_code': phoneCode,
      'email_code': emailCode,
      'pw_salt': b64e(pwSalt),
      'rec_salt': b64e(recSalt),
      'kdf': defaultKdf,
      'auth': b64e(p.auth),
      'rec_auth': b64e(r.auth),
      'wrapped_pw': b64e(await wrap(p.kek, newMk, 'sv-mk')),
      'wrapped_rec': b64e(await wrap(r.kek, newMk, 'sv-mk')),
      'device_id': api.deviceId,
    });
    api.token = res['token'] as String;
    mk = newMk;
    return code;
  }

  Future<Map<String, dynamic>> _params(String phone) =>
      api.json('GET', '/v1/auth/params?phone=${Uri.encodeQueryComponent(phone)}');

  /// Yangi qurilmada [phoneCode] va [recoveryCode] ham kerak (server 403 new_device_required qaytaradi).
  Future<void> login(String phone, String password, {String? phoneCode, String? recoveryCode}) async {
    final p = await _params(phone);
    final keys = await passwordKeys(password, b64d(p['pw_salt'] as String), p['kdf'] as Map<String, dynamic>);
    final body = <String, dynamic>{'phone': phone, 'auth': b64e(keys.auth), 'device_id': api.deviceId};
    if (phoneCode != null && recoveryCode != null) {
      final rk = await recoveryKeys(recoveryCode, b64d(p['rec_salt'] as String));
      body['phone_code'] = phoneCode;
      body['rec_auth'] = b64e(rk.auth);
    }
    final res = await api.json('POST', '/v1/auth/login', body: body);
    mk = await unwrap(keys.kek, b64d(res['wrapped_pw'] as String), 'sv-mk');
    api.token = res['token'] as String;
  }

  /// Parol esdan chiqqanda: telefon kodi + email kodi + tiklash kodi -> yangi parol.
  Future<void> recover(
      {required String phone,
      required String phoneCode,
      required String emailCode,
      required String recoveryCode,
      required String newPassword}) async {
    final p = await _params(phone);
    final rk = await recoveryKeys(recoveryCode, b64d(p['rec_salt'] as String));
    final res = await api.json('POST', '/v1/auth/recover',
        body: {'phone': phone, 'phone_code': phoneCode, 'email_code': emailCode, 'rec_auth': b64e(rk.auth)});
    final recovered = await unwrap(rk.kek, b64d(res['wrapped_rec'] as String), 'sv-mk');
    final salt = randomBytes(16);
    final nk = await passwordKeys(newPassword, salt, defaultKdf);
    final out = await api.json('POST', '/v1/auth/reset', body: {
      'reset_token': res['reset_token'],
      'device_id': api.deviceId,
      'pw_salt': b64e(salt),
      'kdf': defaultKdf,
      'auth': b64e(nk.auth),
      'wrapped_pw': b64e(await wrap(nk.kek, recovered, 'sv-mk')),
    });
    api.token = out['token'] as String;
    mk = recovered;
  }

  // ---------- zaxira ----------
  /// true — yangi yuklandi, false — allaqachon bor edi.
  Future<bool> backupBytes(Uint8List data, Map<String, dynamic> meta) async {
    final tag = await contentTag(_mk, await sha256Of(data));
    final miss = await api.json('POST', '/v1/files/missing', body: {'tags': [tag]});
    if ((miss['missing'] as List).isEmpty) return false;
    final blob = await encryptFile(_mk, data);
    await api.putFile(tag, blob, await encryptJson(_mk, meta, 'sv-meta'));
    return true;
  }

  Future<List<RemoteFile>> listFiles() async {
    final res = await api.json('GET', '/v1/files');
    final out = <RemoteFile>[];
    for (final f in res['files'] as List) {
      final m = f as Map<String, dynamic>;
      out.add(RemoteFile(m['id'] as String, m['size'] as int, (m['uploaded_at'] as num).toDouble(),
          await decryptJson(_mk, m['meta'] as String, 'sv-meta')));
    }
    return out;
  }

  Future<Uint8List> restore(String id) async => decryptFile(_mk, await api.getFile(id));

  // ---------- joylashuv (server faqat shifrlangan matnni ko'radi) ----------
  Future<void> sendLocation(double lat, double lon, double? acc) async {
    final payload = await encryptJson(_mk, {'lat': lat, 'lon': lon, 'acc': acc, 'addr': null, 'bat': null}, 'sv-loc');
    await api.json('POST', '/v1/location', body: {'payload': payload});
  }

  /// null — hali hech qachon yuborilmagan.
  Future<PhoneLocation?> getLocation() async {
    try {
      final r = await api.json('GET', '/v1/location');
      final m = await decryptJson(_mk, r['payload'] as String, 'sv-loc');
      return PhoneLocation((m['lat'] as num).toDouble(), (m['lon'] as num).toDouble(), (m['acc'] as num?)?.toDouble(),
          m['addr'] as String?, DateTime.fromMillisecondsSinceEpoch(((r['updated_at'] as num) * 1000).round()));
    } on ApiException catch (e) {
      if (e.status == 404) return null;
      rethrow;
    }
  }

  Future<VaultStatus> status() async {
    final r = await api.json('GET', '/v1/status');
    final last = r['last_backup_at'];
    return VaultStatus(r['file_count'] as int, r['total_bytes'] as int,
        last == null ? null : DateTime.fromMillisecondsSinceEpoch(((last as num) * 1000).round()));
  }
}
