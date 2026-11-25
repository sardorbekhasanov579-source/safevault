import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_contacts/flutter_contacts.dart';
import 'package:flutter_map/flutter_map.dart' show FlutterMap, MapOptions, TileLayer, MarkerLayer, Marker;
import 'package:latlong2/latlong.dart' as ll;
import 'package:path_provider/path_provider.dart';
import 'package:photo_manager/photo_manager.dart';

import 'api.dart';
import 'backup.dart';
import 'bg.dart';
import 'geo.dart';
import 'search.dart';
import 'session.dart';
import 'storage.dart';
import 'vault_crypto.dart';

String errText(Object e) {
  if (e is ApiException) {
    switch (e.code) {
      case 'invalid_credentials':
        return "Telefon raqami yoki parol noto'g'ri";
      case 'locked':
        return "Juda ko'p xato urinish. ${((e.body['retry_after'] ?? 900) as int) ~/ 60} daqiqadan keyin urinib ko'ring";
      case 'bad_code':
        return "Kod noto'g'ri yoki muddati o'tgan";
      case 'phone_taken':
        return "Bu raqam allaqachon ro'yxatdan o'tgan";
      case 'too_many_codes':
        return "Juda ko'p kod so'raldi. Biroz kuting";
      default:
        return 'Server xatosi: ${e.code} (${e.status})';
    }
  }
  if (e is CryptoError) return e.message;
  if (e is SocketException || e.toString().contains('TimeoutException')) {
    return "Serverga ulanib bo'lmadi. Manzil va tarmoqni tekshiring";
  }
  return e.toString();
}

String fmtBytes(int b) {
  if (b < 1024) return '$b B';
  if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(1)} KB';
  if (b < 1024 * 1024 * 1024) return '${(b / 1024 / 1024).toStringAsFixed(1)} MB';
  return '${(b / 1024 / 1024 / 1024).toStringAsFixed(2)} GB';
}

String fmtTime(DateTime? t) {
  if (t == null) return 'hali zaxira olinmagan';
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(t.day)}.${two(t.month)}.${t.year} ${two(t.hour)}:${two(t.minute)}';
}

String normalizeServer(String s) {
  s = s.trim();
  if (s.isEmpty) return s;
  if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'http://$s';
  return s.endsWith('/') ? s.substring(0, s.length - 1) : s;
}

// ======================= KIRISH / RO'YXATDAN O'TISH / TIKLASH =======================
enum AuthMode { login, register, recover }

class AuthScreen extends StatefulWidget {
  final String deviceId;
  final String initialServer;
  const AuthScreen({super.key, required this.deviceId, required this.initialServer});
  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  AuthMode mode = AuthMode.login;
  late final server = TextEditingController(text: widget.initialServer);
  final phone = TextEditingController(text: '+998');
  final email = TextEditingController();
  final password = TextEditingController();
  final password2 = TextEditingController();
  final phoneCode = TextEditingController();
  final emailCode = TextEditingController();
  final recoveryCode = TextEditingController();
  bool codesSent = false, newDeviceStep = false, busy = false, hide = true;
  String? error, info;

  VaultSession _session() => VaultSession(Api(normalizeServer(server.text), widget.deviceId));

  Future<void> _run(Future<void> Function() f) async {
    setState(() {
      busy = true;
      error = null;
      info = null;
    });
    try {
      await f();
    } catch (e) {
      error = errText(e);
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> _finish(VaultSession s, {String? newRecoveryCode}) async {
    await AppStore.set('server', s.api.baseUrl);
    await AppStore.clearSession();
    await AppStore.clearBackupCache();
    if (!mounted) return;
    final home = HomeScreen(session: s, biometricOn: false, firstRun: newRecoveryCode != null);
    Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => newRecoveryCode != null ? RecoveryCodeScreen(code: newRecoveryCode, next: home) : home),
        (_) => false);
  }

  Future<void> _sendCodes() => _run(() async {
        final s = _session();
        if (mode == AuthMode.register) {
          if (!email.text.contains('@')) throw 'Gmail manzilini kiriting';
          await s.requestOtp('register', phone.text.trim(), email.text.trim());
        } else {
          await s.requestOtp(mode == AuthMode.recover ? 'recover' : 'new_device', phone.text.trim());
        }
        codesSent = true;
        info = mode == AuthMode.register
            ? 'Telefon va emailga kod yuborildi'
            : (mode == AuthMode.recover ? 'Telefon va emailga kod yuborildi' : 'Telefonga kod yuborildi');
      });

  Future<void> _submit() => _run(() async {
        final s = _session();
        final ph = phone.text.trim();
        if (mode == AuthMode.register) {
          if (password.text.length < 8) throw "Parol kamida 8 ta belgi bo'lsin";
          if (password.text != password2.text) throw 'Parollar bir xil emas';
          final code = await s.register(
              phone: ph, email: email.text.trim(), phoneCode: phoneCode.text.trim(),
              emailCode: emailCode.text.trim(), password: password.text);
          await _finish(s, newRecoveryCode: code);
        } else if (mode == AuthMode.recover) {
          if (password.text.length < 8) throw "Yangi parol kamida 8 ta belgi bo'lsin";
          await s.recover(
              phone: ph, phoneCode: phoneCode.text.trim(), emailCode: emailCode.text.trim(),
              recoveryCode: recoveryCode.text.trim(), newPassword: password.text);
          await _finish(s);
        } else {
          try {
            await s.login(ph, password.text,
                phoneCode: newDeviceStep ? phoneCode.text.trim() : null,
                recoveryCode: newDeviceStep ? recoveryCode.text.trim() : null);
            await _finish(s);
          } on ApiException catch (e) {
            if (e.code == 'new_device_required') {
              newDeviceStep = true;
              info = "Bu yangi qurilma. Telefonga kod yuboring va tiklash kodini kiriting";
            } else {
              rethrow;
            }
          }
        }
      });

  Widget _tf(TextEditingController c, String label,
          {TextInputType? type, bool secret = false, int? maxLen, TextCapitalization cap = TextCapitalization.none}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: TextField(
          controller: c,
          keyboardType: type,
          obscureText: secret && hide,
          maxLength: maxLen,
          textCapitalization: cap,
          decoration: InputDecoration(
              labelText: label,
              border: const OutlineInputBorder(),
              counterText: '',
              suffixIcon: secret
                  ? IconButton(icon: Icon(hide ? Icons.visibility : Icons.visibility_off), onPressed: () => setState(() => hide = !hide))
                  : null),
        ),
      );

  void _setMode(AuthMode m) => setState(() {
        mode = m;
        codesSent = false;
        newDeviceStep = false;
        error = null;
        info = null;
      });

  @override
  Widget build(BuildContext context) {
    final title = {AuthMode.login: 'Kirish', AuthMode.register: "Ro'yxatdan o'tish", AuthMode.recover: 'Parolni tiklash'}[mode]!;
    return Scaffold(
      appBar: AppBar(title: Text('SafeVault — $title')),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          _tf(server, 'Server manzili (masalan 192.168.1.15:8080)', type: TextInputType.url),
          _tf(phone, 'Telefon raqami (+998…)', type: TextInputType.phone),
          if (mode == AuthMode.register) _tf(email, 'Gmail manzili', type: TextInputType.emailAddress),
          if (mode != AuthMode.recover || codesSent)
            _tf(password, mode == AuthMode.recover ? 'Yangi parol' : 'Parol', secret: true),
          if (mode == AuthMode.register) _tf(password2, 'Parolni takrorlang', secret: true),
          if (codesSent || newDeviceStep) ...[
            _tf(phoneCode, 'Telefonga kelgan kod', type: TextInputType.number, maxLen: 6),
            if (mode != AuthMode.login) _tf(emailCode, 'Emailga kelgan kod', type: TextInputType.number, maxLen: 6),
            if (mode != AuthMode.register)
              _tf(recoveryCode, 'Tiklash kodi (XXXX-XXXX-…)', cap: TextCapitalization.characters),
          ],
          if (info != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(info!)),
          if (error != null)
            Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
          if (busy) const LinearProgressIndicator(),
          const SizedBox(height: 8),
          if (mode == AuthMode.login && newDeviceStep) ...[
            OutlinedButton(onPressed: busy ? null : _sendCodes, child: const Text('Telefonga kod yuborish')),
            const SizedBox(height: 8),
          ],
          if (mode != AuthMode.login && !codesSent)
            FilledButton(onPressed: busy ? null : _sendCodes, child: const Text('Kodlarni yuborish'))
          else
            FilledButton(onPressed: busy ? null : _submit, child: Text(title)),
          const SizedBox(height: 12),
          if (mode != AuthMode.login) TextButton(onPressed: () => _setMode(AuthMode.login), child: const Text('Kirishga qaytish')),
          if (mode == AuthMode.login) ...[
            TextButton(onPressed: () => _setMode(AuthMode.register), child: const Text("Hisobim yo'q — ro'yxatdan o'tish")),
            TextButton(onPressed: () => _setMode(AuthMode.recover), child: const Text('Parolni unutdim / telefonim yo\'qolgan')),
          ],
        ]),
      ),
    );
  }
}

// ======================= TIKLASH KODI =======================
class RecoveryCodeScreen extends StatefulWidget {
  final String code;
  final Widget next;
  const RecoveryCodeScreen({super.key, required this.code, required this.next});
  @override
  State<RecoveryCodeScreen> createState() => _RecoveryCodeScreenState();
}

class _RecoveryCodeScreenState extends State<RecoveryCodeScreen> {
  bool saved = false;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Tiklash kodingiz'), automaticallyImplyLeading: false),
        body: SafeArea(
          child: ListView(padding: const EdgeInsets.all(16), children: [
            const Text(
                "Bu kod faqat BIR MARTA ko'rsatiladi. Uni qog'ozga yozib, xavfsiz joyda saqlang. "
                "Telefon yo'qolganda yoki parol esdan chiqqanda ma'lumotlaringizni faqat shu kod bilan tiklaysiz. "
                "Kod ham, parol ham yo'qolsa, fayllaringizni hech kim — biz ham — ocha olmaydi.",
                style: TextStyle(fontSize: 16)),
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: SelectableText(widget.code,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 22, fontFamily: 'monospace', fontWeight: FontWeight.bold, letterSpacing: 1.5)),
              ),
            ),
            CheckboxListTile(
                value: saved,
                onChanged: (v) => setState(() => saved = v ?? false),
                title: const Text("Kodni yozib oldim va saqlab qo'ydim")),
            FilledButton(
                onPressed: saved
                    ? () => Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => widget.next))
                    : null,
                child: const Text('Davom etish')),
          ]),
        ),
      );
}

// ======================= BOSH SAHIFA =======================
class HomeScreen extends StatefulWidget {
  final VaultSession session;
  final bool biometricOn;
  final bool firstRun;
  const HomeScreen({super.key, required this.session, required this.biometricOn, this.firstRun = false});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  VaultStatus? status;
  Map<String, int> perCat = {};
  String? progress, message, loadError;
  bool busy = false;
  late bool bio = widget.biometricOn;
  bool autoOn = false, wifiOnly = true, locOn = false;
  AutoRun? autoRun, locRun;

  @override
  void initState() {
    super.initState();
    _refresh();
    _syncAuto();
    if (widget.firstRun) {
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        await Navigator.of(context).push(MaterialPageRoute(builder: (_) => BackupSettingsScreen(session: widget.session, firstRun: true)));
        _refresh();
      });
    }
  }

  Future<void> _syncAuto() async {
    final on = await AppStore.autoEnabled();
    final lo = await AppStore.locationEnabled();
    if (on || lo) await AppStore.writeBg(widget.session); // token yangi bo'lib turadi
    final w = await AppStore.wifiOnly();
    final r = await AppStore.lastAutoRun();
    final lr = await AppStore.lastLocRun();
    if (mounted) setState(() {
          autoOn = on;
          locOn = lo;
          wifiOnly = w;
          autoRun = r;
          locRun = lr;
        });
  }

  Future<void> _refresh() async {
    _syncAuto();
    try {
      final st = await widget.session.status();
      final files = await widget.session.listFiles();
      final m = <String, int>{};
      for (final f in files) {
        m[f.category] = (m[f.category] ?? 0) + 1;
      }
      if (mounted) setState(() {
            status = st;
            perCat = m;
            loadError = null;
          });
    } catch (e) {
      if (mounted) setState(() => loadError = errText(e));
    }
  }

  Future<void> _backupNow() async {
    final cats = await AppStore.categories();
    if (cats.isEmpty) {
      setState(() => message = 'Avval nimalar zaxiralanishini tanlang');
      return;
    }
    setState(() {
      busy = true;
      message = null;
    });
    try {
      final r = await BackupService(widget.session, (p) {
        if (mounted) setState(() => progress = p);
      }).run(cats);
      message = r.summary + (r.notes.isEmpty ? '' : '\n${r.notes.take(3).join("\n")}');
    } catch (e) {
      message = errText(e);
    }
    progress = null;
    if (mounted) setState(() => busy = false);
    _refresh();
  }

  Future<void> _toggleAuto(bool on) async {
    if (on) {
      final cats = await AppStore.categories();
      if (cats.isEmpty) {
        setState(() => message = "Avval 'Nimalar zaxiralansin' bo'limida tanlang");
        return;
      }
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Avtomatik zaxira'),
          content: const Text(
              "Ilova ochiq bo'lmasa ham, internet bor paytda yangi rasm va fayllar o'zi shifrlanib yuklanadi.\n\n"
              "Buning uchun shifrlash kaliti shu telefonning himoyalangan xotirasida (Android Keystore) saqlanadi, "
              "shunda ilova parolsiz ishlay oladi. Istagan paytingizda o'chirishingiz mumkin.\n\n"
              "Rasmlar uchun ruxsatni 'Hammasiga ruxsat' qilib bering, 'Tanlanganlar' bo'lsa yangi rasmlar ko'rinmaydi."),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Bekor qilish')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Yoqish')),
          ],
        ),
      );
      if (ok != true) return;
      try {
        await AppStore.writeBg(widget.session);
        await AppStore.setAuto(true);
        await scheduleAutoBackup(wifiOnly: wifiOnly);
        await runAutoBackupNow();
        setState(() {
          autoOn = true;
          message = "Avtomatik zaxira yoqildi. Birinchi yuklash bir necha daqiqadan keyin boshlanadi.";
        });
        if (mounted) await _showBatteryHelp();
      } catch (e) {
        await AppStore.setAuto(false);
        if (!await AppStore.locationEnabled()) await AppStore.deleteBg();
        setState(() => message = "Avtomatik zaxirani yoqib bo'lmadi: $e");
      }
    } else {
      try {
        await cancelAutoBackup();
      } catch (_) {}
      await AppStore.setAuto(false);
      if (!await AppStore.locationEnabled()) await AppStore.deleteBg();
      setState(() => autoOn = false);
    }
  }

  Future<void> _toggleLoc(bool on) async {
    if (on) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Joylashuvni yuborish'),
          content: const Text(
              "Telefon yo'qolsa topishingiz uchun ilova har ~30 daqiqada telefon joylashuvini shifrlab serverga yuboradi. "
              "Uni faqat siz (ilova yoki Telegram bot orqali) ko'ra olasiz.\n\n"
              "Buning uchun ikki bosqichli ruxsat so'raladi: avval 'ilova ochiqligida', keyin 'Doim ruxsat berish' (Allow all the time).\n\n"
              "Cheklov: telefon o'chiq yoki internetsiz bo'lsa, faqat OXIRGI yuborilgan joy ko'rinadi. "
              "Istagan paytda o'chirishingiz mumkin; holat shu sahifada doim ko'rinib turadi."),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Bekor qilish')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Davom etish')),
          ],
        ),
      );
      if (ok != true) return;
      if (!await requestAlwaysLocationPermission()) {
        setState(() => message = "Doimiy joylashuv ruxsati berilmadi. Telefon sozlamalari → Ilovalar → SafeVault → Ruxsatlar → Joylashuv → 'Doim ruxsat berish'.");
        return;
      }
      try {
        await AppStore.writeBg(widget.session);
        await AppStore.setLocationEnabled(true);
        await scheduleLocation();
        await sendLocationNow();
        setState(() {
          locOn = true;
          message = "Joylashuvni yuborish yoqildi. Birinchi nuqta bir necha daqiqadan keyin yuboriladi.";
        });
      } catch (e) {
        await AppStore.setLocationEnabled(false);
        if (!await AppStore.autoEnabled()) await AppStore.deleteBg();
        setState(() => message = "Joylashuvni yoqib bo'lmadi: $e");
      }
    } else {
      try {
        await cancelLocation();
      } catch (_) {}
      await AppStore.setLocationEnabled(false);
      if (!await AppStore.autoEnabled()) await AppStore.deleteBg();
      setState(() => locOn = false);
    }
  }

  Future<void> _toggleWifi(bool v) async {
    await AppStore.setWifiOnly(v);
    setState(() => wifiOnly = v);
    if (autoOn) {
      try {
        await scheduleAutoBackup(wifiOnly: v);
      } catch (_) {}
    }
  }

  Future<void> _showBatteryHelp() => showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Muhim: batareya sozlamasi'),
          content: const Text(
              "Xiaomi, Samsung, Huawei, Oppo, Vivo telefonlari fon ishini o'zi to'xtatib qo'yadi. "
              "Zaxira muntazam ishlashi uchun:\n\n"
              "Sozlamalar → Ilovalar → SafeVault → Batareya → 'Cheklovsiz' (Unrestricted) ni tanlang.\n\n"
              "Xiaomi'da qo'shimcha: 'Avtomatik ishga tushirish' (Autostart) ni yoqing va ilovani 'Oxirgi ilovalar' "
              "ro'yxatida qulflab qo'ying."),
          actions: [FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Tushundim'))],
        ),
      );

  Future<void> _toggleBio(bool on) async {
    if (on) {
      if (!await authenticateWithBiometrics()) {
        setState(() => message = 'Barmoq izi tasdiqlanmadi yoki qurilmada sozlanmagan');
        return;
      }
      await AppStore.set('token', widget.session.api.token!);
      await AppStore.set('mk', b64e(widget.session.mk!));
    } else {
      await AppStore.clearSession();
    }
    setState(() => bio = on);
  }

  Future<void> _logout() async {
    try {
      await cancelAutoBackup();
      await cancelLocation();
    } catch (_) {}
    await AppStore.setAuto(false);
    await AppStore.setLocationEnabled(false);
    await AppStore.deleteBg();
    await AppStore.clearSession();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
            builder: (_) => AuthScreen(deviceId: widget.session.api.deviceId, initialServer: widget.session.api.baseUrl)),
        (_) => false);
  }

  static const catNames = {'photo': 'Rasmlar', 'video': 'Videolar', 'contact': 'Kontaktlar', 'document': 'Hujjatlar'};

  @override
  Widget build(BuildContext context) {
    final st = status;
    return Scaffold(
      appBar: AppBar(title: const Text('SafeVault'), actions: [
        IconButton(icon: const Icon(Icons.logout), tooltip: 'Chiqish', onPressed: _logout),
      ]),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: st == null
                  ? Text(loadError ?? 'Yuklanmoqda…')
                  : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('Saqlangan fayllar: ${st.fileCount} (${fmtBytes(st.totalBytes)})',
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 6),
                      Text('Oxirgi zaxira: ${fmtTime(st.lastBackup)}'),
                      const SizedBox(height: 8),
                      Wrap(spacing: 8, children: [
                        for (final e in catNames.entries) Chip(label: Text('${e.value}: ${perCat[e.key] ?? 0}')),
                      ]),
                    ]),
            ),
          ),
          const SizedBox(height: 12),
          if (busy) ...[const LinearProgressIndicator(), Padding(padding: const EdgeInsets.all(8), child: Text(progress ?? 'Boshlanmoqda…'))],
          if (message != null) Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(message!)),
          FilledButton.icon(
              onPressed: busy ? null : _backupNow, icon: const Icon(Icons.cloud_upload), label: const Text('Hozir zaxiralash')),
          const SizedBox(height: 8),
          OutlinedButton.icon(
              onPressed: busy
                  ? null
                  : () async {
                      await Navigator.of(context).push(MaterialPageRoute(builder: (_) => BackupSettingsScreen(session: widget.session)));
                      _refresh();
                    },
              icon: const Icon(Icons.tune),
              label: const Text('Nimalar zaxiralansin')),
          const SizedBox(height: 8),
          OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => FilesScreen(session: widget.session))),
              icon: const Icon(Icons.folder_open),
              label: const Text('Saqlangan fayllar va tiklash')),
          SwitchListTile(
              value: autoOn,
              onChanged: busy ? null : _toggleAuto,
              title: const Text('Avtomatik zaxira (fonda)'),
              subtitle: Text(autoOn
                  ? (autoRun == null
                      ? "Yoqilgan. Birinchi ishga tushishni kutmoqda…"
                      : "Oxirgi tekshiruv: ${fmtTime(autoRun!.time)}\n${autoRun!.message}")
                  : "Yangi rasm va fayllar internet bor paytda o'zi yuklanadi")),
          if (autoOn) ...[
            SwitchListTile(
                value: wifiOnly,
                onChanged: _toggleWifi,
                title: const Text('Faqat Wi-Fi orqali'),
                subtitle: const Text("O'chirilsa, mobil internet ham ishlatiladi (trafik sarflaydi)")),
            TextButton(onPressed: _showBatteryHelp, child: const Text("Zaxira to'xtab qolsa: batareya sozlamasi")),
          ],
          SwitchListTile(
              value: locOn,
              onChanged: busy ? null : _toggleLoc,
              title: const Text('Joylashuvni yuborish'),
              subtitle: Text(locOn
                  ? (locRun == null
                      ? "Yoqilgan. Birinchi nuqtani kutmoqda…"
                      : "Oxirgi urinish: ${fmtTime(locRun!.time)}\n${locRun!.message}")
                  : "Telefon yo'qolsa, oxirgi joyini xaritada ko'rish uchun")),
          OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => LocationScreen(session: widget.session))),
              icon: const Icon(Icons.map),
              label: const Text('Telefon joylashuvi (xarita)')),
          SwitchListTile(
              value: bio,
              onChanged: _toggleBio,
              title: const Text('Barmoq izi bilan kirish'),
              subtitle: const Text('Kalit shu telefonning himoyalangan xotirasida saqlanadi')),
          const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text(
                  "Avtomatik zaxira rasm, video, kontaktlar va (yoqilgan bo'lsa) Yuklamalar/Hujjatlar papkalaridagi hujjatlarni oladi.",
                  style: TextStyle(fontSize: 12))),
        ]),
      ),
    );
  }
}

// ======================= ZAXIRA SOZLAMALARI =======================
class BackupSettingsScreen extends StatefulWidget {
  final VaultSession session;
  final bool firstRun;
  const BackupSettingsScreen({super.key, required this.session, this.firstRun = false});
  @override
  State<BackupSettingsScreen> createState() => _BackupSettingsScreenState();
}

class _BackupSettingsScreenState extends State<BackupSettingsScreen> {
  Set<String> cats = {};
  String? message;
  bool busy = false;

  static const why = {
    'photo': ("Rasmlar", "Telefon yo'qolsa yoki almashtirsangiz, rasmlaringizni yangi telefonga qaytarish uchun. Fayllar telefondan chiqishdan oldin shifrlanadi."),
    'video': ("Videolar", "Videolaringizni ham shu tarzda saqlash uchun. Katta videolar ko'p internet sarflaydi; keyingi versiyada faqat Wi-Fi rejimi qo'shiladi."),
    'contact': ("Kontaktlar", "Telefon raqamlaringiz yo'qolib qolmasligi uchun. Ular bitta shifrlangan fayl (.vcf) bo'lib saqlanadi."),
    'document': ("Hujjatlar", "Yuklamalar va Hujjatlar papkalaridagi PDF, Word, slayd, Excel fayllarini o'zi saqlaydi. Buning uchun «Barcha fayllarga ruxsat» kerak. Boshqa papkadagi hujjatni pastdagi tugma bilan tanlang."),
  };

  @override
  void initState() {
    super.initState();
    AppStore.categories().then((c) => setState(() => cats = c));
  }

  Future<bool> _ensurePermission(String cat) async {
    switch (cat) {
      case 'photo':
      case 'video':
        final r = await PhotoManager.requestPermissionExtend();
        if (!r.hasAccess) PhotoManager.openSetting();
        return r.hasAccess;
      case 'contact':
        return FlutterContacts.requestPermission(readonly: true);
      case 'document':
        return ensureAllFilesAccess();
      default:
        return true;
    }
  }

  Future<void> _toggle(String cat, bool on) async {
    if (!on) {
      setState(() => cats = {...cats}..remove(cat));
      await AppStore.setCategories(cats);
      return;
    }
    // Tushuntirish — har bir tur uchun faqat bir marta; ruxsat berilgan bo'lsa qayta so'ralmaydi.
    if (!await AppStore.wasExplained(cat)) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text('${why[cat]!.$1} uchun ruxsat'),
          content: Text(why[cat]!.$2),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Bekor qilish')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Davom etish')),
          ],
        ),
      );
      if (ok != true) return;
      await AppStore.markExplained(cat);
    }
    if (!await _ensurePermission(cat)) {
      setState(() => message = "Ruxsat berilmadi. Telefon sozlamalaridan ruxsat bersangiz, qayta yoqing.");
      return;
    }
    setState(() => cats = {...cats, cat});
    await AppStore.setCategories(cats);
  }

  Future<void> _pickDocs() async {
    final r = await FilePicker.platform.pickFiles(allowMultiple: true);
    if (r == null) return;
    setState(() {
      busy = true;
      message = null;
    });
    try {
      final res = await BackupService(widget.session, (p) {
        if (mounted) setState(() => message = p);
      }).documents(r.files.map((f) => f.path).whereType<String>().toList());
      message = res.summary;
    } catch (e) {
      message = errText(e);
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.firstRun ? 'Birinchi sozlash' : 'Nimalar zaxiralansin')),
        body: SafeArea(
          child: ListView(padding: const EdgeInsets.all(8), children: [
            if (widget.firstRun)
              const Padding(
                  padding: EdgeInsets.all(8),
                  child: Text("Qaysi ma'lumotlar zaxiralanishini o'zingiz tanlang. Buni keyin ham o'zgartirish mumkin.")),
            for (final e in why.entries)
              SwitchListTile(
                  value: cats.contains(e.key) || (e.key == 'document' && cats.contains('document')),
                  onChanged: busy ? null : (v) => _toggle(e.key, v),
                  title: Text(e.value.$1),
                  subtitle: Text(e.value.$2)),
            Padding(
              padding: const EdgeInsets.all(12),
              child: OutlinedButton.icon(
                  onPressed: busy ? null : _pickDocs, icon: const Icon(Icons.upload_file), label: const Text('Hujjat tanlab zaxiralash')),
            ),
            if (busy) const LinearProgressIndicator(),
            if (message != null) Padding(padding: const EdgeInsets.all(12), child: Text(message!)),
            Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton(onPressed: () => Navigator.pop(context), child: Text(widget.firstRun ? 'Tayyor' : 'Orqaga'))),
          ]),
        ),
      );
}

// ======================= SAQLANGAN FAYLLAR =======================
class FilesScreen extends StatefulWidget {
  final VaultSession session;
  const FilesScreen({super.key, required this.session});
  @override
  State<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends State<FilesScreen> {
  List<RemoteFile>? files;
  String? error;
  String? busyId;
  String? bulkProgress;
  String category = 'all'; // all | photo | video | document | contact
  final queryCtl = TextEditingController();
  SearchOutcome? found; // matn yozilgan bo'lsa, qidiruv natijasi

  @override
  void initState() {
    super.initState();
    widget.session.listFiles().then((f) {
      f.sort((a, b) => b.uploadedAt.compareTo(a.uploadedAt));
      if (mounted) setState(() => files = f);
    }).catchError((e) {
      if (mounted) setState(() => error = errText(e as Object));
    });
  }

  @override
  void dispose() {
    queryCtl.dispose();
    super.dispose();
  }

  void _search(String text) {
    if (files == null) return;
    final q = text.trim();
    setState(() => found = q.isEmpty ? null : searchFiles(files!, parseQuery(q, DateTime.now())));
  }

  /// Hozir ekranda ko'rinib turgan fayllar (qidiruv + toifa filtri).
  List<RemoteFile> get visible {
    final base = found != null ? found!.files : files!;
    return category == 'all' ? base : base.where((f) => f.category == category).toList();
  }

  Future<String> _restoreOne(RemoteFile f) async {
    try {
      final data = await widget.session.restore(f.id);
      if (f.category == 'photo') {
        await PhotoManager.editor.saveImage(data, filename: f.name, title: f.name);
        return 'Galereyaga tiklandi: ${f.name}';
      }
      final base = await getExternalStorageDirectory() ?? await getApplicationDocumentsDirectory();
      final dir = Directory('${base.path}/SafeVault')..createSync(recursive: true);
      final out = File('${dir.path}/${f.name}')..writeAsBytesSync(data);
      if (f.category == 'video') {
        await PhotoManager.editor.saveVideo(out, title: f.name);
        return 'Galereyaga tiklandi: ${f.name}';
      }
      return 'Saqlandi: ${out.path}';
    } catch (e) {
      return errText(e);
    }
  }

  Future<void> _restore(RemoteFile f) async {
    setState(() => busyId = f.id);
    final msg = await _restoreOne(f);
    if (!mounted) return;
    setState(() => busyId = null);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  /// Ko'rinib turgan hamma faylni ketma-ket tiklaydi (rasm/video galereyaga, qolganlari SafeVault papkasiga).
  Future<void> _restoreAll() async {
    final list = visible;
    if (list.isEmpty) return;
    final total = list.fold<int>(0, (sum, f) => sum + f.size);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Hammasini yuklab olish'),
        content: Text("${list.length} ta fayl (${fmtBytes(total)}) telefonga tiklanadi. "
            "Rasm va videolar galereyaga qo'shiladi (telefonda allaqachon bo'lsa, nusxa paydo bo'lishi mumkin). "
            "Hujjat va kontaktlar SafeVault papkasiga saqlanadi.\n\nIlovani yopmay turing."),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Bekor qilish')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Boshlash')),
        ],
      ),
    );
    if (ok != true) return;
    var done = 0, failed = 0;
    for (final f in list) {
      if (!mounted) return;
      setState(() => bulkProgress = 'Yuklanmoqda: ${done + failed + 1} / ${list.length}');
      final msg = await _restoreOne(f);
      if (msg.startsWith('Galereyaga') || msg.startsWith('Saqlandi')) {
        done++;
      } else {
        failed++;
      }
    }
    if (!mounted) return;
    setState(() => bulkProgress = null);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Tayyor: $done ta tiklandi' + (failed > 0 ? ', $failed ta xato' : '') + '.')));
  }

  Future<void> _openContacts(RemoteFile f) async {
    setState(() => busyId = f.id);
    try {
      final data = await widget.session.restore(f.id);
      if (!mounted) return;
      setState(() => busyId = null);
      await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ContactsScreen(vcf: utf8.decode(data, allowMalformed: true), file: f)));
    } catch (e) {
      if (!mounted) return;
      setState(() => busyId = null);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(errText(e))));
    }
  }

  static const icons = {
    'photo': Icons.image,
    'video': Icons.videocam,
    'contact': Icons.contacts,
    'document': Icons.description,
  };
  static const chips = [
    ['all', 'Hammasi'],
    ['photo', 'Rasm'],
    ['video', 'Video'],
    ['document', 'Hujjat'],
    ['contact', 'Kontakt'],
  ];

  @override
  Widget build(BuildContext context) {
    final ready = files != null;
    final list = ready ? visible : <RemoteFile>[];
    return Scaffold(
      appBar: AppBar(title: const Text('Saqlangan fayllar'), actions: [
        IconButton(
            icon: const Icon(Icons.download_for_offline),
            tooltip: 'Ko\'rinib turganlarini hammasini yuklab olish',
            onPressed: ready && bulkProgress == null && list.isNotEmpty ? _restoreAll : null),
      ]),
      body: !ready
          ? Center(child: error != null ? Text(error!) : const CircularProgressIndicator())
          : Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
                child: TextField(
                  controller: queryCtl,
                  textInputAction: TextInputAction.search,
                  onChanged: _search,
                  decoration: InputDecoration(
                    hintText: "Masalan: o'tgan oy saqlagan diplomim",
                    prefixIcon: const Icon(Icons.search),
                    suffixIcon: queryCtl.text.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.clear),
                            onPressed: () {
                              queryCtl.clear();
                              _search('');
                            }),
                    border: const OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
              ),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Row(children: [
                  for (final c in chips)
                    Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: ChoiceChip(label: Text(c[1]), selected: category == c[0], onSelected: (_) => setState(() => category = c[0]))),
                ]),
              ),
              if (bulkProgress != null) Padding(padding: const EdgeInsets.all(8), child: Text(bulkProgress!)),
              if (found != null && found!.note.isNotEmpty)
                Padding(padding: const EdgeInsets.fromLTRB(12, 4, 12, 4), child: Text(found!.note, style: const TextStyle(fontSize: 12))),
              Expanded(
                child: list.isEmpty
                    ? Center(
                        child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Text(files!.isEmpty ? "Hali fayl saqlanmagan" : "Hech narsa topilmadi. Qidiruvni qisqartiring yoki toifani 'Hammasi' qiling.")))
                    : ListView.builder(
                        itemCount: list.length,
                        itemBuilder: (_, i) {
                          final f = list[i];
                          final isContacts = f.category == 'contact';
                          return ListTile(
                            leading: Icon(icons[f.category] ?? Icons.insert_drive_file),
                            title: Text(f.name),
                            subtitle: Text(
                                '${fmtBytes(f.size)} · ${fmtTime(DateTime.fromMillisecondsSinceEpoch((f.uploadedAt * 1000).round()))}'),
                            onTap: isContacts && busyId == null ? () => _openContacts(f) : null,
                            trailing: busyId == f.id
                                ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                                : IconButton(icon: const Icon(Icons.download), tooltip: 'Tiklash', onPressed: busyId == null ? () => _restore(f) : null),
                          );
                        },
                      ),
              ),
            ]),
    );
  }
}

// ======================= KONTAKTLAR RO'YXATI =======================
class ContactsScreen extends StatefulWidget {
  final String vcf;
  final RemoteFile file;
  const ContactsScreen({super.key, required this.vcf, required this.file});
  @override
  State<ContactsScreen> createState() => _ContactsScreenState();
}

class _ContactsScreenState extends State<ContactsScreen> {
  late final List<VcfContact> all = parseVcf(widget.vcf);
  String query = '';

  @override
  Widget build(BuildContext context) {
    final list = filterContacts(all, query);
    return Scaffold(
      appBar: AppBar(title: Text('Kontaktlar (${all.length})')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            onChanged: (v) => setState(() => query = v),
            decoration: const InputDecoration(hintText: 'Ism yoki raqam bo\'yicha qidirish', prefixIcon: Icon(Icons.search), border: OutlineInputBorder(), isDense: true),
          ),
        ),
        Expanded(
          child: list.isEmpty
              ? const Center(child: Text('Kontakt topilmadi'))
              : ListView.builder(
                  itemCount: list.length,
                  itemBuilder: (_, i) => ListTile(
                    leading: const Icon(Icons.person),
                    title: Text(list[i].name.isEmpty ? '(ismsiz)' : list[i].name),
                    subtitle: Text(list[i].tels.isEmpty ? "raqam yo'q" : list[i].tels.join('\n')),
                    isThreeLine: list[i].tels.length > 1,
                  ),
                ),
        ),
        const Padding(
            padding: EdgeInsets.all(8),
            child: Text("Telefonga qaytarish uchun 'Saqlangan fayllar' ro'yxatida kontaktlar faylidagi yuklab olish tugmasini bosing, so'ng .vcf faylni oching.",
                style: TextStyle(fontSize: 12))),
      ]),
    );
  }
}


// ======================= TELEFON JOYLASHUVI (XARITA) =======================
String agoText(DateTime t) {
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 1) return 'hozirgina';
  if (d.inMinutes < 60) return '${d.inMinutes} daqiqa oldin';
  if (d.inHours < 24) return '${d.inHours} soat oldin';
  return '${d.inDays} kun oldin';
}

class LocationScreen extends StatefulWidget {
  final VaultSession session;
  const LocationScreen({super.key, required this.session});
  @override
  State<LocationScreen> createState() => _LocationScreenState();
}

class _LocationScreenState extends State<LocationScreen> {
  PhoneLocation? loc;
  String? address, error, info;
  bool loading = true, sending = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final l = await widget.session.getLocation();
      final a = l == null ? null : (l.addr ?? await reverseGeocode(l.lat, l.lon));
      if (!mounted) return;
      setState(() {
        loc = l;
        address = a;
      });
    } catch (e) {
      if (mounted) setState(() => error = errText(e));
    }
    if (mounted) setState(() => loading = false);
  }

  /// Shu telefon joylashuvini hozir yuboradi (sinash uchun; boshqa telefondan qidirilayotgan bo'lsa kerak emas).
  Future<void> _sendNow() async {
    setState(() {
      sending = true;
      info = null;
    });
    try {
      if (!await requestForegroundLocationPermission()) {
        info = "Joylashuv ruxsati berilmadi";
      } else {
        final p = await currentPosition();
        if (p == null) {
          info = "Joylashuvni aniqlab bo'lmadi (GPS yoqilganini tekshiring)";
        } else {
          await widget.session.sendLocation(p.latitude, p.longitude, p.accuracy);
          info = 'Yuborildi';
          await _load();
        }
      }
    } catch (e) {
      info = errText(e);
    }
    if (mounted) setState(() => sending = false);
  }

  @override
  Widget build(BuildContext context) {
    final l = loc;
    return Scaffold(
      appBar: AppBar(title: const Text('Telefon joylashuvi'), actions: [
        IconButton(icon: const Icon(Icons.refresh), tooltip: 'Yangilash', onPressed: loading ? null : _load),
      ]),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(12), children: [
              if (error != null) Padding(padding: const EdgeInsets.all(8), child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
              if (l == null && error == null)
                const Padding(
                    padding: EdgeInsets.all(8),
                    child: Text("Hali joylashuv yuborilmagan. Telefondagi ilovada 'Joylashuvni yuborish' ni yoqing.")),
              if (l != null) ...[
                SizedBox(
                  height: 320,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Stack(children: [
                      FlutterMap(
                        key: ValueKey('${l.lat},${l.lon}'),
                        options: MapOptions(initialCenter: ll.LatLng(l.lat, l.lon), initialZoom: 15),
                        children: [
                          TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', userAgentPackageName: 'uz.safevault.safevault_app'),
                          MarkerLayer(markers: [
                            Marker(
                                point: ll.LatLng(l.lat, l.lon),
                                width: 44,
                                height: 44,
                                child: const Icon(Icons.location_on, size: 44, color: Colors.red)),
                          ]),
                        ],
                      ),
                      const Positioned(
                          right: 4,
                          bottom: 2,
                          child: Text('© OpenStreetMap', style: TextStyle(fontSize: 10, backgroundColor: Colors.white70))),
                    ]),
                  ),
                ),
                const SizedBox(height: 12),
                ListTile(
                    leading: const Icon(Icons.place),
                    title: Text(address ?? "Manzil aniqlanmadi"),
                    subtitle: Text('${l.lat.toStringAsFixed(5)}, ${l.lon.toStringAsFixed(5)}')),
                ListTile(
                    leading: const Icon(Icons.access_time),
                    title: Text('Yangilangan: ${fmtTime(l.updatedAt)}'),
                    subtitle: Text('${agoText(l.updatedAt)}${l.acc == null ? "" : " · aniqlik ~${l.acc!.round()} m"}')),
                const Padding(
                    padding: EdgeInsets.all(8),
                    child: Text("Bu telefon OXIRGI yuborgan joy; u hozir shu yerda bo'lmasligi mumkin. Manzil taxminiy.", style: TextStyle(fontSize: 12))),
              ],
              if (info != null) Padding(padding: const EdgeInsets.all(8), child: Text(info!)),
              OutlinedButton.icon(
                  onPressed: sending ? null : _sendNow,
                  icon: const Icon(Icons.my_location),
                  label: const Text('Shu telefon joylashuvini hozir yuborish')),
            ]),
    );
  }
}
