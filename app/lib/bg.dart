// Fon (avtomatik) zaxira: Android WorkManager har ~30 daqiqada, internet bor va batareya past bo'lmaganda ishga tushiradi.
import 'dart:ui';

import 'package:flutter/widgets.dart';
import 'package:workmanager/workmanager.dart';

import 'api.dart';
import 'backup.dart';
import 'geo.dart';
import 'session.dart';
import 'storage.dart';
import 'vault_crypto.dart';

const bgTaskName = 'safevault_backup';
const bgUniqueName = 'safevault_backup_periodic';
const locTaskName = 'safevault_location';
const locUniqueName = 'safevault_location_periodic';

@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    WidgetsFlutterBinding.ensureInitialized();
    DartPluginRegistrant.ensureInitialized();
    try {
      if (task == locTaskName) return await runBackgroundLocation();
      return await runBackgroundBackup();
    } catch (e) {
      await AppStore.recordAutoRun('Xato: ${e.runtimeType}');
      return false; // keyinroq qayta uriniladi
    }
  });
}

/// true — vazifa tugadi (yoki qayta urinishning foydasi yo'q); false — keyinroq qayta uringin.
Future<bool> runBackgroundBackup() async {
  if (!await AppStore.autoEnabled()) return true;
  final creds = await AppStore.readBg();
  if (creds == null) {
    await AppStore.recordAutoRun('Kirish ma\'lumoti yo\'q: ilovani oching va qayta yoqing');
    return true;
  }
  final cats = await AppStore.categories();
  if (cats.isEmpty) return true;
  final session = VaultSession(Api(creds.server, creds.deviceId, token: creds.token))..mk = b64d(creds.mk);
  final res = await BackupService(session, (_) {}, background: true, budget: const Duration(minutes: 8)).run(cats);
  if (res.authFailed) {
    await AppStore.recordAutoRun('Qayta kirish kerak: ilovani ochib hisobga kiring');
    return true;
  }
  final changed = res.uploaded + res.failed + res.tooBig > 0 || res.partial;
  await AppStore.recordAutoRun(changed ? res.summary : 'Yangi fayl yo\'q');
  return !res.networkDown;
}

/// Telefonning joriy joylashuvini shifrlab serverga yuboradi (egasi yoqqan bo'lsagina).
Future<bool> runBackgroundLocation() async {
  if (!await AppStore.locationEnabled()) return true;
  final creds = await AppStore.readBg();
  if (creds == null) {
    await AppStore.recordLocRun("Kirish ma'lumoti yo'q: ilovani oching va qayta yoqing");
    return true;
  }
  final pos = await currentPosition();
  if (pos == null) {
    await AppStore.recordLocRun("Joylashuvni aniqlab bo'lmadi (GPS yoki 'doim' ruxsatini tekshiring)");
    return true;
  }
  final session = VaultSession(Api(creds.server, creds.deviceId, token: creds.token))..mk = b64d(creds.mk);
  try {
    await session.sendLocation(pos.latitude, pos.longitude, pos.accuracy);
    await AppStore.recordLocRun('Yuborildi');
    return true;
  } on ApiException catch (e) {
    await AppStore.recordLocRun(e.status == 401 ? 'Qayta kirish kerak: ilovani ochib hisobga kiring' : 'Server xatosi: ${e.code}');
    return e.status != 401;
  } catch (_) {
    return false; // tarmoq yo'q: keyinroq qayta uriniladi
  }
}

Future<void> initBackground() => Workmanager().initialize(callbackDispatcher);

Future<void> scheduleAutoBackup({required bool wifiOnly}) async {
  await Workmanager().initialize(callbackDispatcher);
  await Workmanager().registerPeriodicTask(
    bgUniqueName,
    bgTaskName,
    frequency: const Duration(minutes: 30),
    constraints: Constraints(
      networkType: wifiOnly ? NetworkType.unmetered : NetworkType.connected,
      requiresBatteryNotLow: true,
    ),
    existingWorkPolicy: ExistingPeriodicWorkPolicy.update,
  );
}

/// Yoqilgandan keyin darrov bir marta ishga tushiradi (30 daqiqa kutib o'tirmaslik uchun).
Future<void> runAutoBackupNow() => Workmanager().registerOneOffTask('safevault_backup_now', bgTaskName);

Future<void> scheduleLocation() async {
  await Workmanager().initialize(callbackDispatcher);
  await Workmanager().registerPeriodicTask(
    locUniqueName,
    locTaskName,
    frequency: const Duration(minutes: 30),
    constraints: Constraints(networkType: NetworkType.connected),
    existingWorkPolicy: ExistingPeriodicWorkPolicy.update,
  );
}

Future<void> sendLocationNow() => Workmanager().registerOneOffTask('safevault_location_now', locTaskName);

Future<void> cancelLocation() => Workmanager().cancelByUniqueName(locUniqueName);

Future<void> cancelAutoBackup() => Workmanager().cancelByUniqueName(bgUniqueName);
