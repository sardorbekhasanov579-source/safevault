import 'package:flutter/material.dart';

import 'api.dart';
import 'bg.dart';
import 'screens.dart';
import 'session.dart';
import 'storage.dart';
import 'vault_crypto.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    await initBackground();
  } catch (_) {
    // fon xizmati ishga tushmasa ham ilova ishlayveradi
  }
  runApp(const SafeVaultApp());
}

class SafeVaultApp extends StatelessWidget {
  const SafeVaultApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'SafeVault',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorSchemeSeed: const Color(0xFF1B6EF3), useMaterial3: true),
        home: const Boot(),
      );
}

/// Ilova ochilganda: saqlangan sessiya + barmoq izi bo'lsa to'g'ridan-to'g'ri ichkariga, aks holda kirish.
class Boot extends StatefulWidget {
  const Boot({super.key});
  @override
  State<Boot> createState() => _BootState();
}

class _BootState extends State<Boot> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _init());
  }

  Future<void> _init() async {
    final deviceId = await AppStore.deviceId();
    final server = await AppStore.get('server') ?? '';
    final token = await AppStore.get('token');
    final mkB64 = await AppStore.get('mk');
    Widget next = AuthScreen(deviceId: deviceId, initialServer: server);
    if (token != null && mkB64 != null && server.isNotEmpty && await authenticateWithBiometrics()) {
      final s = VaultSession(Api(server, deviceId, token: token))..mk = b64d(mkB64);
      next = HomeScreen(session: s, biometricOn: true);
    }
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => next));
  }

  @override
  Widget build(BuildContext context) => const Scaffold(body: Center(child: CircularProgressIndicator()));
}
