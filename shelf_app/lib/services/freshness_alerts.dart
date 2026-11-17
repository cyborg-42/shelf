import 'dart:async';
import 'dart:convert';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;

import 'api_service.dart';

/// Every 15 minutes asks the backend (GET /api/v1/freshness-alerts) whether any fruit is about to
/// go bad or has not been touched for a day, and shows one notification per quadrant per kind per day.
/// Started from the background service (background_alerts.dart).
final Map<String, String> _freshSent = {}; // "q:kind" -> yyyy-mm-dd already shown
Timer? _freshTimer;

void startFreshnessAlerts() {
  _freshTimer?.cancel();
  Future<void> check() async {
    try {
      final res = await http
          .get(Uri.parse('${ApiService.baseUrl}/api/v1/freshness-alerts'))
          .timeout(const Duration(seconds: 8));
      if (res.statusCode != 200) return;
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      final alerts = (data['alerts'] as List?) ?? const [];
      final now = DateTime.now();
      final today = '${now.year}-${now.month}-${now.day}';
      final plugin = FlutterLocalNotificationsPlugin();
      for (final a in alerts) {
        final m = a as Map<String, dynamic>;
        final q = (m['quadrant'] as num).toInt();
        final kind = (m['kind'] ?? '').toString();
        final key = '$q:$kind';
        if (_freshSent[key] == today) continue;
        _freshSent[key] = today;
        final id = (kind == 'untouched' ? 30 : 20) + q;
        await plugin.show(
          id,
          (m['title'] ?? 'Shelf').toString(),
          (m['body'] ?? '').toString(),
          const NotificationDetails(
            android: AndroidNotificationDetails(
              'shelf_freshness',
              'Freshness reminders',
              channelDescription: 'Fruit about to go bad or not used for a day',
              importance: Importance.high,
              priority: Priority.high,
            ),
          ),
        );
      }
    } catch (_) {
      // backend not reachable right now - try again at the next tick
    }
  }

  Future.delayed(const Duration(seconds: 20), check);
  _freshTimer = Timer.periodic(const Duration(minutes: 15), (_) => check());
}
