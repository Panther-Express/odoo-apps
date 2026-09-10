# -*- coding: utf-8 -*-
"""Mapping between the Panther ``status_id`` values and the Odoo shipment state."""
from odoo import _, api, fields, models

# Internal state of a Panther shipment inside Odoo
SHIPMENT_STATES = [
    ('draft', 'Draft'),
    ('sent', 'Sent to Panther'),
    ('picked_up', 'Picked Up'),
    ('in_transit', 'In Transit'),
    ('out_for_delivery', 'Out for Delivery'),
    ('delivered', 'Delivered'),
    ('returned', 'Returned'),
    ('cancelled', 'Cancelled'),
    ('error', 'Error'),
]

# Fallback keyword matching when a status_id is unknown.
# Order matters: the most specific wording comes first.
_KEYWORDS = (
    ('pickup request', 'sent'),
    ('طلب بيك', 'sent'),
    ('deliver', 'delivered'),
    ('تسليم', 'delivered'),
    ('return', 'returned'),
    ('مرتجع', 'returned'),
    ('cancel', 'cancelled'),
    ('ملغ', 'cancelled'),
    ('out for', 'out_for_delivery'),
    ('خرجت', 'out_for_delivery'),
    ('transit', 'in_transit'),
    ('الطريق', 'in_transit'),
    ('pick', 'picked_up'),
    ('استلام', 'picked_up'),
    ('creat', 'sent'),
    ('انشاء', 'sent'),
)


class PantherStatusMapping(models.Model):
    _name = 'panther.status.mapping'
    _description = 'Panther Express Status Mapping'
    _order = 'sequence, status_id'

    sequence = fields.Integer(default=10)
    status_id = fields.Char(
        string='Panther Status ID', index=True,
        help='Value of "status_id" sent by the Panther webhook. '
             'Can stay empty: getCurrentStatus only returns the status name, '
             'so rows are also matched on the English / Arabic name.')
    name_en = fields.Char(string='Status (EN)', required=True)
    name_ar = fields.Char(string='Status (AR)')
    state = fields.Selection(
        SHIPMENT_STATES, string='Odoo State', required=True, default='in_transit',
        help='Internal state applied on the shipment when this status is received.')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('status_id_uniq', 'unique(status_id)', 'This Panther status id already exists.'),
    ]

    @api.depends('status_id', 'name_en')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '[%s] %s' % (record.status_id or '?', record.name_en or '')

    @api.model
    def _find(self, status_id):
        if status_id in (None, '', False):
            return self.browse()
        return self.with_context(active_test=False).search(
            [('status_id', '=', str(status_id).strip())], limit=1)

    @api.model
    def _find_by_name(self, status_en=None, status_ar=None):
        """getCurrentStatus only returns the status name, so match on it."""
        domain = []
        for field, value in (('name_en', status_en), ('name_ar', status_ar)):
            value = (value or '').strip()
            if value:
                domain.append((field, '=ilike', value))
        if not domain:
            return self.browse()
        if len(domain) == 2:
            domain = ['|'] + domain
        return self.with_context(active_test=False).search(domain, limit=1)

    @api.model
    def _match(self, status_id=None, status_en=None, status_ar=None):
        """Return the mapping row for a status received from the API/webhook."""
        return self._find(status_id) or self._find_by_name(status_en, status_ar)

    @api.model
    def _state_for(self, status_id, status_en=None, status_ar=None):
        """Return the Odoo state for a Panther status, or ``False``."""
        mapping = self._match(status_id, status_en, status_ar)
        if mapping:
            return mapping.state
        haystack = ' '.join(filter(None, [str(status_en or ''), str(status_ar or '')])).lower()
        for needle, state in _KEYWORDS:
            if needle in haystack:
                return state
        return False

    @api.model
    def _labels_for(self, status_id, status_en=None, status_ar=None):
        """Return ``(name_en, name_ar)`` of the matching row."""
        mapping = self._match(status_id, status_en, status_ar)
        if mapping:
            return mapping.name_en, mapping.name_ar
        return '', ''

    def action_open_shipments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipments - %s') % self.name_en,
            'res_model': 'panther.shipment',
            'view_mode': 'tree,form',
            'domain': [('status_id', '=', self.status_id)],
        }
