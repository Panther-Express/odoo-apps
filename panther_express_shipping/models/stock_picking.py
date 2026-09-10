# -*- coding: utf-8 -*-
"""The waybill is stored on the Delivery Order (Part 6)."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    panther_shipment_id = fields.Many2one(
        'panther.shipment', string='Panther Shipment', copy=False, readonly=True)
    panther_waybill = fields.Char(
        string='Panther Waybill', related='panther_shipment_id.waybill',
        store=True, readonly=True)
    panther_status_en = fields.Char(
        string='Panther Status', related='panther_shipment_id.status_en', readonly=True)
    panther_state = fields.Selection(
        string='Panther State', related='panther_shipment_id.state', readonly=True)
    panther_is_carrier = fields.Boolean(
        string='Ships with Panther', compute='_compute_panther_is_carrier')

    @api.depends('carrier_id', 'carrier_id.delivery_type')
    def _compute_panther_is_carrier(self):
        for picking in self:
            picking.panther_is_carrier = bool(
                picking.carrier_id and picking.carrier_id.delivery_type == 'panther')

    # ------------------------------------------------------------------
    # Shipment creation from the Delivery Order
    # ------------------------------------------------------------------
    def _panther_get_or_create_shipment(self):
        """Return the panther.shipment of this picking, creating it if needed."""
        self.ensure_one()
        if self.panther_shipment_id and self.panther_shipment_id.state != 'cancelled':
            return self.panther_shipment_id

        shipment_model = self.env['panther.shipment']
        order = self.sale_id if 'sale_id' in self._fields else False
        if order:
            existing = order.panther_shipment_ids.filtered(
                lambda s: s.state not in ('cancelled',) and (not s.picking_id or s.picking_id == self))
            if existing:
                shipment = existing[:1]
                shipment.write({'picking_id': self.id})
                self.panther_shipment_id = shipment.id
                return shipment
            vals = shipment_model._prepare_vals_from_sale_order(order, picking=self)
        else:
            vals = self._panther_prepare_vals()

        shipment = shipment_model.create(vals)
        self.panther_shipment_id = shipment.id
        return shipment

    def _panther_prepare_vals(self):
        """Fallback mapping for a delivery order without a sale order."""
        self.ensure_one()
        shipment_model = self.env['panther.shipment']
        cfg = self.env['panther.api']._get_config()
        partner = self.partner_id
        weight = self.shipping_weight or self.weight or cfg['default_weight']
        products = []
        for move in self.move_ids:
            qty = move.product_uom_qty
            qty_txt = str(int(qty)) if float(qty).is_integer() else ('%.2f' % qty)
            products.append('%s x %s' % (qty_txt, move.product_id.name))
        return {
            'picking_id': self.id,
            'partner_id': partner.id,
            'carrier_id': self.carrier_id.id if self.carrier_id else False,
            'company_id': self.company_id.id,
            'currency_id': self.company_id.currency_id.id,
            'client_name': partner.name or '',
            'phone_1': shipment_model._format_phone(partner),
            'address': shipment_model._format_address(partner),
            'order_ref': self.origin or self.name,
            'price': 0.0,
            'product_name': (', '.join(products))[:200],
            'weight': weight,
            'sector_id': partner.panther_sector_id or cfg['default_sector_id'],
            'service_type': cfg['service_type'],
            'sender_name': cfg['sender_name'] or self.company_id.name,
            'sender_phone': cfg['sender_phone'] or self.company_id.phone or '',
            'sender_address': cfg['sender_address'] or shipment_model._format_address(
                self.company_id.partner_id),
            'sender_sector': cfg['sender_sector'],
        }

    # ------------------------------------------------------------------
    # Buttons (Part 9)
    # ------------------------------------------------------------------
    def action_create_panther_shipment(self):
        self.ensure_one()
        if self.state == 'cancel':
            raise UserError(_('This delivery order is cancelled.'))
        shipment = self._panther_get_or_create_shipment()
        if shipment.waybill:
            raise UserError(_('This delivery order already has the waybill %s.') % shipment.waybill)
        shipment._send_to_panther()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Shipment created'),
                'message': _('Waybill: %s') % shipment.waybill,
                'type': 'success',
            },
        }

    def action_refresh_panther_status(self):
        self.ensure_one()
        if not self.panther_shipment_id:
            raise UserError(_('No Panther shipment linked to this delivery order.'))
        return self.panther_shipment_id.action_refresh_status()

    def action_open_panther_shipment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'panther.shipment',
            'res_id': self.panther_shipment_id.id,
            'view_mode': 'form',
        }
