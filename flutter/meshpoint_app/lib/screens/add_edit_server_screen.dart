import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/meshpoint_server.dart';
import '../services/api_client.dart';
import '../services/server_store.dart';
import 'server_dashboard_screen.dart';

/// Add a brand-new server, or (re-)log into an existing one whose token
/// is missing/expired -- same form either way, just pre-filled and with
/// the name/URL fields locked when [existing] is set.
class AddEditServerScreen extends StatefulWidget {
  final MeshpointServer? existing;
  const AddEditServerScreen({super.key, this.existing});

  @override
  State<AddEditServerScreen> createState() => _AddEditServerScreenState();
}

class _AddEditServerScreenState extends State<AddEditServerScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _nameCtrl;
  late final TextEditingController _urlCtrl;
  final _userCtrl = TextEditingController(text: 'admin');
  final _passCtrl = TextEditingController();

  bool _busy = false;
  String? _error;

  bool get _isEditing => widget.existing != null;

  @override
  void initState() {
    super.initState();
    _nameCtrl = TextEditingController(text: widget.existing?.name ?? '');
    _urlCtrl = TextEditingController(text: widget.existing?.baseUrl ?? 'http://');
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _urlCtrl.dispose();
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });

    final baseUrl = _normalizeUrl(_urlCtrl.text.trim());
    final client = ApiClient(baseUrl: baseUrl);

    try {
      // Confirm this is really a meshpoint box before ever sending
      // credentials to it -- GET /api/identity is deliberately
      // unauthenticated for exactly this "is this even the right thing"
      // check (src/api/routes/identity_routes.py).
      await client.getIdentity();

      final result = await client.login(_userCtrl.text.trim(), _passCtrl.text);

      if (!mounted) return;
      final store = context.read<ServerStore>();
      final MeshpointServer server;
      if (_isEditing) {
        server = widget.existing!;
        server.baseUrl = baseUrl;
      } else {
        server = await store.addServer(name: _nameCtrl.text.trim(), baseUrl: baseUrl);
      }
      server.token = result.token;
      server.role = result.role;
      await store.save();

      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => ServerDashboardScreen(server: server)),
      );
    } on ApiException catch (e) {
      setState(() => _error = _friendlyError(e));
    } catch (e) {
      setState(() => _error = 'Could not reach $baseUrl -- check the address and that '
          'the device is on the same network.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _friendlyError(ApiException e) {
    switch (e.detail) {
      case 'invalid_credentials':
        return 'Wrong username or password.';
      case 'locked_out':
        return 'Too many failed attempts -- wait a bit and try again.';
      case 'setup_required':
        return 'This server has no admin password set yet -- finish setup '
            'in its web dashboard first.';
      default:
        return e.detail;
    }
  }

  String _normalizeUrl(String raw) {
    var url = raw;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'http://$url';
    }
    return url.endsWith('/') ? url.substring(0, url.length - 1) : url;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_isEditing ? 'Log in to ${widget.existing!.name}' : 'Add server')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _formKey,
          child: ListView(
            children: [
              if (!_isEditing) ...[
                TextFormField(
                  controller: _nameCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Name',
                    hintText: 'e.g. sensecap-meshpoint',
                  ),
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _urlCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Address',
                    hintText: 'http://192.168.1.50:8080',
                  ),
                  keyboardType: TextInputType.url,
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null,
                ),
                const SizedBox(height: 12),
              ],
              TextFormField(
                controller: _userCtrl,
                decoration: const InputDecoration(labelText: 'Username'),
                validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _passCtrl,
                decoration: const InputDecoration(labelText: 'Password'),
                obscureText: true,
                onFieldSubmitted: (_) => _busy ? null : _submit(),
                validator: (v) => (v == null || v.isEmpty) ? 'Required' : null,
              ),
              const SizedBox(height: 20),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(
                        width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(_isEditing ? 'Log in' : 'Add & log in'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
