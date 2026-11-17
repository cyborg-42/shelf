import 'package:flutter/material.dart';
import 'package:shelf_app/services/api_service.dart';
import 'package:shelf_app/services/ws_service.dart';
import 'package:shelf_app/services/notification_service.dart';
import 'package:shelf_app/models/grocery_item.dart';
import 'package:shelf_app/models/scan_log.dart';
import 'package:shelf_app/models/depletion_metric.dart';
import 'package:shelf_app/theme/app_theme.dart';
import 'scan_screen.dart';
import '../widgets/detection_card.dart';
import '../widgets/offline_banner.dart';
import 'dart:async';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<GroceryItem> _inventory = [];
  List<ScanLog> _scans = [];
  List<DepletionMetric> _depletion = [];
  bool _isLoading = true;
  bool _isOnline = true;
  StreamSubscription<Map<String, dynamic>>? _wsSub;

  @override
  void initState() {
    super.initState();
    WsService.instance.connect();
    _wsSub = WsService.instance.stream.listen(_onWsMessage);
    _refreshData();
  }

  void _onWsMessage(Map<String, dynamic> msg) {
    final type = msg['type'] as String?;

    if (type == 'SCAN_UPDATE') {
      // Prepend the new scan to the list without a full reload
      final newScan = ScanLog(
        id: 0,
        label: msg['label'] as String,
        confidence: (msg['confidence'] as num).toDouble(),
        timestamp: 'Just now',
      );
      if (mounted) setState(() => _scans = [newScan, ..._scans]);

    } else if (type == 'WEIGHT_UPDATE') {
      // Refresh inventory to reflect the new weight
      _refreshData();

      _handleStatus(
        quadrant: (msg['quadrant'] as num?)?.toInt() ?? 0,
        itemName: msg['item_name'] as String? ?? 'Unknown',
        status:   msg['status'] as String?,
        weightG:  (msg['weight_g'] as num?)?.toDouble(),
      );

    } else if (type == 'STOCK_DEPLETED') {
      _refreshData();

      _handleStatus(
        quadrant: (msg['quadrant'] as num?)?.toInt() ?? 0,
        itemName: msg['item_name'] as String? ?? 'Unknown',
        status:   'Depleted',
        weightG:  0,
        confirmed: true,
      );
    }
  }

  // Last status we saw for each quadrant, so we alert only when it CHANGES
  // (no repeat notification on every weight wobble).
  final Map<int, String> _lastStatus = {};
  final Map<int, DateTime> _emptySince = {};   // when each tray first read empty

  void _handleStatus({
    required int quadrant,
    required String itemName,
    required String? status,
    required double? weightG,
    bool confirmed = false,   // true = the backend already waited
  }) {
    if (status == null || quadrant == 0) return;

    final empty = status == 'Depleted' || (weightG != null && weightG <= 0);
    final effective = empty ? 'Depleted' : status;

    // wait before calling a tray empty: you may only have picked the fruit up to look / cut it
    if (effective == 'Depleted' && !confirmed) {
      final since = _emptySince.putIfAbsent(quadrant, () => DateTime.now());
      if (DateTime.now().difference(since).inSeconds < NotificationService.depletionConfirmSeconds) return;
    } else if (effective != 'Depleted') {
      _emptySince.remove(quadrant);
    }

    if (_lastStatus[quadrant] == effective) return;   // nothing new
    _lastStatus[quadrant] = effective;

    if (effective == 'Depleted') {
      _alertDepleted(itemName, quadrant);
    } else if (effective == 'Low Stock' || effective == 'Critical') {
      // system notification: the background service posts it (also works when the app is closed)
    }
  }

  void _alertDepleted(String itemName, int quadrant) {
    // system notification: the background service posts it (also works when the app is closed)

    // Also an in-app banner, so it is seen even while the app is open.
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: const Color(0xFFE53935),
        duration: const Duration(seconds: 6),
        content: Row(
          children: [
            const Icon(Icons.warning_amber_rounded,
                color: Colors.white, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'Restock needed: $itemName (Q$quadrant) is empty',
                style: const TextStyle(color: Colors.white),
              ),
            ),
          ],
        ),
      ),
    );
  }
  @override
  void dispose() {
    _wsSub?.cancel();
    super.dispose();
  }

  Future<void> _refreshData() async {
    setState(() => _isLoading = true);

    final inventoryResult = await ApiService.getInventory();
    final scansResult = await ApiService.getRecentScans();
    final depletionResult = await ApiService.getDepletionMetrics();

    if (!mounted) return;

    // If any call reached the backend, consider ourselves online.
    final online =
        inventoryResult.isOnline || scansResult.isOnline || depletionResult.isOnline;

    setState(() {
      _inventory = inventoryResult.data;
      _scans = scansResult.data;
      _depletion = depletionResult.data;
      _isOnline = online;
      _isLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final totalWeightKg =
        _inventory.fold<double>(0, (sum, i) => sum + i.weightG) / 1000.0;
    final itemCount = _inventory.length;
    final lowStockItems = _depletion
        .where((m) => m.stockStatus == 'Low Stock' || m.stockStatus == 'Critical')
        .toList();

    return RefreshIndicator(
      onRefresh: _refreshData,
      child: Column(
        children: [
          OfflineBanner(visible: !_isOnline),
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : SingleChildScrollView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Greeting
                        Text(
                          'Hello, Shelf User!',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Your smart shelf is ready for scanning.',
                          style: Theme.of(context).textTheme.bodyLarge,
                        ),
                        const SizedBox(height: 24),

                        // Quick AI Scan Button
                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton.icon(
                            onPressed: () {
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => const ScanScreen()),
                              );
                            },
                            icon: const Icon(Icons.center_focus_strong),
                            label: const Text('Quick AI Scan'),
                            style: ElevatedButton.styleFrom(
                              padding:
                                  const EdgeInsets.symmetric(vertical: 16),
                            ),
                          ),
                        ),
                        const SizedBox(height: 24),

                        // Summary Cards
                        Row(
                          children: [
                            Expanded(
                              child: _buildSummaryCard(
                                'Total Items',
                                _isOnline ? '$itemCount' : '—',
                                Icons.inventory,
                                AppTheme.forestEmerald,
                              ),
                            ),
                            const SizedBox(width: 16),
                            Expanded(
                              child: _buildSummaryCard(
                                'Total Weight',
                                _isOnline
                                    ? '${totalWeightKg.toStringAsFixed(2)} kg'
                                    : '—',
                                Icons.monitor_weight,
                                AppTheme.mintLeaf,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 24),

                        // Depletion Alerts
                        Card(
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Depletion Alerts',
                                  style: Theme.of(context).textTheme.titleLarge,
                                ),
                                const SizedBox(height: 8),
                                if (!_isOnline)
                                  const Text(
                                    'No data — backend is offline.',
                                    style: TextStyle(
                                        color: AppTheme.textSecondary),
                                  )
                                else if (lowStockItems.isEmpty)
                                  const Text(
                                      'All items are sufficiently stocked.')
                                else
                                  ...lowStockItems.map((metric) => ListTile(
                                        leading: Icon(
                                          metric.stockStatus == 'Critical'
                                              ? Icons.error
                                              : Icons.warning,
                                          color: metric.stockStatus == 'Critical'
                                              ? AppTheme.criticalAlert
                                              : AppTheme.lowStockAlert,
                                        ),
                                        title: Text(
                                            '${metric.itemName} (Q${metric.quadrant})'),
                                        subtitle: Text(
                                          '${metric.estimatedDaysRemaining.toStringAsFixed(1)} days left',
                                          style: TextStyle(
                                            color:
                                                metric.stockStatus == 'Critical'
                                                    ? AppTheme.criticalAlert
                                                    : AppTheme.lowStockAlert,
                                          ),
                                        ),
                                      )),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 24),

                        // Recent Scans
                        Text(
                          'Recent Scans',
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        const SizedBox(height: 8),
                        if (!_isOnline)
                          const Text(
                            'No data — backend is offline.',
                            style: TextStyle(color: AppTheme.textSecondary),
                          )
                        else if (_scans.isEmpty)
                          const Text('No scans recorded yet.')
                        else
                          ListView.builder(
                            shrinkWrap: true,
                            physics: const NeverScrollableScrollPhysics(),
                            itemCount: _scans.length,
                            itemBuilder: (context, index) {
                              final scan = _scans[index];
                              return DetectionCard(
                                label: scan.label,
                                confidence: scan.confidence,
                                timestamp: scan.timestamp,
                              );
                            },
                          ),
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildSummaryCard(
      String title, String value, IconData icon, Color color) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: color, size: 32),
            const SizedBox(height: 8),
            Text(
              value,
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 4),
            Text(
              title,
              style: Theme.of(context).textTheme.bodyMedium,
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
