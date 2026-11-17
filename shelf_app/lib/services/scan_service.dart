import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'api_service.dart';

/// Calls the backend scan helpers.
class ScanService {
  /// POST /api/v1/scan-auto  (detect + count).
  /// commit=false -> probe only (changes nothing on the server).
  static Future<Map<String, dynamic>> scanAuto(
    Uint8List imageBytes, {
    bool commit = false,
  }) async {
    try {
      final uri = Uri.parse(
          '${ApiService.baseUrl}/api/v1/scan-auto?commit=$commit');
      final request = http.MultipartRequest('POST', uri);
      request.files.add(
        http.MultipartFile.fromBytes('file', imageBytes, filename: 'scan.jpg'),
      );
      final streamed =
          await request.send().timeout(const Duration(seconds: 20));
      final response = await http.Response.fromStream(streamed);
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return {'success': false, 'error': 'Server error ${response.statusCode}'};
    } catch (e) {
      return {'success': false, 'error': e.toString()};
    }
  }

  /// POST /api/v1/assign-item  - write [itemName] onto [quadrant] now.
  /// The weight stays whatever the load cell last reported.
  static Future<Map<String, dynamic>> assignItem({
    required int quadrant,
    required String itemName,
    double confidence = 0,
    int count = 0,
  }) async {
    try {
      final response = await http
          .post(
            Uri.parse('${ApiService.baseUrl}/api/v1/assign-item'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'quadrant': quadrant,
              'item_name': itemName,
              'confidence': confidence,
              'count': count,
            }),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return {'success': false, 'error': 'Server error ${response.statusCode}'};
    } catch (e) {
      return {'success': false, 'error': e.toString()};
    }
  }
}
