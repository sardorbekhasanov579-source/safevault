// Joylashuv: ruxsat, joriy nuqta va manzil (ko'rish paytida, OpenStreetMap Nominatim).
import 'dart:convert';

import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';

/// Android 10+ da avval "ilova ochiqligida", keyin "doim" ruxsati alohida so'raladi.
Future<bool> requestAlwaysLocationPermission() async {
  final w = await Permission.locationWhenInUse.request();
  if (!w.isGranted) return false;
  final a = await Permission.locationAlways.request();
  return a.isGranted;
}

Future<bool> requestForegroundLocationPermission() async => (await Permission.locationWhenInUse.request()).isGranted;

Future<bool> hasAlwaysLocationPermission() async => Permission.locationAlways.status.isGranted;

/// Joriy nuqta; aniqlab bo'lmasa oxirgi ma'lum nuqta; ruxsat/GPS yo'q bo'lsa null.
Future<Position?> currentPosition() async {
  try {
    if (!await Geolocator.isLocationServiceEnabled()) return null;
    try {
      return await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 30)));
    } catch (_) {
      return await Geolocator.getLastKnownPosition();
    }
  } catch (_) {
    return null; // ruxsat yo'q
  }
}

/// Taxminiy manzil. Koordinata faqat egasi xaritani ochganda OpenStreetMap'ga yuboriladi.
Future<String?> reverseGeocode(double lat, double lon) async {
  try {
    final res = await http.get(
        Uri.https('nominatim.openstreetmap.org', '/reverse',
            {'format': 'jsonv2', 'lat': lat.toStringAsFixed(6), 'lon': lon.toStringAsFixed(6), 'zoom': '18', 'accept-language': 'uz,ru,en'}),
        headers: {'User-Agent': 'SafeVault/0.2 (personal backup app)'}).timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) return null;
    final name = (jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>)['display_name'];
    return name is String ? name : null;
  } catch (_) {
    return null;
  }
}

/// Android 11+ da Yuklamalar/Hujjatlar papkalaridagi boshqa ilovalar fayllarini o'qish uchun («Barcha fayllarga ruxsat»).
Future<bool> ensureAllFilesAccess() async {
  var st = await Permission.manageExternalStorage.status;
  if (!st.isGranted) st = await Permission.manageExternalStorage.request();
  if (!st.isGranted) await openAppSettings();
  return st.isGranted;
}
