import 'dart:async';
import 'dart:convert';
import 'dart:ui' show DartPluginRegistrant;

import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'api_service.dart';
import 'freshness_alerts.dart';
import 'notification_service.dart';

/// Keeps Shelf listening to the shelf even when the app is closed or the
/// screen is off, and posts normal Android notifications (like WhatsApp does)
/// when a quadrant gets low or empty.
///
/// How: an Android *foreground service* runs this file's [onBackgroundStart]
/// in its own isolate. It holds its own WebSocket to the backend. Android shows
/// a small permanent "Shelf is watching your shelf" notification while it runs.

const String _serviceChannelId = 'shelf_service';

/// Call once from main() after NotificationService.instance.init().
Future<void> initBackgroundAlerts() async {
  try {
    // The foreground-service notification needs its channel BEFORE the service starts.
    final plugin = FlutterLocalNotificationsPlugin();
    await plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(const AndroidNotificationChannel(
          _serviceChannelId,
          'Shelf monitor',
          description: 'Keeps Shelf watching your shelf in the background',
          importance: Importance.low,
        ));

    final service = FlutterBackgroundService();
    await service.configure(
      androidConfiguration: AndroidConfiguration(
        onStart: onBackgroundStart,
        autoStart: true,
        autoStartOnBoot: false,
        isForegroundMode: true,
        notificationChannelId: _serviceChannelId,
        initialNotificationTitle: 'Shelf',
        initialNotificationContent: 'Watching your shelf',
        foregroundServiceNotificationId: 888,
      ),
      iosConfiguration: IosConfiguration(autoStart: false),
    );

    if (!await service.isRunning()) {
      await service.startService();
    }
  } catch (e) {
    // never let a background-service problem stop the app from opening
    // ignore: avoid_print
    print('[BG] could not start background alerts: $e');
  }
}

// ---------------------------------------------------------------------------
// Everything below runs inside the background service (separate isolate).
// ---------------------------------------------------------------------------

@pragma('vm:entry-point')
Future<void> onBackgroundStart(ServiceInstance service) async {
  DartPluginRegistrant.ensureInitialized();
  await NotificationService.instance.init(askPermission: false);

  service.on('stopService').listen((_) => service.stopSelf());

  // Last status per quadrant -> notify only when it CHANGES.
  final Map<int, String> lastStatus = {};
  WebSocketChannel? channel;
  Timer? retry;
  startFreshnessAlerts();   // freshness reminders

  Future<void> seed() async {
    try {
      final r = await ApiService.getInventory();
      for (final i in r.data) {
        final q = (i.quadrant as num).toInt();
        lastStatus.putIfAbsent(q, () => i.status.toString());
      }
    } catch (_) {}
  }

  final Map<int, DateTime> emptySince = {};   // when each tray first read empty

  void handle(Map<String, dynamic> msg) {
    final type = msg['type'] as String?;
    if (type != 'WEIGHT_UPDATE' && type != 'STOCK_DEPLETED') return;

    final q = (msg['quadrant'] as num?)?.toInt() ?? 0;
    final name = msg['item_name'] as String? ?? 'Item';
    final w = (msg['weight_g'] as num?)?.toDouble();
    final status =
        type == 'STOCK_DEPLETED' ? 'Depleted' : msg['status'] as String?;
    if (status == null || q == 0) return;

    final empty = status == 'Depleted' || (w != null && w <= 0);
    final effective = empty ? 'Depleted' : status;
    // wait before calling a tray empty (a STOCK_DEPLETED message from the backend has already waited)
    if (effective == 'Depleted' && type != 'STOCK_DEPLETED') {
      final since = emptySince.putIfAbsent(q, () => DateTime.now());
      if (DateTime.now().difference(since).inSeconds < NotificationService.depletionConfirmSeconds) return;
    } else if (effective != 'Depleted') {
      emptySince.remove(q);
    }
    if (lastStatus[q] == effective) return;
    lastStatus[q] = effective;

    if (effective == 'Depleted') {
      NotificationService.instance
          .showDepletionAlert(itemName: name, quadrant: q);
    } else if (effective == 'Low Stock' || effective == 'Critical') {
      NotificationService.instance.showLowStockAlert(
        itemName: name,
        quadrant: q,
        status: effective,
        weightG: w ?? 0,
      );
    }
  }

  void scheduleReconnect(void Function() open) {
    retry?.cancel();
    retry = Timer(const Duration(seconds: 3), open);
  }

  void open() {
    try {
      final base = ApiService.baseUrl
          .replaceFirst(RegExp(r'^http'), 'ws')
          .replaceAll(RegExp(r'#.*$'), '');
      channel = WebSocketChannel.connect(Uri.parse('$base/ws'));
      channel!.ready.then((_) {
        seed();
        channel!.stream.listen(
          (raw) {
            try {
              handle(jsonDecode(raw as String) as Map<String, dynamic>);
            } catch (_) {}
          },
          onDone: () => scheduleReconnect(open),
          onError: (_) => scheduleReconnect(open),
          cancelOnError: true,
        );
      }).catchError((Object _) {
        scheduleReconnect(open);
      });
    } catch (_) {
      scheduleReconnect(open);
    }
  }

  open();
}
