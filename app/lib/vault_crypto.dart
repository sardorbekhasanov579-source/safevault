// SafeVault shifrlash yadrosi — client/safevault_client/crypto.py (Python) bilan BAYTMA-BAYT mos.
// Moslik test/crypto_test.dart + test/vectors.json orqali tekshiriladi.
import 'dart:convert';
import 'dart:isolate';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:pointycastle/export.dart' as pc;

class CryptoError implements Exception {
  final String message;
  CryptoError(this.message);
  @override
  String toString() => message;
}

const int chunkSize = 1024 * 1024;
const Map<String, dynamic> defaultKdf = {'alg': 'scrypt', 'n': 32768, 'r': 8, 'p': 1};
const String _b32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
final List<int> _magic = utf8.encode('SVF1');
final Random _rng = Random.secure();

Uint8List randomBytes(int n) => Uint8List.fromList(List<int>.generate(n, (_) => _rng.nextInt(256)));
String b64e(List<int> b) => base64Url.encode(b).replaceAll('=', '');
Uint8List b64d(String s) => Uint8List.fromList(base64Url.decode(base64Url.normalize(s)));
String hexOf(List<int> b) => b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
Uint8List fromHex(String h) => Uint8List.fromList(
    List<int>.generate(h.length ~/ 2, (i) => int.parse(h.substring(2 * i, 2 * i + 2), radix: 16)));

class KeyPair {
  final Uint8List kek; // MK ni o'raydi
  final Uint8List auth; // serverga yuboriladi (server faqat xeshini saqlaydi)
  KeyPair(this.kek, this.auth);
}

Uint8List _scrypt(Uint8List pw, Uint8List salt, int n, int r, int p, int len) {
  final s = pc.Scrypt()..init(pc.ScryptParameters(n, r, p, len, salt));
  return s.process(pw);
}

/// Parol -> (kek, auth). scrypt og'ir, shuning uchun alohida isolate'da.
Future<KeyPair> passwordKeys(String password, Uint8List salt, Map<String, dynamic> kdf) async {
  if (kdf['alg'] != 'scrypt') throw CryptoError("noma'lum KDF");
  final pw = Uint8List.fromList(utf8.encode(password));
  final n = kdf['n'] as int, r = kdf['r'] as int, p = kdf['p'] as int;
  final raw = await Isolate.run(() => _scrypt(pw, salt, n, r, p, 64));
  return KeyPair(Uint8List.sublistView(raw, 0, 32), Uint8List.sublistView(raw, 32, 64));
}

String newRecoveryCode() {
  var n = BigInt.zero;
  for (final b in randomBytes(20)) {
    n = (n << 8) | BigInt.from(b);
  }
  final chars = List<String>.generate(32, (i) => _b32[((n >> (5 * (31 - i))) & BigInt.from(31)).toInt()]);
  final s = chars.join();
  return [for (var i = 0; i < 32; i += 4) s.substring(i, i + 4)].join('-');
}

Uint8List _parseRecoveryCode(String code) {
  final s = code.replaceAll('-', '').replaceAll(' ', '').toUpperCase();
  if (s.length != 32 || s.split('').any((c) => !_b32.contains(c))) {
    throw CryptoError("tiklash kodi noto'g'ri formatda");
  }
  var n = BigInt.zero;
  for (final c in s.split('')) {
    n = (n << 5) | BigInt.from(_b32.indexOf(c));
  }
  final out = Uint8List(20);
  for (var i = 19; i >= 0; i--) {
    out[i] = (n & BigInt.from(255)).toInt();
    n >>= 8;
  }
  return out;
}

Future<KeyPair> recoveryKeys(String code, Uint8List salt) async {
  final key = await Hkdf(hmac: Hmac.sha256(), outputLength: 64).deriveKey(
      secretKey: SecretKey(_parseRecoveryCode(code)), nonce: salt, info: utf8.encode('sv-recovery-v1'));
  final raw = Uint8List.fromList(await key.extractBytes());
  return KeyPair(Uint8List.sublistView(raw, 0, 32), Uint8List.sublistView(raw, 32, 64));
}

// ---------- o'rash: nonce(12) || shifrmatn || tag(16), AES-256-GCM ----------
Future<Uint8List> wrap(Uint8List key, List<int> data, String aad) async {
  final box = await AesGcm.with256bits().encrypt(data, secretKey: SecretKey(key), aad: utf8.encode(aad));
  return Uint8List.fromList([...box.nonce, ...box.cipherText, ...box.mac.bytes]);
}

Future<Uint8List> unwrap(Uint8List key, Uint8List blob, String aad) async {
  if (blob.length < 28) throw CryptoError("ma'lumot buzilgan");
  try {
    final box = SecretBox(blob.sublist(12, blob.length - 16),
        nonce: blob.sublist(0, 12), mac: Mac(blob.sublist(blob.length - 16)));
    return Uint8List.fromList(
        await AesGcm.with256bits().decrypt(box, secretKey: SecretKey(key), aad: utf8.encode(aad)));
  } catch (_) {
    throw CryptoError("kalit noto'g'ri yoki ma'lumot buzilgan");
  }
}

// ---------- fayl: SVF1 | prefix(4) | len(2) | wrapped_fk | bo'laklar(ChaCha20-Poly1305) ----------
Uint8List _chunkNonce(Uint8List prefix, int i) {
  final n = Uint8List(12)..setRange(0, 4, prefix);
  ByteData.sublistView(n).setUint64(4, i, Endian.big);
  return n;
}

List<int> _chunkAad(bool last) => [..._magic, last ? 1 : 0];

Future<Uint8List> encryptFile(Uint8List mk, Uint8List data) async {
  final fk = randomBytes(32);
  final prefix = randomBytes(4);
  final wrapped = await wrap(mk, fk, 'sv-fk');
  final out = BytesBuilder()
    ..add(_magic)
    ..add(prefix)
    ..add([wrapped.length >> 8, wrapped.length & 255])
    ..add(wrapped);
  final aead = Chacha20.poly1305Aead();
  final nChunks = max(1, (data.length + chunkSize - 1) ~/ chunkSize);
  for (var i = 0; i < nChunks; i++) {
    final end = min((i + 1) * chunkSize, data.length);
    final box = await aead.encrypt(Uint8List.sublistView(data, min(i * chunkSize, data.length), end),
        secretKey: SecretKey(fk), nonce: _chunkNonce(prefix, i), aad: _chunkAad(i == nChunks - 1));
    out
      ..add(box.cipherText)
      ..add(box.mac.bytes);
  }
  return out.toBytes();
}

Future<Uint8List> decryptFile(Uint8List mk, Uint8List blob) async {
  if (blob.length < 10 || String.fromCharCodes(blob.sublist(0, 4)) != 'SVF1') {
    throw CryptoError("fayl formati noto'g'ri");
  }
  final prefix = blob.sublist(4, 8);
  final wl = (blob[8] << 8) | blob[9];
  final fk = await unwrap(mk, blob.sublist(10, 10 + wl), 'sv-fk');
  final body = Uint8List.sublistView(blob, 10 + wl);
  final aead = Chacha20.poly1305Aead();
  const step = chunkSize + 16;
  final out = BytesBuilder();
  var pos = 0, i = 0;
  while (true) {
    final remaining = body.length - pos;
    if (remaining < 16) throw CryptoError('fayl kesilgan');
    final last = remaining <= step;
    final piece = Uint8List.sublistView(body, pos, pos + (last ? remaining : step));
    try {
      final box = SecretBox(piece.sublist(0, piece.length - 16),
          nonce: _chunkNonce(Uint8List.fromList(prefix), i), mac: Mac(piece.sublist(piece.length - 16)));
      out.add(await aead.decrypt(box, secretKey: SecretKey(fk), aad: _chunkAad(last)));
    } catch (_) {
      throw CryptoError('fayl buzilgan yoki kesilgan');
    }
    if (last) return out.toBytes();
    pos += step;
    i++;
  }
}

/// Takroriy yuklashni oldini oluvchi belgi: HMAC(HKDF(MK,"sv-tag-v1"), sha256(mazmun)).
Future<String> contentTag(Uint8List mk, List<int> sha256Bytes) async {
  final k = await Hkdf(hmac: Hmac.sha256(), outputLength: 32)
      .deriveKey(secretKey: SecretKey(mk), nonce: const <int>[], info: utf8.encode('sv-tag-v1'));
  final mac = await Hmac.sha256().calculateMac(sha256Bytes, secretKey: k);
  return hexOf(mac.bytes);
}

Future<List<int>> sha256Of(List<int> data) async => (await Sha256().hash(data)).bytes;

Future<String> encryptJson(Uint8List mk, Map<String, dynamic> obj, String aad) async =>
    b64e(await wrap(mk, utf8.encode(jsonEncode(obj)), aad));

Future<Map<String, dynamic>> decryptJson(Uint8List mk, String s, String aad) async =>
    jsonDecode(utf8.decode(await unwrap(mk, b64d(s), aad))) as Map<String, dynamic>;
