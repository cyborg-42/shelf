// ignore: depend_on_referenced_packages
import 'dart:ui' show Color;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Singleton wrapper around flutter_local_notifications.
/// Call [NotificationService.instance.init()] once at app startup,
/// then use [showDepletionAlert] or [showLowStockAlert] anywhere in the app.
class NotificationService {
  /// Seconds a tray must stay empty before the 'Depleted' alert fires (600 = 10 min; use 20 for a demo).
  static const int depletionConfirmSeconds = 5;

  NotificationService._();
  static final NotificationService instance = NotificationService._();

  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();

  bool _initialized = false;

  // Android notification channel (required for Android 8+)
  static const _channelId   = 'shelf_alerts_v2';
  static const _channelName = 'Stock Alerts';
  static const _channelDesc = 'Notifies when a shelf quadrant runs low or empty';

  // Notification IDs: depleted alerts use IDs 11-14, low/critical use 1-4.
  // Repeated alerts for the same quadrant replace the previous one.
  static int _depletionId(int quadrant) => 10 + quadrant;
  static int _lowStockId(int quadrant)  => quadrant;

  /// Must be called once before showing any notification.
  /// Safe to call multiple times - later calls are no-ops.
  /// Also asks for the Android 13+ notification permission.
  Future<void> init({bool askPermission = true}) async {
    if (_initialized) return;
    _initialized = true;

    const androidSettings =
        AndroidInitializationSettings('@mipmap/ic_launcher');

    const darwinSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );

    const initSettings = InitializationSettings(
      android: androidSettings,
      iOS: darwinSettings,
      macOS: darwinSettings,
    );

    await _plugin.initialize(initSettings);

    final android = _plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();

    // Create the Android notification channel (silently ignored on older OS)
    const channel = AndroidNotificationChannel(
      _channelId,
      _channelName,
      description: _channelDesc,
      importance: Importance.high,
      playSound: true,
    );
    await android?.createNotificationChannel(channel);

    // Android 13+ (API 33): notifications are blocked until the user allows them.
    // (the background service passes askPermission: false - it has no screen to show the prompt on)
    if (!askPermission) return;
    // (dynamic call so it compiles on any plugin version; new name first, old name as fallback)
    try {
      await (android as dynamic)?.requestNotificationsPermission();
    } catch (_) {
      try {
        await (android as dynamic)?.requestPermission();
      } catch (_) {}
    }
  }

  /// Heads-up notification when a quadrant weight reaches 0 (empty).
  Future<void> showDepletionAlert({
    required String itemName,
    required int quadrant,
  }) async {
    final androidDetails = AndroidNotificationDetails(
      _channelId,
      _channelName,
      channelDescription: _channelDesc,
      importance: Importance.high,
      priority: Priority.high,
      ticker: 'Stock depleted',
      color: const Color(0xFFE53935), // red
      icon: '@mipmap/ic_launcher',
    );

    const iosDetails = DarwinNotificationDetails(
      presentAlert: true,
      presentBadge: true,
      presentSound: true,
    );

    final details = NotificationDetails(
      android: androidDetails,
      iOS: iosDetails,
      macOS: iosDetails,
    );

    await _plugin.show(
      _depletionId(quadrant),
      'Restock needed - $itemName',
      '$itemName in Quadrant $quadrant is empty. Please restock now.',
      details,
    );
  }

  /// Softer notification for low/critical stock (weight > 0 but below threshold).
  Future<void> showLowStockAlert({
    required String itemName,
    required int quadrant,
    required String status,
    required double weightG,
  }) async {
    const androidDetails = AndroidNotificationDetails(
      _channelId,
      _channelName,
      channelDescription: _channelDesc,
      importance: Importance.high,
      priority: Priority.high,
      icon: '@mipmap/ic_launcher',
    );

    const iosDetails = DarwinNotificationDetails(
      presentAlert: true,
      presentBadge: false,
      presentSound: false,
    );

    const details = NotificationDetails(
      android: androidDetails,
      iOS: iosDetails,
      macOS: iosDetails,
    );

    await _plugin.show(
      _lowStockId(quadrant),
      '$status - $itemName',
      '$itemName in Quadrant $quadrant is running low '
      '(${weightG.toStringAsFixed(0)} g remaining).',
      details,
    );
  }
}
