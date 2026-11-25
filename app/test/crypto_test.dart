// Python yadrosi bilan moslik testi. Vektorlar: python tests/gen_vectors.py
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:safevault_app/vault_crypto.dart';

void main() {
  late Map<String, dynamic> v;
  setUpAll(() => v = jsonDecode(File('test/vectors.json').readAsStringSync()) as Map<String, dynamic>);

  test('parol kalitlari Python bilan bir xil (scrypt)', () async {
    final p = v['password'] as Map<String, dynamic>;
    final k = await passwordKeys(p['password'] as String, fromHex(p['salt'] as String), p['kdf'] as Map<String, dynamic>);
    expect(hexOf(k.kek), p['kek']);
    expect(hexOf(k.auth), p['auth']);
  });

  test('tiklash kodi kalitlari Python bilan bir xil (HKDF)', () async {
    final r = v['recovery'] as Map<String, dynamic>;
    final k = await recoveryKeys(r['code'] as String, fromHex(r['salt'] as String));
    expect(hexOf(k.kek), r['kek']);
    expect(hexOf(k.auth), r['auth']);
    final k2 = await recoveryKeys((r['code'] as String).toLowerCase().replaceAll('-', ' '), fromHex(r['salt'] as String));
    expect(hexOf(k2.kek), r['kek']);
  });

  test('Python o\'ragan kalitni ochadi (AES-GCM)', () async {
    final w = v['wrap'] as Map<String, dynamic>;
    final out = await unwrap(fromHex(w['key'] as String), fromHex(w['blob'] as String), w['aad'] as String);
    expect(hexOf(out), w['plaintext']);
  });

  test('Python shifrlagan faylni ochadi (1 va 2 bo\'lak)', () async {
    final f = v['file'] as Map<String, dynamic>;
    expect(hexOf(await decryptFile(fromHex(f['mk'] as String), fromHex(f['blob'] as String))), f['plaintext']);
    final b = v['bigfile'] as Map<String, dynamic>;
    final out = await decryptFile(fromHex(b['mk'] as String), fromHex(b['blob'] as String));
    expect(out.length, b['length']);
    expect(hexOf(await sha256Of(out)), b['sha256']);
  });

  test('takrorlash belgisi (content tag) Python bilan bir xil', () async {
    final t = v['tag'] as Map<String, dynamic>;
    expect(await contentTag(fromHex(t['mk'] as String), fromHex(t['sha256'] as String)), t['tag']);
  });

  test('metama\'lumot JSON ni ochadi', () async {
    final j = v['json'] as Map<String, dynamic>;
    expect(await decryptJson(fromHex(j['mk'] as String), j['blob'] as String, j['aad'] as String), j['obj']);
  });

  test('Dart shifrlab o\'zi ochadi, buzilgan/kesilgan faylni rad etadi', () async {
    final mk = randomBytes(32);
    for (final n in [0, 1, 1000, chunkSize, chunkSize + 1, 2 * chunkSize + 7]) {
      final data = randomBytes(n);
      final blob = await encryptFile(mk, data);
      expect(await decryptFile(mk, blob), data, reason: 'n=$n');
    }
    final blob = await encryptFile(mk, randomBytes(3000));
    final bad = Uint8List.fromList(blob)..[blob.length - 3] ^= 1;
    expect(() => decryptFile(mk, bad), throwsA(isA<CryptoError>()));
    expect(() => decryptFile(randomBytes(32), blob), throwsA(isA<CryptoError>()));
  });

  test('tiklash kodi formati', () {
    final c = newRecoveryCode();
    expect(c.replaceAll('-', '').length, 32);
    expect(RegExp(r'^([A-Z2-7]{4}-){7}[A-Z2-7]{4}$').hasMatch(c), isTrue);
  });
}
