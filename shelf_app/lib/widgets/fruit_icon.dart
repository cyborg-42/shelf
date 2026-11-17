import 'package:flutter/material.dart';

/// Small hand-drawn fruit icons (no image files needed).
/// Use:  FruitIcon(label: 'Orange', size: 34)
/// Draws apple, orange, guava and pomegranate; any other name shows a green leaf icon.
class FruitIcon extends StatelessWidget {
  final String label;
  final double size;

  const FruitIcon({super.key, required this.label, this.size = 34});

  @override
  Widget build(BuildContext context) {
    final kind = label.toLowerCase().trim();
    const known = ['apple', 'orange', 'guava', 'pomegranate'];
    if (!known.contains(kind)) {
      return Icon(Icons.eco, size: size, color: const Color(0xFF2E7D32));
    }
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _FruitPainter(kind)),
    );
  }
}

class _FruitPainter extends CustomPainter {
  final String kind;
  _FruitPainter(this.kind);

  @override
  void paint(Canvas canvas, Size size) {
    final double s = size.width;

    Offset p(double x, double y) => Offset(x * s, y * s);
    Paint fill(Color c) {
      final paint = Paint();
      paint.color = c;
      paint.style = PaintingStyle.fill;
      return paint;
    }

    void oval(double cx, double cy, double w, double h, Paint paint, {double rot = 0}) {
      canvas.save();
      canvas.translate(cx * s, cy * s);
      canvas.rotate(rot);
      canvas.drawOval(Rect.fromCenter(center: Offset.zero, width: w * s, height: h * s), paint);
      canvas.restore();
    }

    void stemAndLeaf(double sx, double sy) {
      final stem = Paint();
      stem.color = const Color(0xFF6D4C41);
      stem.strokeWidth = 0.045 * s;
      stem.strokeCap = StrokeCap.round;
      canvas.drawLine(p(sx, sy), p(sx + 0.03, sy - 0.14), stem);
      oval(sx + 0.17, sy - 0.12, 0.24, 0.11, fill(const Color(0xFF43A047)), rot: -0.5);
    }

    final shine = fill(const Color.fromRGBO(255, 255, 255, 0.35));

    if (kind == 'apple') {
      final body = fill(const Color(0xFFD32F2F));
      canvas.drawCircle(p(0.40, 0.58), 0.27 * s, body);
      canvas.drawCircle(p(0.60, 0.58), 0.27 * s, body);
      canvas.drawCircle(p(0.50, 0.66), 0.22 * s, body);
      stemAndLeaf(0.50, 0.34);
      oval(0.29, 0.54, 0.09, 0.17, shine, rot: 0.3);
    } else if (kind == 'orange') {
      canvas.drawCircle(p(0.50, 0.58), 0.35 * s, fill(const Color(0xFFFB8C00)));
      final dot = fill(const Color(0xFFEF6C00));
      canvas.drawCircle(p(0.40, 0.60), 0.016 * s, dot);
      canvas.drawCircle(p(0.60, 0.50), 0.016 * s, dot);
      canvas.drawCircle(p(0.56, 0.72), 0.016 * s, dot);
      canvas.drawCircle(p(0.38, 0.74), 0.016 * s, dot);
      canvas.drawCircle(p(0.66, 0.66), 0.016 * s, dot);
      canvas.drawCircle(p(0.50, 0.25), 0.03 * s, fill(const Color(0xFF8D4E00)));
      oval(0.67, 0.19, 0.24, 0.11, fill(const Color(0xFF43A047)), rot: -0.45);
      oval(0.34, 0.47, 0.10, 0.17, shine, rot: 0.3);
    } else if (kind == 'guava') {
      oval(0.50, 0.60, 0.68, 0.62, fill(const Color(0xFFAED581)));
      canvas.drawCircle(p(0.64, 0.68), 0.15 * s, fill(const Color.fromRGBO(244, 143, 177, 0.40)));
      final speck = fill(const Color(0xFF7CB342));
      canvas.drawCircle(p(0.38, 0.62), 0.018 * s, speck);
      canvas.drawCircle(p(0.50, 0.50), 0.018 * s, speck);
      canvas.drawCircle(p(0.44, 0.76), 0.018 * s, speck);
      canvas.drawCircle(p(0.58, 0.58), 0.018 * s, speck);
      stemAndLeaf(0.50, 0.30);
      oval(0.32, 0.52, 0.09, 0.16, shine, rot: 0.3);
    } else {
      // pomegranate: dark red body with a crown on top
      canvas.drawCircle(p(0.50, 0.60), 0.34 * s, fill(const Color(0xFFB71C1C)));
      final crown = Path();
      crown.moveTo(0.38 * s, 0.31 * s);
      crown.lineTo(0.40 * s, 0.14 * s);
      crown.lineTo(0.46 * s, 0.24 * s);
      crown.lineTo(0.50 * s, 0.10 * s);
      crown.lineTo(0.54 * s, 0.24 * s);
      crown.lineTo(0.60 * s, 0.14 * s);
      crown.lineTo(0.62 * s, 0.31 * s);
      crown.close();
      canvas.drawPath(crown, fill(const Color(0xFF8E0E0E)));
      final seed = fill(const Color(0xFFE57373));
      canvas.drawCircle(p(0.42, 0.62), 0.016 * s, seed);
      canvas.drawCircle(p(0.58, 0.55), 0.016 * s, seed);
      canvas.drawCircle(p(0.55, 0.74), 0.016 * s, seed);
      oval(0.33, 0.52, 0.10, 0.17, shine, rot: 0.3);
    }
  }

  @override
  bool shouldRepaint(covariant _FruitPainter oldDelegate) => oldDelegate.kind != kind;
}
