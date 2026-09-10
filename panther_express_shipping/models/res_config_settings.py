# -*- coding: utf-8 -*-
"""Part 3 - Panther Express Configuration, stored in ir.config_parameter."""
from odoo import _, api, fields, models

from .panther_api import DEFAULT_API_URL, PARAMS


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # --- API credentials
    panther_api_url = fields.Char(
        string='API URL', config_parameter=PARAMS['api_url'], default=DEFAULT_API_URL,
        help='Base endpoint. The action is appended automatically, e.g. ?action=addBulkShipments')
    panther_api_username = fields.Char(
        string='API Username', config_parameter=PARAMS['api_username'])
    panther_api_password = fields.Char(
        string='API Password', config_parameter=PARAMS['api_password'])
    panther_api_timeout = fields.Integer(
        string='Timeout (s)', config_parameter=PARAMS['api_timeout'], default=30)

    # --- Sender (pickup) information
    panther_sender_name = fields.Char(
        string='Sender Name', config_parameter=PARAMS['sender_name'])
    panther_sender_phone = fields.Char(
        string='Sender Phone', config_parameter=PARAMS['sender_phone'])
    panther_sender_address = fields.Char(
        string='Sender Address', config_parameter=PARAMS['sender_address'])
    panther_sender_sector = fields.Char(
        string='Sender Sector ID', config_parameter=PARAMS['sender_sector'])

    # --- Shipment defaults
    panther_default_sector_id = fields.Char(
        string='Default Destination Sector', config_parameter=PARAMS['default_sector_id'],
        help='Used when the customer has no specific Panther sector.')
    panther_service_type = fields.Integer(
        string='Default Service Type', config_parameter=PARAMS['service_type'], default=1)
    panther_default_weight = fields.Float(
        string='Default Weight (kg)', config_parameter=PARAMS['default_weight'], default=1.0)
    panther_tracking_url = fields.Char(
        string='Public Tracking URL', config_parameter=PARAMS['tracking_url'],
        help='Optional. Use {waybill} as placeholder, e.g. https://panther-express.top/track/{waybill}')

    # --- Webhook (Part 8)
    panther_webhook_token = fields.Char(
        string='Webhook Token', config_parameter=PARAMS['webhook_token'],
        help='Optional shared secret. When set, Panther must call the webhook with '
             '?token=... or the X-Panther-Token header.')
    panther_webhook_url = fields.Char(
        string='Webhook URL', compute='_compute_panther_webhook_url', readonly=True)

    @api.depends('panther_webhook_token')
    def _compute_panther_webhook_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for record in self:
            url = base.rstrip('/') + '/panther/webhook/status'
            if record.panther_webhook_token:
                url += '?token=' + record.panther_webhook_token
            record.panther_webhook_url = url

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_panther_test_connection(self):
        """Part 9 - Test Connection (saves the form first)."""
        self.ensure_one()
        self.execute()
        ok, message = self.env['panther.api'].test_connection()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panther Express connection'),
                'message': message,
                'type': 'success' if ok else 'danger',
                'sticky': not ok,
            },
        }

    def action_panther_open_shipments(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'panther_express_shipping.action_panther_shipment')

    def action_panther_open_carrier(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'panther_express_shipping.action_panther_delivery_carrier')
