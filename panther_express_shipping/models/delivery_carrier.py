# -*- coding: utf-8 -*-
"""Part 4 - Panther Express as a native Odoo delivery carrier."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('panther', 'Panther Express')],
        ondelete={'panther': 'set default'})

    panther_price_per_kg = fields.Float(
        string='Price per kg', default=0.0,
        help='Added to the fixed price, multiplied by the order weight.')
    panther_service_type = fields.Integer(
        string='Service Type', default=1,
        help='Panther service_type sent with every shipment of this carrier.')
    panther_sector_id = fields.Char(
        string='Default Sector ID',
        help='Fallback sector_id when the customer has none.')

    # ------------------------------------------------------------------
    # Rating
    # ------------------------------------------------------------------
    def _panther_price(self, weight):
        self.ensure_one()
        return (self.fixed_price or 0.0) + (self.panther_price_per_kg or 0.0) * (weight or 0.0)

    def panther_rate_shipment(self, order):
        """Called by Odoo (backend + eCommerce checkout) to price the delivery."""
        self.ensure_one()
        carrier = self._match_address(order.partner_shipping_id)
        if not carrier:
            return {
                'success': False,
                'price': 0.0,
                'error_message': _('Panther Express does not deliver to this address.'),
                'warning_message': False,
            }

        weight = order._panther_get_weight()
        price = self._panther_price(weight)
        company = self.company_id or order.company_id or self.env.company

        # honour the standard "Free if order amount is above" option
        if self.free_over and order.currency_id.compare_amounts(
                order._compute_amount_total_without_delivery(), self.amount) >= 0:
            price = 0.0
        elif company.currency_id and company.currency_id != order.currency_id:
            price = company.currency_id._convert(
                price, order.currency_id, company, fields.Date.today())

        return {
            'success': True,
            'price': price,
            'error_message': False,
            'warning_message': False,
        }

    # ------------------------------------------------------------------
    # Shipping
    # ------------------------------------------------------------------
    def panther_send_shipping(self, pickings):
        """Called when the user clicks "Send to Shipper" on a Delivery Order."""
        self.ensure_one()
        result = []
        for picking in pickings:
            shipment = picking._panther_get_or_create_shipment()
            if not shipment.waybill:
                shipment._send_to_panther()
            weight = picking.shipping_weight or shipment.weight
            result.append({
                'exact_price': self._panther_price(weight),
                'tracking_number': shipment.waybill,
            })
        return result

    def panther_cancel_shipment(self, pickings):
        """Panther has no public cancel endpoint: flag the shipment locally."""
        for picking in pickings:
            shipment = picking.panther_shipment_id
            if shipment:
                shipment.write({'state': 'cancelled'})
                shipment.message_post(body=_('Shipment cancelled from Odoo.'))
            picking.write({'carrier_tracking_ref': False})
        return True

    def panther_get_tracking_link(self, picking):
        base = self.env['panther.api']._get_config().get('tracking_url')
        waybill = picking.carrier_tracking_ref or ''
        if not waybill:
            return False
        if base:
            return base.replace('{waybill}', waybill) if '{waybill}' in base \
                else base.rstrip('/') + '/' + waybill
        web_base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        return '%s/panther/track?waybill=%s' % (web_base.rstrip('/'), waybill)

    # ------------------------------------------------------------------
    # Buttons (Part 9)
    # ------------------------------------------------------------------
    def action_panther_test_connection(self):
        self.ensure_one()
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

    @api.model
    def _panther_carrier(self):
        """Convenience accessor used by the demo scripts."""
        return self.search([('delivery_type', '=', 'panther')], limit=1)
