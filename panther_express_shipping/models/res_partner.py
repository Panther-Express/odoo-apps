# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    panther_sector_id = fields.Char(
        string='Panther Sector ID',
        help='Panther Express destination sector of this address. '
             'When empty the default sector of the configuration is used.')
