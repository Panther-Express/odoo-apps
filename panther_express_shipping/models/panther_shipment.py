# -*- coding: utf-8 -*-
"""Panther Express shipment: the Odoo mirror of a waybill created in Panther."""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .panther_status import SHIPMENT_STATES

_logger = logging.getLogger(__name__)

DONE_STATES = ('delivered', 'returned', 'cancelled')


class PantherShipment(models.Model):
    _name = 'panther.shipment'
    _description = 'Panther Express Shipment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        index=True, default=lambda self: _('New'))
    state = fields.Selection(
        SHIPMENT_STATES, string='State', default='draft', required=True,
        tracking=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    user_id = fields.Many2one('res.users', string='Created by', default=lambda self: self.env.user)

    # ---------------------------------------------------------------- links
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', index=True, ondelete='set null')
    picking_id = fields.Many2one('stock.picking', string='Delivery Order', index=True, ondelete='set null')
    carrier_id = fields.Many2one('delivery.carrier', string='Delivery Method')
    partner_id = fields.Many2one('res.partner', string='Customer', index=True)

    # ------------------------------------------------- Panther answer (Part 6)
    waybill = fields.Char(string='Waybill', copy=False, index=True, tracking=True)
    panther_id = fields.Char(string='Panther ID', copy=False, readonly=True)
    qr_code = fields.Char(string='QR Code', copy=False, readonly=True)
    tracking_url = fields.Char(string='Tracking URL', compute='_compute_tracking_url')

    # ------------------------------------------- request payload (Part 5 map)
    client_name = fields.Char(string='Client Name', help='Mapped to client_name')
    phone_1 = fields.Char(string='Phone', help='Mapped to phone_1')
    address = fields.Char(string='Address', help='Mapped to address')
    order_ref = fields.Char(string='Order Number', help='Mapped to order_id')
    price = fields.Monetary(string='Order Total', currency_field='currency_id', help='Mapped to price')
    product_name = fields.Char(string='Product', help='Mapped to product_name')
    weight = fields.Float(string='Weight (kg)', digits='Stock Weight', help='Mapped to weight')
    sector_id = fields.Char(string='Sector ID', help='Mapped to sector_id')
    service_type = fields.Integer(string='Service Type', default=1)

    sender_name = fields.Char(string='Sender Name')
    sender_phone = fields.Char(string='Sender Phone')
    sender_address = fields.Char(string='Sender Address')
    sender_sector = fields.Char(string='Sender Sector')

    # --------------------------------------------------------- status (P7/P8)
    status_id = fields.Char(string='Panther Status ID', tracking=True)
    status_ar = fields.Char(string='Status (AR)')
    status_en = fields.Char(string='Status (EN)', tracking=True)
    status_note = fields.Text(string='Status Notes')
    last_status_update = fields.Datetime(string='Last Status Update', readonly=True)
    history_ids = fields.One2many(
        'panther.shipment.status.history', 'shipment_id', string='Status History', readonly=True)

    # ------------------------------------------------------------- debugging
    request_json = fields.Text(string='Last Request', readonly=True, copy=False)
    response_json = fields.Text(string='Last Response', readonly=True, copy=False)
    error_message = fields.Text(string='Error', readonly=True, copy=False)
    sent_date = fields.Datetime(string='Sent On', readonly=True, copy=False)

    _sql_constraints = [
        ('waybill_uniq', 'unique(waybill)', 'This waybill already exists in Odoo.'),
    ]

    # ------------------------------------------------------------------
    # Compute / CRUD
    # ------------------------------------------------------------------
    @api.depends('waybill')
    def _compute_tracking_url(self):
        base = self.env['panther.api']._get_config().get('tracking_url') or ''
        for shipment in self:
            if shipment.waybill and base:
                shipment.tracking_url = base.replace('{waybill}', shipment.waybill) \
                    if '{waybill}' in base else (base.rstrip('/') + '/' + shipment.waybill)
            else:
                shipment.tracking_url = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('panther.shipment') or _('New')
        return super().create(vals_list)

    @api.depends('name', 'waybill')
    def _compute_display_name(self):
        for shipment in self:
            shipment.display_name = shipment.waybill or shipment.name

    # ------------------------------------------------------------------
    # Data preparation (Part 5 - field mapping)
    # ------------------------------------------------------------------
    @api.model
    def _format_address(self, partner):
        if not partner:
            return ''
        parts = [
            partner.street, partner.street2,
            partner.city,
            partner.state_id.name if partner.state_id else '',
            partner.zip,
            partner.country_id.name if partner.country_id else '',
        ]
        return ', '.join([p.strip() for p in parts if p and p.strip()])

    @api.model
    def _format_phone(self, partner):
        if not partner:
            return ''
        phone = partner.phone or partner.mobile or ''
        return phone.replace(' ', '').strip()

    @api.model
    def _prepare_vals_from_sale_order(self, order, picking=None):
        """Build the panther.shipment values out of a sale order (+ optional picking)."""
        cfg = self.env['panther.api']._get_config()
        partner = order.partner_shipping_id or order.partner_id
        carrier = order.carrier_id if 'carrier_id' in order._fields else False

        weight = order._panther_get_weight()
        if picking and getattr(picking, 'shipping_weight', 0.0):
            weight = picking.shipping_weight or weight
        if not weight:
            weight = cfg['default_weight']

        sector = partner.panther_sector_id or ''
        if not sector and carrier and carrier.panther_sector_id:
            sector = carrier.panther_sector_id
        if not sector:
            sector = cfg['default_sector_id']

        service_type = cfg['service_type']
        if carrier and carrier.delivery_type == 'panther' and carrier.panther_service_type:
            service_type = carrier.panther_service_type

        return {
            'sale_order_id': order.id,
            'picking_id': picking.id if picking else False,
            'partner_id': partner.id,
            'carrier_id': carrier.id if carrier else False,
            'company_id': order.company_id.id,
            'currency_id': order.currency_id.id,
            # --- mapping requested in Part 5
            'client_name': partner.name or order.partner_id.name or '',
            'phone_1': self._format_phone(partner) or self._format_phone(order.partner_id),
            'address': self._format_address(partner),
            'order_ref': order.name,
            'price': order.amount_total,
            'product_name': order._panther_get_product_name(),
            'weight': weight,
            'sector_id': sector,
            'service_type': service_type,
            # --- sender (Part 3 configuration)
            'sender_name': cfg['sender_name'] or order.company_id.name,
            'sender_phone': cfg['sender_phone'] or order.company_id.phone or '',
            'sender_address': cfg['sender_address'] or self._format_address(order.company_id.partner_id),
            'sender_sector': cfg['sender_sector'],
        }

    def _prepare_shipment_payload(self):
        """Return the JSON payload of one shipment for ``addBulkShipments``."""
        self.ensure_one()
        cfg = self.env['panther.api']._get_config()

        def _s(value):
            return '' if value in (None, False) else str(value).strip()

        return {
            'sector_id': _s(self.sector_id or cfg['default_sector_id']),
            'product_name': _s(self.product_name),
            'phone_1': _s(self.phone_1),
            'service_type': int(self.service_type or cfg['service_type'] or 1),
            'price': '%.2f' % (self.price or 0.0),
            'weight': '%.2f' % (self.weight or cfg['default_weight'] or 1.0),
            'address': _s(self.address),
            'client_name': _s(self.client_name),
            'order_id': _s(self.order_ref or self.name),
            'sender_name': _s(self.sender_name or cfg['sender_name']),
            'sender_phone': _s(self.sender_phone or cfg['sender_phone']),
            'sender_address': _s(self.sender_address or cfg['sender_address']),
            'sender_sector': _s(self.sender_sector or cfg['sender_sector']),
        }

    def _check_ready_to_send(self):
        self.ensure_one()
        missing = []
        if not self.client_name:
            missing.append(_('Client Name'))
        if not self.phone_1:
            missing.append(_('Phone'))
        if not self.address:
            missing.append(_('Address'))
        if missing:
            raise UserError(_(
                'The shipment %(ref)s cannot be sent, the customer data is incomplete.\n'
                'Missing: %(missing)s'
            ) % {'ref': self.name, 'missing': ', '.join(missing)})

    # ------------------------------------------------------------------
    # Panther calls
    # ------------------------------------------------------------------
    def _send_to_panther(self):
        """Create the shipment in Panther. Raises UserError on failure."""
        self.ensure_one()
        if self.waybill:
            raise UserError(_('Shipment %(ref)s already has the waybill %(wb)s.') % {
                'ref': self.name, 'wb': self.waybill})
        self._check_ready_to_send()

        payload = self._prepare_shipment_payload()
        result = self.env['panther.api'].add_bulk_shipments([payload])

        self.sudo().write({
            'request_json': json.dumps(result['request'], indent=2, ensure_ascii=False),
            'response_json': (json.dumps(result['data'], indent=2, ensure_ascii=False)
                              if result['data'] is not None else result['raw']),
        })

        if result['error']:
            self.sudo().write({'state': 'error', 'error_message': result['error']})
            raise UserError(_('Panther Express refused the shipment %(ref)s:\n\n%(err)s') % {
                'ref': self.name, 'err': result['error']})

        api = self.env['panther.api']
        rows = api._response_rows(result['data'])
        row = False
        for candidate in rows:
            if str(api._pick(candidate, 'order_id')) == str(payload['order_id']):
                row = candidate
                break
        if not row and rows:
            row = rows[0]

        waybill = str(api._pick(row or {}, 'waybill', 'awb', 'waybill_no', 'tracking_number') or '')
        if not waybill:
            error = _('Panther Express did not return a waybill.\nRaw response:\n%s') % result['raw'][:500]
            self.sudo().write({'state': 'error', 'error_message': error})
            raise UserError(error)

        self.write({
            'waybill': waybill,
            'panther_id': str(api._pick(row, 'id', 'shipment_id') or ''),
            'qr_code': str(api._pick(row, 'qr_code', 'qrcode', 'qr') or ''),
            'state': 'sent',
            'error_message': False,
            'sent_date': fields.Datetime.now(),
        })
        self.message_post(body=_('Shipment created in Panther Express. Waybill: <b>%s</b>') % waybill)
        self._propagate_waybill()
        return waybill

    def _propagate_waybill(self):
        """Store the waybill on the Delivery Order (Part 6)."""
        for shipment in self:
            picking = shipment.picking_id
            if not picking and shipment.sale_order_id:
                picking = shipment.sale_order_id._panther_get_picking()
                if picking:
                    shipment.picking_id = picking.id
            if picking and shipment.waybill:
                vals = {'carrier_tracking_ref': shipment.waybill}
                if 'panther_shipment_id' in picking._fields and not picking.panther_shipment_id:
                    vals['panther_shipment_id'] = shipment.id
                if not picking.carrier_id and shipment.carrier_id:
                    vals['carrier_id'] = shipment.carrier_id.id
                picking.sudo().write(vals)
                picking.sudo().message_post(
                    body=_('Panther Express waybill: <b>%s</b>') % shipment.waybill)

    def _refresh_status(self):
        """Call ``getCurrentStatus`` and apply the answer. Raises on failure."""
        self.ensure_one()
        if not self.waybill:
            raise UserError(_('Shipment %s has no waybill yet.') % self.name)

        api = self.env['panther.api']
        result = api.get_current_status(self.waybill)
        self.sudo().write({
            'response_json': (json.dumps(result['data'], indent=2, ensure_ascii=False)
                              if result['data'] is not None else result['raw']),
        })
        if result['error']:
            self.sudo().write({'error_message': result['error']})
            raise UserError(_('Cannot read the status of %(wb)s:\n\n%(err)s') % {
                'wb': self.waybill, 'err': result['error']})

        rows = api._response_rows(result['data'])
        if not rows:
            raise UserError(_('Panther Express returned no status for %(wb)s.\nRaw:\n%(raw)s') % {
                'wb': self.waybill, 'raw': result['raw'][:500]})
        row = rows[0]
        # the live API answers [{"waybill": ..., "name_en": ..., "name_ar": ...}]
        # (no status_id at all), the webhook sends status_id/status_en/status_ar.
        self._apply_status(
            status_id=api._pick(row, 'status_id', 'status', 'state_id'),
            status_ar=api._pick(row, 'status_ar', 'state_ar', 'status_arabic', 'name_ar'),
            status_en=api._pick(row, 'status_en', 'state_en', 'status_english',
                                'status_name', 'name_en'),
            notes=api._pick(row, 'notes', 'note', 'comment', 'remarks'),
            source='api',
        )
        self.sudo().write({'error_message': False})
        return True

    # ------------------------------------------------------------------
    # Status application (shared by the API refresh and the webhook - Part 8)
    # ------------------------------------------------------------------
    def _apply_status(self, status_id=None, status_ar=None, status_en=None,
                      notes=None, source='webhook'):
        mapping_model = self.env['panther.status.mapping'].sudo()
        for shipment in self:
            status_id = '' if status_id in (None, False) else str(status_id).strip()
            label_en, label_ar = mapping_model._labels_for(status_id, status_en, status_ar)
            status_en = status_en or label_en or shipment.status_en
            status_ar = status_ar or label_ar or shipment.status_ar
            if not status_id:
                # getCurrentStatus returns the name only: recover the id from the mapping
                row = mapping_model._match(False, status_en, status_ar)
                status_id = row.status_id or ''

            vals = {
                'status_id': status_id or shipment.status_id,
                'status_en': status_en or '',
                'status_ar': status_ar or '',
                'last_status_update': fields.Datetime.now(),
            }
            if notes not in (None, False):
                vals['status_note'] = notes
            state = mapping_model._state_for(status_id, status_en, status_ar)
            if state:
                vals['state'] = state
            shipment.sudo().write(vals)

            self.env['panther.shipment.status.history'].sudo().create({
                'shipment_id': shipment.id,
                'status_id': status_id,
                'status_ar': status_ar or '',
                'status_en': status_en or '',
                'notes': notes or '',
                'source': source,
            })
            shipment.sudo().message_post(body=_(
                'Status update (%(source)s): <b>[%(sid)s] %(en)s</b> %(ar)s<br/>%(notes)s'
            ) % {
                'source': source,
                'sid': status_id or '-',
                'en': status_en or '',
                'ar': status_ar or '',
                'notes': notes or '',
            })
        return True

    # ------------------------------------------------------------------
    # Buttons (Part 9 - Test Connection / Create Shipment / Refresh Status)
    # ------------------------------------------------------------------
    @api.model
    def _notify(self, title, message, kind='success', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': kind,          # success / warning / danger / info
                'sticky': sticky,
            },
        }

    def action_create_shipment(self):
        """Button: Create Shipment."""
        created, errors = [], []
        for shipment in self.filtered(lambda s: not s.waybill):
            try:
                created.append(shipment._send_to_panther())
            except UserError as exc:
                errors.append('%s: %s' % (shipment.name, exc.args[0] if exc.args else exc))
        if errors:
            return self._notify(_('Panther Express'), '\n'.join(errors), kind='danger', sticky=True)
        if not created:
            return self._notify(
                _('Panther Express'), _('Nothing to send: every shipment already has a waybill.'),
                kind='warning')
        return self._notify(
            _('Shipment created'),
            _('Waybill: %s') % ', '.join(created), kind='success')

    def action_refresh_status(self):
        """Button: Refresh Status."""
        errors = []
        done = 0
        for shipment in self.filtered('waybill'):
            try:
                shipment._refresh_status()
                done += 1
            except UserError as exc:
                errors.append('%s: %s' % (shipment.waybill, exc.args[0] if exc.args else exc))
        if errors:
            return self._notify(_('Panther Express'), '\n'.join(errors), kind='danger', sticky=True)
        return self._notify(
            _('Status refreshed'),
            _('%s shipment(s) updated from Panther Express.') % done, kind='success')

    def action_test_connection(self):
        """Button: Test Connection."""
        ok, message = self.env['panther.api'].test_connection()
        return self._notify(
            _('Panther Express connection'), message,
            kind='success' if ok else 'danger', sticky=not ok)

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'error_message': False})
        return True

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
        }

    def action_open_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # Scheduled action: refresh the shipments still on the road
    # ------------------------------------------------------------------
    @api.model
    def _cron_refresh_status(self, limit=50):
        shipments = self.search([
            ('waybill', '!=', False),
            ('state', 'not in', DONE_STATES),
        ], limit=limit)
        for shipment in shipments:
            try:
                shipment._refresh_status()
                self.env.cr.commit()
            except Exception as exc:  # noqa: BLE001 - a cron must never die
                self.env.cr.rollback()
                _logger.warning('Panther cron: cannot refresh %s: %s', shipment.waybill, exc)
        return True


class PantherShipmentStatusHistory(models.Model):
    _name = 'panther.shipment.status.history'
    _description = 'Panther Shipment Status History'
    _order = 'create_date desc, id desc'

    shipment_id = fields.Many2one(
        'panther.shipment', string='Shipment', required=True, ondelete='cascade', index=True)
    waybill = fields.Char(related='shipment_id.waybill', store=True, string='Waybill')
    status_id = fields.Char(string='Status ID')
    status_ar = fields.Char(string='Status (AR)')
    status_en = fields.Char(string='Status (EN)')
    notes = fields.Text(string='Notes')
    source = fields.Selection(
        [('api', 'API'), ('webhook', 'Webhook'), ('manual', 'Manual')],
        string='Source', default='webhook')
