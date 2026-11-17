import 'package:flutter/material.dart';
import 'theme/app_theme.dart';
import 'navigation/bottom_navigation.dart';
import 'services/notification_service.dart';
import 'package:shelf_app/services/background_alerts.dart';

void main() async {
  // Required before any async work before runApp
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize local notifications and create the Android channel
  await NotificationService.instance.init();
  await initBackgroundAlerts();

  runApp(const ShelfApp());
}

class ShelfApp extends StatelessWidget {
  const ShelfApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'INVENTORY',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      home: const BottomNavigation(),
    );
  }
}
