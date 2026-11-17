import 'dart:async';

import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../models/depletion_metric.dart';
import '../services/api_service.dart';
import '../services/ws_service.dart';
import '../widgets/offline_banner.dart';
import '../services/shelf_life_service.dart';

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  List<DepletionMetric> _metrics = [];
  List<ShelfLife> _shelf = [];
  bool _isLoading = true;
  bool _isOnline = true;

  StreamSubscription<Map<String, dynamic>>? _wsSub;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _loadMetrics();
    // Live updates: any WebSocket event (scan, weight, bind) triggers a quiet reload.
    _wsSub = WsService.instance.stream.listen((_) {
      _debounce?.cancel();
      _debounce = Timer(const Duration(milliseconds: 500), () {
        if (mounted) _loadMetrics(silent: true);
      });
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _wsSub?.cancel();
    super.dispose();
  }

  Future<void> _loadMetrics({bool silent = false}) async {
    if (!silent) setState(() => _isLoading = true);
    final result = await ApiService.getDepletionMetrics();
    final shelf = await ShelfLifeService.fetch();
    if (!mounted) return;
    setState(() {
      _metrics = result.data;
      _shelf = shelf;
      _isOnline = result.isOnline;
      _isLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final shoppingList =
        _metrics.where((m) => m.estimatedDaysRemaining <= 2.0).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Consumption & Depletion Analytics',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => _loadMetrics(),
          ),
        ],
      ),
      body: Column(
        children: [
          OfflineBanner(visible: !_isOnline),
          Expanded(
            child: _isLoading
                ? const Center(
                    child: CircularProgressIndicator(color: AppTheme.primary))
                : RefreshIndicator(
                    onRefresh: () => _loadMetrics(),
                    color: AppTheme.primary,
                    child: SingleChildScrollView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Depletion Forecast',
                            style: TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.bold,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 4),
                          const Text(
                            'Calculated from daily load cell delta measurements (ΔW / Δt)',
                            style: TextStyle(
                                fontSize: 13, color: AppTheme.textSecondary),
                          ),
                          const SizedBox(height: 20),

                          if (_shelf.isNotEmpty) ..._buildShelfLife(),

                          // Depletion Forecast Cards
                          if (!_isOnline)
                            _buildOfflineEmptyState()
                          else if (_metrics.isEmpty)
                            _buildNoDataState()
                          else
                            ..._metrics.map(_buildMetricTile),

                          const SizedBox(height: 24),

                          // Auto Restock Shopping List
                          Container(
                            padding: const EdgeInsets.all(18),
                            decoration: BoxDecoration(
                              color: Colors.white,
                              borderRadius: BorderRadius.circular(16),
                              boxShadow: [
                                BoxShadow(
                                  color: Colors.black.withValues(alpha: 0.04),
                                  blurRadius: 8,
                                  offset: const Offset(0, 3),
                                ),
                              ],
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: const [
                                    Icon(Icons.shopping_cart_outlined,
                                        color: AppTheme.primary, size: 22),
                                    SizedBox(width: 8),
                                    Text(
                                      'Auto Grocery Restock List',
                                      style: TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.bold,
                                        color: AppTheme.textPrimary,
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                const Text(
                                  'Items projected to run out within 2 days are automatically added:',
                                  style: TextStyle(
                                      fontSize: 12,
                                      color: AppTheme.textSecondary),
                                ),
                                const SizedBox(height: 12),
                                if (!_isOnline)
                                  const Padding(
                                    padding: EdgeInsets.symmetric(vertical: 8),
                                    child: Text(
                                      'No data — backend is offline.',
                                      style: TextStyle(
                                          color: AppTheme.textSecondary),
                                    ),
                                  )
                                else if (shoppingList.isEmpty)
                                  const Padding(
                                    padding: EdgeInsets.symmetric(vertical: 8),
                                    child: Text(
                                      '🎉 All items are sufficiently stocked! No restocking needed.',
                                      style: TextStyle(
                                          color: AppTheme.primary,
                                          fontWeight: FontWeight.w600),
                                    ),
                                  )
                                else
                                  ...shoppingList.map(
                                    (item) => Padding(
                                      padding:
                                          const EdgeInsets.only(bottom: 8),
                                      child: Row(
                                        children: [
                                          const Icon(
                                              Icons.check_box_outlined,
                                              color: AppTheme.accentOrange,
                                              size: 18),
                                          const SizedBox(width: 8),
                                          Text(
                                            '${item.itemName} (Zone Q${item.quadrant})',
                                            style: const TextStyle(
                                                fontWeight: FontWeight.bold),
                                          ),
                                          const Spacer(),
                                          Text(
                                            '~${item.estimatedDaysRemaining.toStringAsFixed(1)} days left',
                                            style: const TextStyle(
                                              color: AppTheme.accentRed,
                                              fontSize: 12,
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  List<Widget> _buildShelfLife() {
    return [
      const Text(
        'Fruit Freshness Tracker',
        style: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.bold,
          color: AppTheme.textPrimary,
        ),
      ),
      const SizedBox(height: 4),
      const Text(
        'When each fruit was placed, whether it was removed, and days until it goes bad',
        style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
      ),
      const SizedBox(height: 16),
      ..._shelf.map(_buildShelfTile),
      const SizedBox(height: 8),
      const Divider(),
      const SizedBox(height: 16),
    ];
  }

  Widget _shelfLine(IconData icon, String label, String value) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 16, color: AppTheme.textSecondary),
        const SizedBox(width: 6),
        Text('$label: ',
            style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary)),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppTheme.textPrimary),
          ),
        ),
      ],
    );
  }

  Widget _buildShelfTile(ShelfLife s) {
    Color c = AppTheme.primary;
    if (s.freshness == 'Use soon') c = AppTheme.accentOrange;
    if (s.freshness == 'Past best') c = AppTheme.accentRed;
    if (s.state == 'removed') c = Colors.grey;
    final onShelf = s.state == 'on_shelf';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 6,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                s.itemName,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: AppTheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  'Q${s.quadrant}',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.primary,
                  ),
                ),
              ),
              const Spacer(),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: c.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  s.freshness,
                  style: TextStyle(
                    color: c,
                    fontWeight: FontWeight.bold,
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _shelfLine(Icons.login_rounded, 'Placed',
              s.firstSeen ? '${s.placedText} (first seen)' : s.placedText),
          const SizedBox(height: 6),
          if (onShelf)
            _shelfLine(Icons.inventory_2_outlined, 'Status',
                'Still on shelf, ${s.daysOnShelf.toStringAsFixed(1)} days')
          else
            _shelfLine(Icons.logout_rounded, 'Removed',
                '${s.removedText} (was on shelf ${s.daysOnShelf.toStringAsFixed(1)} days)'),
          if (onShelf && s.predictedDays != null) ...[
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Days until it goes bad',
                      style: TextStyle(
                          fontSize: 12, color: AppTheme.textSecondary),
                    ),
                    Text(
                      '${s.predictedDays!.toStringAsFixed(1)} Days',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w900,
                        color: c,
                      ),
                    ),
                  ],
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    const Text(
                      'Weight now',
                      style: TextStyle(
                          fontSize: 12, color: AppTheme.textSecondary),
                    ),
                    Text(
                      '${s.currentWeightG.toStringAsFixed(0)} g  (-${s.weightLossPct.toStringAsFixed(1)}%)',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Based on ${s.basis}',
              style: const TextStyle(
                  fontSize: 11, color: AppTheme.textSecondary),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildOfflineEmptyState() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Center(
        child: Column(
          children: const [
            Icon(Icons.wifi_off_rounded, size: 48, color: Colors.grey),
            SizedBox(height: 12),
            Text(
              'No analytics data — backend is offline.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNoDataState() {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 24),
      child: Center(
        child: Text(
          'No depletion data yet. Weight readings will populate this section.',
          style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
          textAlign: TextAlign.center,
        ),
      ),
    );
  }

  Widget _buildMetricTile(DepletionMetric metric) {
    Color badgeColor = AppTheme.primary;
    if (metric.stockStatus == 'Low Stock') badgeColor = AppTheme.accentOrange;
    if (metric.stockStatus == 'Critical') badgeColor = AppTheme.accentRed;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 6,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                metric.itemName,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: AppTheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  'Q${metric.quadrant}',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.primary,
                  ),
                ),
              ),
              const Spacer(),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: badgeColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  metric.stockStatus,
                  style: TextStyle(
                    color: badgeColor,
                    fontWeight: FontWeight.bold,
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Est. Days Remaining',
                    style:
                        TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                  ),
                  Text(
                    '${metric.estimatedDaysRemaining.toStringAsFixed(1)} Days',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w900,
                      color: badgeColor,
                    ),
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Text(
                    'Daily Consumption Rate',
                    style:
                        TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                  ),
                  Text(
                    '${metric.dailyRateG.toInt()} g/day',
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}