import 'package:flutter/material.dart';
import 'package:shelf_app/theme/app_theme.dart';
import 'package:shelf_app/widgets/fruit_icon.dart';

class DetectionCard extends StatelessWidget {
  final String label;
  final double confidence;
  final String timestamp;

  const DetectionCard({
    super.key,
    required this.label,
    required this.confidence,
    required this.timestamp,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            // Icon representing the fruit (drawn in fruit_icon.dart)
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: AppTheme.mintLeaf.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(12),
              ),
              alignment: Alignment.center,
              child: FruitIcon(label: label, size: 34),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Confidence: ${confidence.toStringAsFixed(1)}%',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
              ),
            ),
            Text(
              timestamp,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
