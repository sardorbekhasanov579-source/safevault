import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  final int status;
  final Map<String, dynamic> body;
  ApiException(this.status, this.body);
  String get code => (body['error'] ?? '') as String;
  @override
  String toString() => 'ApiException($status, $code)';
}

class Api {
  String baseUrl;
  final String deviceId;
  String? token;
  Api(this.baseUrl, this.deviceId, {this.token});

  static const _timeout = Duration(seconds: 60);

  Map<String, String> get _auth => token == null ? {} : {'Authorization': 'Bearer $token'};

  Map<String, dynamic> _decode(http.Response res) {
    Map<String, dynamic> m;
    try {
      m = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      m = {'error': 'http_error'};
    }
    if (res.statusCode >= 400) throw ApiException(res.statusCode, m);
    return m;
  }

  Future<Map<String, dynamic>> json(String method, String path, {Map<String, dynamic>? body}) async {
    final req = http.Request(method, Uri.parse(baseUrl + path))..headers.addAll(_auth);
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final res = await http.Response.fromStream(await req.send().timeout(_timeout));
    return _decode(res);
  }

  Future<Map<String, dynamic>> putFile(String tag, Uint8List blob, String meta) async {
    final res = await http
        .put(Uri.parse('$baseUrl/v1/files/$tag'),
            headers: {..._auth, 'X-Meta': meta, 'Content-Type': 'application/octet-stream'}, body: blob)
        .timeout(const Duration(minutes: 10));
    return _decode(res);
  }

  Future<Uint8List> getFile(String id) async {
    final res = await http.get(Uri.parse('$baseUrl/v1/files/$id'), headers: _auth).timeout(const Duration(minutes: 10));
    if (res.statusCode >= 400) _decode(res);
    return res.bodyBytes;
  }
}
