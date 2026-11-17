import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shelf_app/services/api_service.dart';
import 'package:shelf_app/services/ws_service.dart';
import 'package:shelf_app/models/grocery_item.dart';
import 'package:shelf_app/theme/app_theme.dart';
import '../widgets/offline_banner.dart';

class InventoryScreen extends StatefulWidget {
  const InventoryScreen({super.key});

  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends State<InventoryScreen> {
  List<GroceryItem> _inventory = [];
  bool _isLoading = true;
  bool _isOnline = true;

  StreamSubscription<Map<String, dynamic>>? _wsSub;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _refreshData();
    // Live updates: any WebSocket event (scan, weight, bind) triggers a quiet reload.
    _wsSub = WsService.instance.stream.listen((_) {
      _debounce?.cancel();
      _debounce = Timer(const Duration(milliseconds: 300), () {
        if (mounted) _refreshData(silent: true);
      });
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _wsSub?.cancel();
    super.dispose();
  }

  Future<void> _refreshData({bool silent = false}) async {
    if (!silent) setState(() => _isLoading = true);
    final result = await ApiService.getInventory();
    if (!mounted) return;
    setState(() {
      _inventory = result.data;
      _isOnline = result.isOnline;
      _isLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () => _refreshData(),
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
                        Text(
                          'Smart Shelf Inventory',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          'Monitor your 4-quadrant tray scale matrix',
                          style: Theme.of(context).textTheme.bodyLarge,
                        ),
                        const SizedBox(height: 24),

                        // 4-Quadrant Tray Matrix
                        GridView.count(
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          crossAxisCount: 2,
                          crossAxisSpacing: 16,
                          mainAxisSpacing: 16,
                          childAspectRatio: 0.85,
                          children: List.generate(4, (index) {
                            final quadrant = index + 1;
                            final item = _inventory.cast<GroceryItem?>().firstWhere(
                                  (i) => i?.quadrant == quadrant,
                                  orElse: () => null,
                                );
                            return item != null
                                ? _buildQuadrantCard(context, item)
                                : _buildEmptyQuadrantCard(context, quadrant);
                          }),
                        ),
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildQuadrantCard(BuildContext context, GroceryItem item) {
    return Card(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            // Wrap lets the badge drop to its own line instead of overflowing.
            child: Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 8,
              runSpacing: 6,
              children: [
                Text(
                  'Quadrant ${item.quadrant}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _statusColor(item.status).withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    item.status,
                    style: TextStyle(
                      color: _statusColor(item.status),
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.itemName,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  'Weight: ${item.weightG.toStringAsFixed(1)} g / ${item.maxCapacityG.toStringAsFixed(0)} g',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 8),
                SizedBox(
                  height: 8,
                  child: LinearProgressIndicator(
                    value: (item.weightG / item.maxCapacityG).clamp(0.0, 1.0),
                    backgroundColor: Colors.grey[300],
                    valueColor: AlwaysStoppedAnimation<Color>(
                        _statusColor(item.status)),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyQuadrantCard(BuildContext context, int quadrant) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              'Quadrant $quadrant',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            Icon(Icons.wifi_off_rounded,
                size: 28, color: Colors.grey.shade400),
            const SizedBox(height: 8),
            Text(
              'No data',
              style: TextStyle(color: Colors.grey.shade500, fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'Critical':
        return AppTheme.criticalAlert;
      case 'Low Stock':
        return AppTheme.lowStockAlert;
      default:
        return AppTheme.mintLeaf;
    }
  }
}