# -*- coding: utf-8 -*-
"""Part 5 - "Create Panther Shipment" button on the Sales Order."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    panther_shipment_ids = fields.One2many(
        'panther.shipment', 'sale_order_id', string='Panther Shipments')
    panther_shipment_count = fields.Integer(
        string='Shipments', compute='_compute_panther_shipment_count')
    panther_waybill = fields.Char(
        string='Panther Waybill', compute='_compute_panther_waybill', store=True)
    panther_is_carrier = fields.Boolean(
        string='Ships with Panther', compute='_compute_panther_is_carrier')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('panther_shipment_ids')
    def _compute_panther_shipment_count(self):
        data = self.env['panther.shipment']._read_group(
            [('sale_order_id', 'in', self.ids)], ['sale_order_id'], ['__count'])
        mapped = {order.id: count for order, count in data}
        for order in self:
            order.panther_shipment_count = mapped.get(order.id, 0)

    @api.depends('panther_shipment_ids.waybill')
    def _compute_panther_waybill(self):
        for order in self:
            waybills = order.panther_shipment_ids.filtered('waybill').mapped('waybill')
            order.panther_waybill = ', '.join(waybills) if waybills else False

    @api.depends('carrier_id', 'carrier_id.delivery_type')
    def _compute_panther_is_carrier(self):
        for order in self:
            order.panther_is_carrier = bool(
                order.carrier_id and order.carrier_id.delivery_type == 'panther')

    # ------------------------------------------------------------------
    # Helpers used to build the API payload
    # ------------------------------------------------------------------
    def _panther_get_weight(self):
        """Total weight (kg) of the storable/consumable lines."""
        self.ensure_one()
        weight = 0.0
        for line in self.order_line:
            if line.display_type or (('is_delivery' in line._fields) and line.is_delivery):
                continue
            product = line.product_id
            if not product or product.type == 'service':
                continue
            weight += (product.weight or 0.0) * (line.product_uom_qty or 0.0)
        return weight

    def _panther_get_product_name(self, limit=200):
        """Human readable product list, e.g. "1 x Test Phone"."""
        self.ensure_one()
        names = []
        for line in self.order_line:
            if line.display_type or (('is_delivery' in line._fields) and line.is_delivery):
                continue
            if not line.product_id:
                continue
            qty = line.product_uom_qty
            qty_txt = str(int(qty)) if float(qty).is_integer() else ('%.2f' % qty)
            names.append('%s x %s' % (qty_txt, line.product_id.name))
        text = ', '.join(names) or (self.name or '')
        return text[:limit]

    def _panther_get_picking(self):
        """The outgoing delivery order linked to this sale order, if any."""
        self.ensure_one()
        if 'picking_ids' not in self._fields:   # sale_stock not installed
            return self.env['stock.picking']
        pickings = self.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing' and p.state != 'cancel')
        return pickings.sorted(key=lambda p: p.id)[:1]

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def _panther_prepare_shipment(self):
        """Return (creating it if needed) the draft shipment of this order."""
        self.ensure_one()
        if self.state in ('draft', 'sent'):
            raise UserError(_(
                'Confirm the quotation %s before creating a Panther shipment.') % self.name)

        existing = self.panther_shipment_ids.filtered(lambda s: s.state != 'cancelled')
        with_waybill = existing.filtered('waybill')
        if with_waybill:
            raise UserError(_(
                'This order already has the Panther waybill %s.\n'
                'Open the shipment from the "Panther" smart button to refresh its status.'
            ) % ', '.join(with_waybill.mapped('waybill')))

        picking = self._panther_get_picking()

        # Safety net: the shipment record can be deleted in Odoo while the waybill
        # still exists at Panther (deleting here never cancels it there).
        # Without this check a second real - billable - shipment would be created.
        if picking and picking.carrier_tracking_ref and not self.env.context.get(
                'panther_force_new_shipment'):
            raise UserError(_(
                'The delivery order %(picking)s already carries the waybill '
                '%(waybill)s, so this order has already been sent to Panther '
                '(the shipment record was probably deleted in Odoo, which does '
                'NOT cancel it at Panther).\n\n'
                'Creating another one would produce a second billable shipment.\n'
                'If you really want a new waybill, clear the "Tracking Reference" '
                'field on %(picking)s first.'
            ) % {'picking': picking.name, 'waybill': picking.carrier_tracking_ref})

        vals = self.env['panther.shipment']._prepare_vals_from_sale_order(self, picking=picking)
        draft = existing.filtered(lambda s: s.state in ('draft', 'error'))[:1]
        if draft:
            draft.write(vals)
            return draft
        return self.env['panther.shipment'].create(vals)

    def action_create_panther_shipment(self):
        """Part 5 - main demo button."""
        self.ensure_one()
        shipment = self._panther_prepare_shipment()
        try:
            shipment._send_to_panther()
        except UserError as exc:
            message = exc.args[0] if exc.args else str(exc)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Panther Express'),
                    'message': message,
                    'type': 'danger',
                    'sticky': True,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'panther.shipment',
                        'res_id': shipment.id,
                        'view_mode': 'form',
                    },
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panther Shipment'),
            'res_model': 'panther.shipment',
            'res_id': shipment.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_panther_create_shipments(self):
        """Bulk version: select several orders in the list and send them all.

        Bound to the "Create Panther Shipments" entry of the Action menu.
        """
        sent, skipped, errors = [], [], []
        for order in self:
            try:
                shipment = order._panther_prepare_shipment()
                shipment._send_to_panther()
                sent.append('%s -> %s' % (order.name, shipment.waybill))
            except UserError as exc:
                message = exc.args[0] if exc.args else str(exc)
                if 'already' in message:
                    skipped.append(order.name)
                else:
                    errors.append('%s: %s' % (order.name, message))

        lines = []
        if sent:
            lines.append(_('Sent (%s):') % len(sent))
            lines.extend(sent)
        if skipped:
            lines.append(_('Already sent, skipped: %s') % ', '.join(skipped))
        if errors:
            lines.append(_('Failed:'))
            lines.extend(errors)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panther Express'),
                'message': '\n'.join(lines) or _('Nothing to do.'),
                'type': 'danger' if errors else ('success' if sent else 'warning'),
                'sticky': bool(errors or len(sent) > 1),
            },
        }

    def action_view_panther_shipments(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'panther_express_shipping.action_panther_shipment')
        shipments = self.panther_shipment_ids
        if len(shipments) == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': shipments.id,
            })
        else:
            action['domain'] = [('sale_order_id', '=', self.id)]
        action['context'] = {'default_sale_order_id': self.id}
        return action

    def action_panther_test_connection(self):
        return self.env['panther.shipment'].action_test_connection()
