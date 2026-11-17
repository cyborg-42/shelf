import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import '../theme/app_theme.dart';
import '../services/api_service.dart';
import '../services/scan_service.dart';

class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

/// One scan result waiting to be added to a quadrant.
class _Scanned {
  final String item;
  final double confidence;
  final int count;
  const _Scanned(this.item, this.confidence, this.count);

  String get text => '$count × $item (${confidence.toStringAsFixed(1)}%)';
}

class _ScanScreenState extends State<ScanScreen> {
  bool _isProcessing = false;
  bool _isAdding = false;
  _Scanned? _scanned;      // last scan, waiting for the Add button
  String? _statusLine;     // e.g. "Apple added to Quadrant 2"

  // Camera-related variables
  CameraController? _cameraController;
  bool _torchOn = false;   // flashlight switch (starts off)
  bool _isCameraInitialized = false;
  String? _cameraError;

  @override
  void initState() {
    super.initState();
    _initializeCamera();
  }

  @override
  void dispose() {
    _cameraController?.dispose();
    super.dispose();
  }

  Future<void> _initializeCamera() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        setState(() => _cameraError = 'No cameras found');
        return;
      }
      final CameraDescription camera = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );

      _cameraController = CameraController(
        camera,
        ResolutionPreset.medium,
        enableAudio: false,
      );

      await _cameraController?.initialize();
      try {
        await _cameraController?.setFlashMode(FlashMode.off);
      } catch (_) {}
      if (!mounted) return;

      setState(() => _isCameraInitialized = true);
    } on CameraException catch (e) {
      setState(() => _cameraError = 'Camera error: ${e.description}');
    }
  }

  Future<Uint8List?> _captureBytes() async {
    final c = _cameraController;
    if (c == null || !c.value.isInitialized || c.value.isTakingPicture) {
      return null;
    }
    try {
      final XFile f = await c.takePicture();
      return await f.readAsBytes();
    } catch (_) {
      return null;
    }
  }

  void _snack(String msg, Color color) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: color),
    );
  }

  // ---------------- scan ----------------
  Future<void> _executeScan() async {
    if (!_isCameraInitialized || _isProcessing || _isAdding) return;

    setState(() {
      _isProcessing = true;
      _statusLine = null;
    });
    try {
      final bytes = await _captureBytes();
      if (bytes == null) throw Exception('Could not capture a photo');

      // probe only: detects + counts, changes nothing on the server
      final r = await ScanService.scanAuto(bytes, commit: false);
      if (!mounted) return;

      if (r['success'] != true) {
        setState(() => _isProcessing = false);
        _snack('Error: ${r['error'] ?? 'scan failed'}', Colors.red);
        return;
      }

      final item = r['detected_item'].toString();
      if (item == 'No Produce Detected') {
        setState(() {
          _isProcessing = false;
          _scanned = null;
        });
        _snack('No produce detected. Try better light or move closer.',
            Colors.orange.shade800);
        return;
      }

      setState(() {
        _isProcessing = false;
        _scanned = _Scanned(
          item,
          ((r['confidence'] as num?) ?? 0).toDouble(),
          ((r['count'] as num?) ?? 0).toInt(),
        );
      });
    } catch (e) {
      if (mounted) {
        setState(() => _isProcessing = false);
        _snack('Error: $e', Colors.red);
      }
    }
  }

  // ---------------- add to a quadrant ----------------
  Future<void> _chooseQuadrantAndAdd() async {
    final scan = _scanned;
    if (scan == null || _isAdding) return;

    // show what is in each quadrant right now
    final inv = await ApiService.getInventory();
    if (!mounted) return;
    final byQ = {for (final i in inv.data) i.quadrant: i};

    final picked = await showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Add ${scan.item} to which quadrant?',
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.bold),
                ),
              ),
            ),
            for (final q in [1, 2, 3, 4])
              ListTile(
                leading: CircleAvatar(child: Text('$q')),
                title: Text('Quadrant $q'),
                subtitle: Text(
                  byQ[q] == null
                      ? 'No data'
                      : '${byQ[q]!.itemName} · ${byQ[q]!.weightG.toStringAsFixed(0)} g',
                ),
                onTap: () => Navigator.pop(ctx, q),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (picked == null || !mounted) return;

    setState(() => _isAdding = true);
    final r = await ScanService.assignItem(
      quadrant: picked,
      itemName: scan.item,
      confidence: scan.confidence,
      count: scan.count,
    );
    if (!mounted) return;
    setState(() => _isAdding = false);

    if (r['success'] == true) {
      setState(() {
        _statusLine = '${scan.item} added to Quadrant $picked';
        _scanned = null;
      });
      _snack('${scan.item} added to Quadrant $picked', AppTheme.primary);
    } else {
      _snack('Could not add: ${r['error'] ?? 'server error'}', Colors.red);
    }
  }

  // ---------------- UI ----------------
  /// Torch (flashlight) on/off. Stays lit while the photo is taken.
  Future<void> _toggleTorch() async {
    final c = _cameraController;
    if (c == null || !c.value.isInitialized) return;
    final next = !_torchOn;
    try {
      await c.setFlashMode(next ? FlashMode.torch : FlashMode.off);
      if (mounted) setState(() => _torchOn = next);
    } catch (_) {
      _snack('This camera has no torch', Colors.red);
    }
  }

  /// Camera preview that fills the viewfinder box (cropped, not squashed).
  Widget _buildPreview() {
    final controller = _cameraController!;
    final size = controller.value.previewSize ?? const Size(1280, 720);
    return Positioned.fill(
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: FittedBox(
          fit: BoxFit.cover,
          child: SizedBox(
            width: size.height,
            height: size.width,
            child: CameraPreview(controller),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          "Phone Camera Scanning Station",
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              "Visual Produce Scanner",
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.bold,
                color: AppTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              "Point the camera at produce, tap Scan, then Add it to a quadrant",
              style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
            ),
            const SizedBox(height: 20),

            // Camera Viewfinder Box
            Container(
              width: double.infinity,
              height: 240,
              decoration: BoxDecoration(
                color: const Color(0xFF0F172A),
                borderRadius: BorderRadius.circular(20),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.15),
                    blurRadius: 12,
                    offset: const Offset(0, 4),
                  ),
                ],
              ),
              child: Stack(
                children: [
                  if (_cameraError != null)
                    Center(
                      child: Text(
                        _cameraError!,
                        style: const TextStyle(color: Colors.red, fontSize: 16),
                        textAlign: TextAlign.center,
                      ),
                    )
                  else if (_isCameraInitialized)
                    _buildPreview()
                  else
                    const Center(
                      child: CircularProgressIndicator(color: AppTheme.primary),
                    ),
                  // Torch button (top-right)
                  if (_isCameraInitialized && _cameraError == null)
                    Positioned(
                      top: 8,
                      right: 8,
                      child: Material(
                        color: Colors.black54,
                        shape: const CircleBorder(),
                        child: IconButton(
                          tooltip: _torchOn ? 'Torch off' : 'Torch on',
                          icon: Icon(
                            _torchOn ? Icons.flash_on : Icons.flash_off,
                            color: _torchOn ? Colors.amber : Colors.white,
                          ),
                          onPressed: _toggleTorch,
                        ),
                      ),
                    ),
                  // Reticle corners
                  Positioned(
                    top: 20,
                    left: 20,
                    child: _buildCorner(top: true, left: true),
                  ),
                  Positioned(
                    top: 20,
                    right: 20,
                    child: _buildCorner(top: true, left: false),
                  ),
                  Positioned(
                    bottom: 20,
                    left: 20,
                    child: _buildCorner(top: false, left: true),
                  ),
                  Positioned(
                    bottom: 20,
                    right: 20,
                    child: _buildCorner(top: false, left: false),
                  ),
                  if (_isProcessing)
                    const Center(
                      child: CircularProgressIndicator(
                          color: AppTheme.primaryLight, strokeWidth: 4),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            // Scan Action Button
            SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton.icon(
                onPressed: (_isProcessing || _isAdding) ? null : _executeScan,
                icon: const Icon(Icons.camera_alt_rounded),
                label: Text(_isProcessing ? "Processing..." : "Scan Item"),
              ),
            ),

            // Result of the last scan + Add button
            if (_scanned != null) ...[
              const SizedBox(height: 20),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppTheme.primaryLight.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                      color: AppTheme.primary.withValues(alpha: 0.3)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.check_circle_rounded,
                            color: AppTheme.primary, size: 24),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                "Scanned",
                                style: TextStyle(
                                    fontSize: 12,
                                    color: AppTheme.textSecondary),
                              ),
                              Text(
                                _scanned!.text,
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                  color: AppTheme.primaryDark,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    SizedBox(
                      width: double.infinity,
                      height: 46,
                      child: ElevatedButton.icon(
                        onPressed: _isAdding ? null : _chooseQuadrantAndAdd,
                        icon: const Icon(Icons.add_circle_outline),
                        label: Text(_isAdding ? "Adding..." : "Add"),
                      ),
                    ),
                  ],
                ),
              ),
            ],

            // Confirmation after adding
            if (_statusLine != null) ...[
              const SizedBox(height: 20),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppTheme.primaryLight.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                      color: AppTheme.primary.withValues(alpha: 0.3)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.check_circle_rounded,
                        color: AppTheme.primary, size: 24),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        _statusLine!,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.primaryDark,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildCorner({required bool top, required bool left}) {
    return Container(
      width: 24,
      height: 24,
      decoration: BoxDecoration(
        border: Border(
          top: top
              ? const BorderSide(color: AppTheme.primaryLight, width: 3)
              : BorderSide.none,
          bottom: !top
              ? const BorderSide(color: AppTheme.primaryLight, width: 3)
              : BorderSide.none,
          left: left
              ? const BorderSide(color: AppTheme.primaryLight, width: 3)
              : BorderSide.none,
          right: !left
              ? const BorderSide(color: AppTheme.primaryLight, width: 3)
              : BorderSide.none,
        ),
      ),
    );
  }
}
