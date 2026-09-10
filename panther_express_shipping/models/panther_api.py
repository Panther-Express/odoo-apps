# -*- coding: utf-8 -*-
"""Low level HTTP client for the Panther Express shipping API.

Production endpoint::

    POST https://panther-express.top/api/shipment.php?action=addBulkShipments

For the local demo the URL can be pointed at the bundled mock server
(``http://panther-mock:8888/api/shipment.php``) so nothing leaves the machine.
"""
import json
import logging
import pprint

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_API_URL = 'https://panther-express.top/api/shipment.php'
DEFAULT_TIMEOUT = 30

# ir.config_parameter keys used by the whole module
PARAMS = {
    'api_url': 'panther_express.api_url',
    'api_username': 'panther_express.api_username',
    'api_password': 'panther_express.api_password',
    'api_timeout': 'panther_express.api_timeout',
    'sender_name': 'panther_express.sender_name',
    'sender_phone': 'panther_express.sender_phone',
    'sender_address': 'panther_express.sender_address',
    'sender_sector': 'panther_express.sender_sector',
    'default_sector_id': 'panther_express.default_sector_id',
    'service_type': 'panther_express.service_type',
    'default_weight': 'panther_express.default_weight',
    'webhook_token': 'panther_express.webhook_token',
    'tracking_url': 'panther_express.tracking_url',
}


class PantherApi(models.AbstractModel):
    """Stateless helper: ``self.env['panther.api'].add_bulk_shipments([...])``"""

    _name = 'panther.api'
    _description = 'Panther Express API Client'

    # ------------------------------------------------------------------
    # Configuration (Part 3 - everything lives in ir.config_parameter)
    # ------------------------------------------------------------------
    @api.model
    def _get_config(self):
        icp = self.env['ir.config_parameter'].sudo()

        def _p(key, default=''):
            return (icp.get_param(PARAMS[key]) or default or '').strip()

        try:
            timeout = int(float(_p('api_timeout') or DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        try:
            service_type = int(float(_p('service_type') or 1))
        except (TypeError, ValueError):
            service_type = 1
        try:
            default_weight = float(_p('default_weight') or 1.0)
        except (TypeError, ValueError):
            default_weight = 1.0

        return {
            'api_url': _p('api_url', DEFAULT_API_URL),
            'user': _p('api_username'),
            'password': _p('api_password'),
            'timeout': timeout,
            'sender_name': _p('sender_name'),
            'sender_phone': _p('sender_phone'),
            'sender_address': _p('sender_address'),
            'sender_sector': _p('sender_sector'),
            'default_sector_id': _p('default_sector_id'),
            'service_type': service_type,
            'default_weight': default_weight,
            'webhook_token': _p('webhook_token'),
            'tracking_url': _p('tracking_url'),
        }

    @api.model
    def _check_credentials(self):
        cfg = self._get_config()
        missing = [label for key, label in (
            ('api_url', _('API URL')),
            ('user', _('API Username')),
            ('password', _('API Password')),
        ) if not cfg.get(key)]
        if missing:
            raise UserError(_(
                'Panther Express is not configured yet.\n'
                'Missing: %s\n\n'
                'Go to Panther Express > Configuration > Settings.'
            ) % ', '.join(missing))
        return cfg

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    @api.model
    def _mask(self, payload):
        """Return a copy of the payload that is safe to store/log."""
        safe = dict(payload or {})
        if safe.get('password'):
            safe['password'] = '********'
        return safe

    @api.model
    def _request(self, action, payload, check_credentials=True):
        """POST ``payload`` to ``<api_url>?action=<action>``.

        Never raises on transport errors: returns a dict
        ``{'ok', 'data', 'raw', 'status_code', 'request', 'url', 'error'}``
        so the caller can store the failure on the shipment record.
        """
        cfg = self._check_credentials() if check_credentials else self._get_config()
        url = '%s?action=%s' % (cfg['api_url'], action)
        body = dict(payload or {})
        body['user'] = cfg['user']
        body['password'] = cfg['password']

        _logger.debug('Panther >>> POST %s\n%s', url, pprint.pformat(self._mask(body)))
        result = {
            'ok': False,
            'data': None,
            'raw': '',
            'status_code': 0,
            'request': self._mask(body),
            'url': url,
            'error': '',
        }
        try:
            response = requests.post(
                url,
                json=body,
                timeout=cfg['timeout'],
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'User-Agent': 'Odoo-PantherExpress/1.0',
                },
            )
        except requests.exceptions.Timeout:
            result['error'] = _('Panther API timeout after %(sec)s seconds (%(url)s).') % {
                'sec': cfg['timeout'], 'url': url}
            _logger.warning(result['error'])
            return result
        except requests.exceptions.RequestException as exc:
            result['error'] = _('Cannot reach the Panther API at %(url)s:\n%(err)s') % {
                'url': url, 'err': exc}
            _logger.warning(result['error'])
            return result

        result['status_code'] = response.status_code
        result['raw'] = (response.text or '')[:20000]
        _logger.debug('Panther <<< %s %s', response.status_code, result['raw'][:2000])

        try:
            result['data'] = response.json()
        except ValueError:
            result['data'] = None

        if response.status_code >= 400:
            result['error'] = _('Panther API returned HTTP %(code)s:\n%(body)s') % {
                'code': response.status_code, 'body': result['raw'][:500]}
            return result
        if result['data'] is None:
            result['error'] = _('Panther API returned a non JSON response:\n%s') % result['raw'][:500]
            return result

        api_error = self._extract_error(result['data'])
        if api_error:
            result['error'] = api_error
            return result

        result['ok'] = True
        return result

    @api.model
    def _extract_error(self, data):
        """Detect the PHP style error payloads used by the Panther API."""
        if isinstance(data, dict):
            for key in ('error', 'errors', 'error_message', 'message_error'):
                value = data.get(key)
                if value:
                    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            status = data.get('status')
            if isinstance(status, str) and status.lower() in ('fail', 'failed', 'error', 'false'):
                return data.get('message') or _('Panther API returned status "%s".') % status
            if data.get('success') is False:
                return data.get('message') or _('Panther API returned success=false.')
        return ''

    # ------------------------------------------------------------------
    # Public API actions (Part 6)
    # ------------------------------------------------------------------
    @api.model
    def add_bulk_shipments(self, shipments):
        """``action=addBulkShipments`` - ``shipments`` is a list of payload dicts."""
        return self._request('addBulkShipments', {'shipments': list(shipments or [])})

    @api.model
    def get_current_status(self, waybill):
        """``action=getCurrentStatus``.

        The API expects ``waybill`` as a **list** (it runs implode() on it server
        side); sending a plain string makes the remote script crash.
        """
        waybills = waybill if isinstance(waybill, (list, tuple)) else [waybill]
        return self._request('getCurrentStatus', {
            'waybill': [str(w or '') for w in waybills],
        })

    @api.model
    def test_connection(self):
        """Ping the API with the stored credentials. Returns ``(ok, message)``."""
        cfg = self._check_credentials()
        result = self._request('getCurrentStatus', {'waybill': ['PANTHER-TEST-CONNECTION']})
        if result['error']:
            return False, result['error']
        return True, _(
            'Connection OK.\nEndpoint: %(url)s\nUser: %(user)s\nHTTP status: %(code)s'
        ) % {'url': cfg['api_url'], 'user': cfg['user'], 'code': result['status_code']}

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------
    @api.model
    def _response_rows(self, data):
        """Normalise every known response shape into a list of dicts."""
        if data is None:
            return []
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            for key in ('response', 'data', 'result', 'shipments', 'results'):
                value = data.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
                if isinstance(value, dict):
                    return [value]
            # flat dict already holding the fields
            if any(k in data for k in ('waybill', 'status_id', 'status_en', 'awb')):
                return [data]
        return []

    @api.model
    def _pick(self, row, *keys):
        """First non empty value among ``keys`` of ``row``."""
        for key in keys:
            value = row.get(key)
            if value not in (None, '', False):
                return value
        return ''
