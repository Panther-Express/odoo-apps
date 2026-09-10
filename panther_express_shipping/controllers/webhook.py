# -*- coding: utf-8 -*-
"""Part 8 - Panther status webhook + a small public tracking page.

    POST /panther/webhook/status
    {
        "waybill": "PE000000001",
        "status_id": "5",
        "status_ar": "تم التسليم",
        "status_en": "Delivered",
        "notes": "Received by the customer"
    }
"""
import json
import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PantherWebhookController(http.Controller):

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[('Content-Type', 'application/json; charset=utf-8')],
            status=status,
        )

    def _read_payload(self, post):
        """Accept raw JSON, JSON-RPC ({"params": {...}}) and form encoded bodies."""
        data = {}
        try:
            raw = request.httprequest.get_data(as_text=True) or ''
        except Exception:  # noqa: BLE001
            raw = ''
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed.get('params') if isinstance(parsed.get('params'), dict) else parsed
                elif isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    data = parsed[0]
            except ValueError:
                data = {}
        if not data and post:
            data = {k: v for k, v in post.items() if k != 'token'}
        return data or {}

    def _check_token(self, post):
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'panther_express.webhook_token') or ''
        if not expected:
            return True
        received = (
            post.get('token')
            or request.httprequest.args.get('token')
            or request.httprequest.headers.get('X-Panther-Token')
            or ''
        )
        return received == expected

    # ------------------------------------------------------------------
    # webhook
    # ------------------------------------------------------------------
    @http.route(
        '/panther/webhook/status',
        type='http', auth='public', methods=['POST', 'GET'],
        csrf=False, save_session=False)
    def panther_webhook_status(self, **post):
        if request.httprequest.method == 'GET':
            # convenience: open the URL in a browser to check that it is alive
            return self._json_response({
                'status': 'ok',
                'endpoint': '/panther/webhook/status',
                'method': 'POST',
                'expected_payload': {
                    'waybill': '', 'status_id': '', 'status_ar': '', 'status_en': '', 'notes': '',
                },
            })

        if not self._check_token(post):
            _logger.warning('Panther webhook: invalid token from %s', request.httprequest.remote_addr)
            return self._json_response({'status': 'error', 'message': 'invalid token'}, status=403)

        data = self._read_payload(post)
        _logger.info('Panther webhook received: %s', data)

        waybill = str(data.get('waybill') or data.get('awb') or '').strip()
        if not waybill:
            return self._json_response(
                {'status': 'error', 'message': 'waybill is required'}, status=400)

        shipment = request.env['panther.shipment'].sudo().search(
            [('waybill', '=', waybill)], limit=1)
        if not shipment:
            _logger.warning('Panther webhook: unknown waybill %s', waybill)
            return self._json_response(
                {'status': 'error', 'message': 'unknown waybill', 'waybill': waybill}, status=404)

        shipment._apply_status(
            status_id=data.get('status_id'),
            status_ar=data.get('status_ar'),
            status_en=data.get('status_en'),
            notes=data.get('notes'),
            source='webhook',
        )
        request.env.cr.commit()

        return self._json_response({
            'status': 'ok',
            'waybill': waybill,
            'shipment': shipment.name,
            'odoo_state': shipment.state,
            'status_id': shipment.status_id,
            'status_en': shipment.status_en,
        })

    # ------------------------------------------------------------------
    # public tracking page (Part 7, customer side)
    # ------------------------------------------------------------------
    @http.route('/panther/track', type='http', auth='public', website=True, sitemap=False)
    def panther_track(self, waybill=None, **kwargs):
        shipment = request.env['panther.shipment']
        if waybill:
            shipment = shipment.sudo().search([('waybill', '=', waybill.strip())], limit=1)
        return request.render('panther_express_shipping.panther_track_page', {
            'waybill': waybill or '',
            'shipment': shipment,
            'searched': bool(waybill),
        })
