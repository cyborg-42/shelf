import 'dart:convert';
import 'package:http/http.dart' as http;
import 'api_service.dart';

/// One fruit's time on the shelf (from GET /api/v1/shelf-life).
class ShelfLife {
  final int quadrant;
  final String itemName;
  final String state; // 'on_shelf' or 'removed'
  final String placedText;
  final String removedText;
  final bool firstSeen;
  final double daysOnShelf;
  final double startWeightG;
  final double currentWeightG;
  final double weightLossPct;
  final double? lossRateGPerDay;
  final double? predictedDays;
  final String basis;
  final String freshness;

  ShelfLife({
    required this.quadrant,
    required this.itemName,
    required this.state,
    required this.placedText,
    required this.removedText,
    required this.firstSeen,
    required this.daysOnShelf,
    required this.startWeightG,
    required this.currentWeightG,
    required this.weightLossPct,
    required this.lossRateGPerDay,
    required this.predictedDays,
    required this.basis,
    required this.freshness,
  });

  factory ShelfLife.fromJson(Map<String, dynamic> j) {
    double d(dynamic v) => (v as num?)?.toDouble() ?? 0.0;
    double? dn(dynamic v) => (v as num?)?.toDouble();
    return ShelfLife(
      quadrant: (j['quadrant'] as num?)?.toInt() ?? 0,
      itemName: (j['item_name'] ?? '').toString(),
      state: (j['state'] ?? '').toString(),
      placedText: (j['placed_text'] ?? '').toString(),
      removedText: (j['removed_text'] ?? '').toString(),
      firstSeen: j['first_seen'] == true,
      daysOnShelf: d(j['days_on_shelf']),
      startWeightG: d(j['start_weight_g']),
      currentWeightG: d(j['current_weight_g']),
      weightLossPct: d(j['weight_loss_pct']),
      lossRateGPerDay: dn(j['loss_rate_g_per_day']),
      predictedDays: dn(j['predicted_days_until_bad']),
      basis: (j['basis'] ?? '').toString(),
      freshness: (j['freshness'] ?? '').toString(),
    );
  }
}

class ShelfLifeService {
  /// Returns an empty list if the server is offline or has no fruit history yet.
  static Future<List<ShelfLife>> fetch() async {
    try {
      final response = await http
          .get(Uri.parse('${ApiService.baseUrl}/api/v1/shelf-life'))
          .timeout(const Duration(seconds: 6));
      if (response.statusCode != 200) return [];
      final list = jsonDecode(response.body) as List<dynamic>;
      return list
          .map((e) => ShelfLife.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return [];
    }
  }
}
